# 리스트 공통화 — BE 상세 설계 (원문)

> 2026-07-22 실측 기반 설계 원문. 채택 결정·수정사항은 [LIST-COMMONALIZATION.md](./LIST-COMMONALIZATION.md) 가 우선한다.
> 원문 대비 채택 변경: apply_sort(정렬 레일)는 보류(표기법 '-camelCase' 만 합의), bare list 4종(/users·/org-units·/agent-access·/agents)의 envelope 소급 전환 취소(신규 엔드포인트부터 적용), /runs limit 상한은 100→200 통일(의도 명시).

# BE 리스트 조회 공통화 아키텍처 제안

리포: `/Users/wishdev/et-works/dashboard-design/backend` (FastAPI + SQLAlchemy async, 테이블 22개·라우터 10개·리스트성 엔드포인트 ~13개)

## 0. 설계 원칙 (규모 판정)

- 리스트 엔드포인트 대부분이 30줄 이내이고, 실측된 고통은 **쿼리 구성이 아니라 clamp·count·envelope 의 복붙**이다 — `me_codes.py:308-309`/`me_codes.py:470-471`/`runs.py:515-516` 의 수동 clamp 3중복, `logs.py:36-42` vs `me_codes.py:301-307` 의 count+rows 이중 조립.
- 따라서 **도메인별 Repository 클래스는 채택하지 않는다.** 함수형 제네릭 헬퍼 3개(페이지 의존성·페이지네이터·정렬 화이트리스트) + envelope 제네릭 스키마 2개가 이 규모의 정답이다. Repository 는 스토리지 교체·목킹 수요가 있을 때의 도구인데 이 리포는 단일 PG(+SQLite 테스트)이고 이미 `conftest.py` 가 실 DB 테스트를 돌린다.

---

## 1. 공용 리스트 쿼리 계층 — `app/core/listing.py` (신규)

```python
\"\"\"공용 리스트 조회 레일 — 페이지 파라미터·count+rows 페이지네이터·정렬 화이트리스트.

기존 3중복 수동 clamp(me_codes.py:308,470 / runs.py:515)와 count·rows 이중 필터
조립(logs.py:36-42, me_codes.py:301-307)을 대체한다.
\"\"\"
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Generic, Sequence, TypeVar

from fastapi import Depends, HTTPException, Query
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

DEFAULT_LIMIT = 50
MAX_LIMIT = 200  # logs.py:23 의 le=200 과 동일 상한.

T = TypeVar(\"T\")


@dataclass(frozen=True)
class PageParams:
    limit: int = DEFAULT_LIMIT
    offset: int = 0


def page_params(
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageParams:
    \"\"\"수동 clamp 대신 FastAPI Query 검증(범위 밖=422)로 통일.\"\"\"
    return PageParams(limit=limit, offset=offset)


PageQuery = Annotated[PageParams, Depends(page_params)]


@dataclass(frozen=True)
class Page(Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


async def paginate(db: AsyncSession, stmt: Select, page: PageParams) -> Page:
    \"\"\"필터가 붙은 rows 쿼리 하나에서 count 를 파생 — 조건을 두 번 붙이지 않는다.\"\"\"
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = (await db.execute(count_stmt)).scalar_one()
    rows = (await db.execute(stmt.limit(page.limit).offset(page.offset))).scalars().all()
    return Page(items=list(rows), total=int(total), limit=page.limit, offset=page.offset)


def page_slice(rows: Sequence[T], page: PageParams) -> Page[T]:
    \"\"\"파이썬 인메모리 필터 경로(/me/catalog, me_codes.py:538) 전용 — envelope 만 통일.\"\"\"
    return Page(
        items=list(rows[page.offset : page.offset + page.limit]),
        total=len(rows), limit=page.limit, offset=page.offset,
    )


def apply_sort(
    stmt: Select,
    sort: str | None,
    allowed: dict[str, ColumnElement],
    *,
    default: str,
    tiebreak: ColumnElement,
) -> Select:
    \"\"\"'-loggedAt'/'loggedAt' 형식. 화이트리스트 밖 키는 422. tiebreak(PK 등)로 페이지 간
    순서 안정화 — me_codes.py:299 의 norm_merchant 타이브레이크 관행을 규칙화.\"\"\"
    key = (sort or default).strip()
    descending = key.startswith(\"-\")
    col = allowed.get(key.lstrip(\"-\"))
    if col is None:
        raise HTTPException(status_code=422, detail=f\"정렬할 수 없는 필드입니다: {key}\")
    return stmt.order_by(col.desc() if descending else col.asc(), tiebreak)
```

