"""pytest 픽스처 — SQLite(파일) 인메모리 대용 DB + 시드 + 의존성 오버라이드.

실제 Playwright 브라우저나 PostgreSQL 없이 라우터/권한/시드를 단위 검증한다.
lifespan 은 ASGITransport 에서 실행되지 않으므로 DB/브라우저 부팅 없이 테스트가 돈다.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import app.db as appdb
from app.core.deps import DbSession, get_current_user, get_db, get_role_by_code
from app.main import app as fastapi_app
from app.models import Base, User
from app.services.seed import seed_all
from nbkit.omnisol import latency, verify


@pytest_asyncio.fixture
async def sm(tmp_path):
    """시드된 SQLite DB 의 async_sessionmaker."""
    url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    appdb.init_engine(url)
    async with appdb.get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = appdb.get_sessionmaker()
    async with maker() as s:
        await seed_all(s)
        await s.commit()
    yield maker
    await appdb.dispose_engine()


@pytest_asyncio.fixture
async def client(sm):
    """get_db 를 테스트 세션메이커로 오버라이드한 httpx 클라이언트."""

    async def _get_db():
        async with sm() as s:
            yield s

    fastapi_app.dependency_overrides[get_db] = _get_db
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    fastapi_app.dependency_overrides.clear()


@pytest.fixture
def make_user(sm):
    """롤 코드로 사용자를 생성하고 user_id 를 반환하는 async 헬퍼."""

    async def _make(userid: str, role_code: str, status: str = "active"):
        async with sm() as s:
            role = await get_role_by_code(s, role_code)
            u = User(
                omnisol_userid=userid,
                display_name=userid,
                status=status,
                role_id=role.id if role is not None else None,
            )
            s.add(u)
            await s.commit()
            return u.id

    return _make


@pytest.fixture
def make_agent(sm):
    """실행 게이트 테스트용 Agent 를 생성. workflow_id·access_configured·허용 조직구분 지정."""

    async def _make(
        agent_id: str,
        *,
        workflow_id: str,
        access_configured: bool = False,
        allowed_org_units: tuple[str, ...] = (),
        allow_unassigned: bool = False,
    ):
        from app.models import Agent, AgentOrgAccess

        async with sm() as s:
            s.add(
                Agent(
                    id=agent_id,
                    workflow_id=workflow_id,
                    name=agent_id,
                    description="",
                    drive="browser",
                    interaction="autonomous",
                    status="idle",
                    access_configured=access_configured,
                    allow_unassigned=allow_unassigned,
                )
            )
            for ou in allowed_org_units:
                s.add(AgentOrgAccess(agent_id=agent_id, org_unit_id=ou))
            await s.commit()
        return agent_id

    return _make


@pytest.fixture
def set_user_org(sm):
    """사용자의 org_unit_id 를 지정하는 async 헬퍼(실행 조직접근 테스트용)."""

    async def _set(user_id, org_unit_id):
        async with sm() as s:
            u = (await s.execute(select(User).where(User.id == user_id))).scalar_one()
            u.org_unit_id = org_unit_id
            await s.commit()

    return _set


@pytest.fixture
def auth_as(sm):
    """get_current_user 를 주어진 user_id 로 오버라이드한다.

    요청의 DbSession(get_db 오버라이드)을 그대로 재사용해야 한다 — 실제 운영 코드의
    get_current_user(request, db: DbSession)와 동일하게 세션을 공유해야, 엔드포인트가
    반환된 User 를 그 db 로 커밋/리프레시하는 케이스(예: PATCH /auth/me)가 성립한다.
    """

    def _set(user_id):
        async def _dep(db: DbSession):
            return (
                await db.execute(select(User).where(User.id == user_id))
            ).scalar_one()

        fastapi_app.dependency_overrides[get_current_user] = _dep

    return _set


@pytest.fixture(autouse=True)
def _disable_erp_api_sync(monkeypatch):
    """카탈로그 동기화의 API 우선 경로를 단위 테스트에서 기본 비활성.

    sync_catalog 은 이제 순수 HTTP API(app.erp.api_client)를 먼저 시도한다 — 끄지 않으면
    브라우저 경로를 몽키패치로 검증하는 기존 스모크(test_me_codes)가 실 ERP 로그인
    엔드포인트로 실제 네트워크 요청을 보낸 뒤에야 폴백한다(느림·불안정·프로덕션 ERP 타격).
    _collect_rows 는 code_sync.get_settings().erp_api_sync_enabled 만 읽으므로 그 플래그만
    False 로 스텁한다. API 경로 자체를 검증하는 테스트는 자기 test 본문에서 다시 켠다
    (monkeypatch 는 나중 setattr 가 이긴다)."""
    from types import SimpleNamespace

    from app.services import code_sync

    monkeypatch.setattr(code_sync, "get_settings", lambda: SimpleNamespace(erp_api_sync_enabled=False))


@pytest.fixture(autouse=True)
def _no_realtime_verify_backoff(monkeypatch):
    """확인 커널(nbkit.omnisol.verify)의 재시도 대기를 단위 테스트에서 무효화한다.

    커널의 기본 대기는 **실시간**(delay_scale 무관)이라, 실패 경로를 태우는 테스트가
    회차당 수 초씩 잡아먹는다. 대기 규율 자체는 sleep= 을 직접 주입하는 커널 전용
    테스트(test_verify_kernel.py)에서 검증하므로, 여기서는 no-op 으로 갈아끼운다.

    지연 배율(nbkit.omnisol.latency)도 함께 격리한다 — ① 프로세스 전역 EMA 를 매 테스트
    리셋하고 ② record 를 no-op 으로 갈아끼워, 재시도 성공 되먹임이 EMA 를 올려 다른
    테스트의 대기·폴 상한(factor)이 1.0 을 벗어나는 누수를 막는다. 배율 자체를 검증하는
    테스트(test_adaptive_latency.py)는 latency.factor/record 를 스스로 패치한다.
    """

    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(verify, "DEFAULT_SLEEP", _instant)
    latency.reset()
    monkeypatch.setattr(latency, "record", lambda *_a, **_k: None)