**필터 조립은 공통화하지 않는다.** `paginate` 가 rows 쿼리에서 count 를 파생하므로, 필터는 라우터/서비스가 평범한 `stmt.where(...)` 로 한 번만 붙이면 끝이다. 현행 이중 조립(`logs.py:38-40` 의 for 루프)의 원인 자체가 사라지므로 별도 필터 DSL 은 과추상화다.

**정렬 화이트리스트 운용 규칙**: wire 키는 camelCase(`-loggedAt`), 값은 컬럼. **인덱스가 있는 컬럼만 등록**한다(예: `AccessLog.logged_at` 은 인덱스 있음 `access_log.py:31-36` — 등록 가능. `AccessLog.status` 는 미인덱스 — 필터는 허용하되 정렬 키 미등록). 정렬 파라미터가 필요 없는 목록(고정 최신순 등)은 `sort` 파라미터를 아예 노출하지 않고 `apply_sort(stmt, None, ...)` 로 기본값만 쓴다 — 현행 `/logs` 고정 정렬(`logs.py:37`)과 호환.

### 적용 예 — /logs 리라이트 (wire 불변)

```python
@router.get(\"\", response_model=AccessLogPage)
async def list_access_logs(
    db: DbSession,
    _actor: Annotated[User, Depends(require_permission(LOGS_READ))],
    page: PageQuery,
    q: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
) -> AccessLogPage:
    stmt = select(AccessLog)
    if q and q.strip():
        stmt = stmt.where(AccessLog.omnisol_userid.ilike(f\"%{q.strip()}%\"))
    if status in (\"success\", \"failed\"):
        stmt = stmt.where(AccessLog.status == status)
    stmt = apply_sort(stmt, None, {\"loggedAt\": AccessLog.logged_at},
                      default=\"-loggedAt\", tiebreak=AccessLog.id)
    result = await paginate(db, stmt, page)
    # displayName 일괄 User 조회(logs.py:45-50)는 그대로 — 레일 밖의 화면 특화 후처리.
    ...
```

`logs.py:30-43` 의 conditions 리스트·count_stmt/rows_stmt 이중 조립 14줄이 5줄로 줄고, clamp 는 의존성이 흡수한다.

---

## 2. 응답 envelope 표준 — `app/schemas/common.py` 확장

### 실태와 결정

`schemas/common.py:9-14` 는 `CamelModel` 하나뿐이고 리스트 응답은 7가지 형태가 공존한다: bare list(`users.py:42`, `org_units.py:85·199`, `agents.py:61-75`), `{items}`(`me_codes.py:90·370`, `skills.py:46`), `{total,limit,offset,items}`(`me_codes.py:352`), `{items,total,syncedAt}`(`me_codes.py:547-551`), `{logs,total}`(`schemas/log.py:23-25`), `{runs,total}`(`runs.py:523`), `{templates}`(`runs.py:489`).

**표준은 2단계로 확정한다** (page/size 가 아니라 limit/offset — 현행 3개 페이지네이션 엔드포인트와 FE 클라이언트 `src/lib/api/me-codes.ts:14`, `src/lib/live/runs-api.ts:12` 가 전부 limit/offset 이므로 양쪽 churn 이 0 인 쪽):

```python
# app/schemas/common.py 에 추가
from typing import Generic, TypeVar

ItemT = TypeVar(\"ItemT\")


class ListOut(CamelModel, Generic[ItemT]):
    \"\"\"전량 목록 표준 — 페이지네이션 없는 소규모 목록(즐겨찾기·조직구분·유저 등).\"\"\"
    items: list[ItemT]
    total: int  # len(items) — FE 가 배지 카운트 등에 사용.


class ListPage(ListOut[ItemT], Generic[ItemT]):
    \"\"\"페이지 목록 표준 — {items,total,limit,offset}. me_codes.py:352 형태의 공식화.\"\"\"
    limit: int
    offset: int
```

부가 메타가 필요한 목록은 서브클래스: `class CatalogPage(ListPage[CatalogItem]): synced_at: datetime | None` → CamelModel 이 `syncedAt` 으로 직렬화(현행 `me_codes.py:550` 과 동일 키).

### 호환/이행 경로 (기존 엔드포인트별)

| 현행 형태 | 엔드포인트 | 이행 |
|---|---|---|
| `{total,limit,offset,items}` | `/me/card-learning/seed`(me_codes.py:352) | **이미 표준** — 타입만 입힘, wire 불변 |
| `{items,total,syncedAt}` | `/me/catalog`(me_codes.py:547-551) | 서브클래스로 limit/offset 키 **추가**(additive — FE `me-codes.ts:158-161` 는 아는 키만 읽음) |
| `{items}` | favorites·card-learning·seed-notes·skills | `ListOut` 으로 total 추가(additive) |
| `{logs,total}` | `/logs`(schemas/log.py:23-25) | dual-key: `items` 병기 → FE 전환 → `logs` 키 제거 |
| `{runs,total}` `{templates}` | `/runs`(runs.py:523)·`/runs/templates`(runs.py:489) | 동일 dual-key 경로 |
| bare list | `/users`·`/org-units`·`/agent-access`·`/agents` | 파괴 변경 — **FE 관용 리더 선배포** 후 전환(아래) |

**FE 관용 리더**: bare list 소비처는 `useApiResource<T[]>` 3화면(`members-client.tsx:52`, `org-access-client.tsx:34`, `agent-access-client.tsx:48-49`) + agents. `src/lib/api` 에 `unwrapItems = (res) => Array.isArray(res) ? res : res.items ?? []` 헬퍼를 먼저 배포하면, BE 가 배열→envelope 어느 시점에 바뀌어도 FE 가 흡수한다(무중단의 핵심 장치). 전환 완료 후 타입을 `ListOut<T>` 로 조인다.

**중요 — /users 에 페이지네이션을 끼워넣지 말 것**: 멤버 화면은 전량 소비 전제(`users.py:47-49` 전량 + FE 전량 렌더). envelope 전환 시 기본 limit 가 생기면 목록이 잘린다. `ListOut`(전량) 으로만 전환하고, 페이징은 화면이 실제로 페이저를 달 때 `PageQuery` 를 옵션으로 추가한다.

---

## 3. 모델 공통화 — `app/models/base.py` 확장

### 실측 근거

- `TimestampMixin`(base.py:34-45) 사용처가 User 1곳(user.py:18)뿐이고, `org_unit.py:41-46`·card_seed_selection·card_seed_note 는 **동일 컬럼을 인라인 복붙**(server_default=func.now(), onupdate=func.now() 까지 동일).
- UUID PK 보일러플레이트 `mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)` 가 ~10개 모델에 복붙(user.py:21, user_code_favorite.py:36 등).
- boolean server_default 표기 불일치: `sa.false()`(agent.py) vs 문자열 `\"false\"`(user_code_favorite.py:51) — 둘 다 PG 에서 동일 DDL 이므로 **기존은 방치, 신규는 `sa.false()` 로 통일**만 문서화.

### 믹스인 추가

```python
# app/models/base.py 에 추가
import uuid
from sqlalchemy import Uuid


class UuidPkMixin:
    \"\"\"UUID surrogate PK — 신규 도메인 테이블 기본. (user.py:21 패턴의 공식화)\"\"\"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
```

기존 모델의 믹스인 수렴(인라인 → 믹스인)은 **DDL no-op** 이므로 마이그레이션 없이 안전하다. 단, 각 스왑 후 `alembic autogenerate` diff 가 비어 있음을 확인하는 절차를 강제한다(env.py compare_type=True 환경).

### 규칙 확정 (기존 불일치의 '정리'가 아니라 '판정')

1. **PK 정책 3종을 공인**한다: (a) UUID surrogate = 신규 기본(UuidPkMixin), (b) 슬러그 String PK = wire 에 노출되는 픽스처 정의 id 전용(agents/org_units/agent_groups — 현행 유지), (c) 클라 생성 접두 id(`run-`/`tpl-`) = 현행 유지. **신규 테이블에서 (b)(c)를 새로 만들려면 설계 리뷰 필수.** 조인테이블은 자연 복합 PK(agent_org_access 스타일, org_unit.py:60-65)로 통일 — role_permissions 의 surrogate+uq 는 방치(소급 변경 이득 없음).
2. **타임스탬프 정책**: 수명주기 컬럼(created_at/updated_at)은 TimestampMixin 만 사용. **도메인 이벤트 시각은 별도 명명 컬럼으로 공인** — access_logs.logged_at(이벤트 시각), erp_code_catalog.synced_at(동기화 시각), card_*.last_used_at(사용 시각)은 '불일치'가 아니라 의미가 다른 컬럼이다. 소급 추가 금지(§doNotAbstract).
3. **인덱스 규칙**: 리스트 레일에 올라가는 컬럼은 (필터 where 대상 → 단독 인덱스 검토, 정렬 화이트리스트 등재 → 인덱스 필수, 소유자 스코프 → (user_id, ...) 복합) 를 신규 테이블 체크리스트로. 기존 보강은 실제 병목 확인 후만: access_logs.status 는 이진 카디널리티라 단독 인덱스 무익 — 로그 누적으로 /logs 가 느려지면 `(status, logged_at)` 복합으로. org_units.parent_id 는 수십 행 테이블이라 불필요.
4. **naming_convention(base.py:17-23)은 그대로** — 이미 올바른 공통화가 되어 있는 부분.

---

## 4. 서비스 계층 규칙

현황: 리스트 쿼리는 전부 라우터 인라인(logs.py:19-72, users.py:43-48, agents.py:62-75, org_units.py:79-90, me_codes.py 전반)이고, 서비스는 쓰기 헬퍼(services/access_log.py)·직렬화+집계(services/agents.py)만 있다. **이 리포 규모에서 '모든 리스트를 서비스로' 는 세리머니다.** 규칙은 3버킷으로:

1. **라우터에 남긴다**: 파라미터 검증(Query/PageQuery)·권한 게이트(Depends)·HTTP 상태 — 그리고 **레일 위에서 ~15줄 이내로 끝나는 리스트 조회**. §1 적용 후 /logs·/users·favorites 는 이 기준에 들어온다.
2. **서비스로 내린다**: (a) **두 라우터 이상이 쓰는 로직** — 조직접근 가시성 게이트가 1순위: agents.py:53-58(_visible)과 runs.py:197-225 인라인이 이중 구현이고 runs.py:36 이 프라이빗 심볼(_HIDDEN_AGENT_IDS, _is_org_admin)을 직접 import 한다 → `app/services/agent_visibility.py` 로 승격(visible_agents(db, user) / ensure_can_run(db, user, agent)). (b) 직렬화 dict 빌더가 30줄 넘는 것(runs.py:433-465 의 _run_summary/_run_detail → services/runs_serialize.py 또는 pydantic Out 전환 시 자연 소멸). (c) ERP/외부 IO(현행 code_sync 등 — 이미 준수).
3. **core 로 올린다**(도메인 무관 횡단): `RequireAdmin` 별칭 → core/deps.py(현재 org_units.py:26·agents.py:35 재정의), `_omnisol_password` → `app/core/creds.py`(me_codes.py:555-570 이 runs.py:130-151 복붙임을 docstring 이 자인), `reorder_by_client_order(rows, ordered_ids)` 순수 함수 → `app/services/ordering.py`(org_units.py:183-192 ≒ me_codes.py:162-171), `get_owned_or_none(db, Model, raw_id, user_id)`(uuid 파싱 try/except→소유자 where→None, me_codes.py:127-145·176-195·279-282 의 3중복), user→OrgUnit cost_type 조회(me_codes.py:417-421·442-446·runs.py:261-264 3중복) → `app/services/org_lookup.py` 의 `user_cost_type(db, user)`.

**세션 컨벤션**: 서비스는 `AsyncSession` 주입이 표준(services/access_log.py·agents.py 현행). `services/cost_project.py:28-40` 의 자체 `get_sessionmaker()` 개설은 LangGraph 노드 내부라는 사정이 있으므로 예외로 문서화하되, HTTP 경로 서비스에서는 금지.

---

## 5. 신규 도메인 추가 시나리오 — 거래처(partners) 예시

현재 거래처는 테이블이 없고(erp_code_catalog 의 kind='partner' 행 + card_* 의 norm_merchant 문자열뿐), 프로젝트관리·예산단위도 FE 픽스처만 소비한다(src/lib/data/projects.ts 등). 레일 위 온보딩은 파일 3개:

```python
# 1) app/models/partner.py — 믹스인 2개로 공통 컬럼 0줄
class Partner(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = \"partners\"
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)   # ERP 거래처코드
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    biz_no: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=\"active\")
    __table_args__ = (CheckConstraint(\"status IN ('active','archived')\", name=\"status\"),)

# 2) app/schemas/partner.py — envelope 은 제네릭 재사용
class PartnerOut(CamelModel):
    id: str
    code: str
    name: str
    biz_no: str | None
PartnerPage = ListPage[PartnerOut]  # {items,total,limit,offset} 자동

# 3) app/routers/partners.py — 리스트가 12줄
PARTNER_SORT = {\"name\": Partner.name, \"code\": Partner.code, \"createdAt\": Partner.created_at}

@router.get(\"\", response_model=PartnerPage)
async def list_partners(
    db: DbSession, _actor: RequireAdmin, page: PageQuery,
    q: Annotated[str | None, Query()] = None,
    sort: Annotated[str | None, Query()] = None,
) -> PartnerPage:
    stmt = select(Partner)
    if q and q.strip():
        like = f\"%{q.strip()}%\"
        stmt = stmt.where(or_(Partner.name.ilike(like), Partner.code.ilike(like),
                              Partner.biz_no.ilike(like)))
    stmt = apply_sort(stmt, sort, PARTNER_SORT, default=\"name\", tiebreak=Partner.id)
    p = await paginate(db, stmt, page)
    return PartnerPage(items=[PartnerOut.model_validate(r) for r in p.items],
                       total=p.total, limit=p.limit, offset=p.offset)
```

**절감 실측 대비**: 같은 기능을 현행 방식으로 쓰면 clamp 2줄 + count/rows 이중 조립 ~10줄 + 수제 camelCase dict ~10줄 + envelope 형태 결정(제각각) = /logs 급 70줄. 레일 위에서는 라우터 ~25줄, 그리고 **FE 는 ListPage 형태를 이미 알고 있으므로 unwrap/타입 재정의 불필요**.

- **프로젝트관리**: 동일 패턴으로 `projects` 1급 테이블(UuidPkMixin+TimestampMixin, slug 필드는 unique 컬럼으로 — PK 로 쓰지 않음). erp_code_catalog 의 kind='project'(파이프 합성 코드, services/cost_project.py:35-40 의 LIKE 파싱)는 ERP 캐시로 병존시키고, 관리 화면 CRUD 는 새 테이블이 담당.
- **예산단위**: 관리(CRUD) 요구가 확정되기 전까지는 erp_code_catalog 유지. 승격 시 `budget_units` 테이블 + 동기화가 catalog→테이블로 upsert 하는 구조.

---

## 6. 무중단 마이그레이션 순서 (요약)

Phase 0 레일 신설(무접촉) → Phase 1 이미 표준형 편입(wire 불변: seed/catalog/logs 내부교체) → Phase 2 FE unwrapItems 선배포 후 logs·runs dual-key → 구 키 제거 → Phase 3 bare list 4종 envelope 전환(/users 는 전량 유지) → Phase 4 횡단 중복 제거(RequireAdmin·creds·reorder·가시성 — 기존 테스트 test_agents_visibility.py·test_runs_access.py·test_org_units.py·test_me_codes.py 가 가드) → Phase 5 믹스인 수렴(autogenerate 빈 diff 검증) → Phase 6 신규 도메인(거래처→프로젝트→예산단위). 상세는 migrationOrder 필드 참조.

각 Phase 는 독립 배포 가능하며 롤백 단위다. AWS ECS + 온프렘 이중 배포 환경에서 Phase 2·3 의 FE 선배포 순서만 지키면 혼재 윈도에도 응답 파싱이 깨지지 않는다.