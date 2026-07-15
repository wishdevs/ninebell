"""ERP 코드 카탈로그 헤드리스 동기화 — 코드피커를 훑어 erp_code_catalog 를 채운다.

fresh 헤드리스 브라우저로 카드결의 진입 체인(로그인→…→증빙유형 선택)을 태운 뒤 예산단위(bg_cd)
/프로젝트(pjt_cd) 코드피커를 전량 읽어 upsert 한다. ⚠ 저장(F7)은 하지 않는다(읽기 전용 수집).

- 예산단위(budget_unit): **전사 공용(dept='')** — 팝업 목록 자체가 전사 예산단위(=부서 단위:
  임원실·경영 본부·인사기획팀…)다. 팝업 그리드의 DEPT_NM 은 행별 소속이 아니라 로그인 사용자
  부서가 전 행 반복되는 값이라 스코프 키로 쓰지 않는다(초기 구현 오류 정정). "내 부서" 필터는
  조회 시 예산단위명 ↔ 사용자 department 정규화 매칭(norm_code_name)으로 한다.
- 프로젝트(project): 전사 공용(dept=''). 팝업 캡(500)으로 접두 스윕 합집합. 부분 스윕이 카탈로그를
  날리지 않도록, 새 집계 건수가 기존 건수 이상일 때만 stale 삭제.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.card_collect import steps
from app.agents.common.nodes import (
    make_add_row_node,
    make_login_node,
    make_menu_nav_node,
    make_open_evdn_node,
    make_select_evdn_node,
    make_set_gubun_node,
    make_user_type_node,
)
from app.models import ErpCodeCatalog
from app.services.card_seed_remap import remap_seed_notes_to_catalog

logger = logging.getLogger(__name__)

# 이름 정규화에서 제거할 문자 — 공백·구분기호·괄호(ninebell _norm_item 검증 노하우).
_NORM_STRIP_RE = re.compile(r"[\s_\-/()\[\]]+")


def norm_code_name(s: object) -> str:
    """예산단위명/부서명 정규화 — '인사/기획팀'↔'인사기획팀', '경영 본부'↔'경영본부' 매칭용."""
    return _NORM_STRIP_RE.sub("", str(s or "")).lower()


def dept_matches_budget_name(department: str | None, bg_name: str | None) -> bool:
    """사용자 소속(department)이 예산단위명(bg_name)과 같은 부서인지 — 정규화 후 상호 포함."""
    d, b = norm_code_name(department), norm_code_name(bg_name)
    if not d or not b:
        return False
    return d in b or b in d


# 프로젝트 접두 스윕 — 빈검색(초기 500) + 영숫자 + 한글 음절 대표 접두. 팝업 캡을 채우는 접두는 로그.
_PROJECT_PREFIXES: tuple[str, ...] = (
    "",
    *[chr(c) for c in range(ord("A"), ord("Z") + 1)],
    *[chr(c) for c in range(ord("0"), ord("9") + 1)],
    "가", "나", "다", "라", "마", "바", "사", "아", "자", "차", "카", "타", "파", "하",
)


async def _run_entry_chain(page, userid: str, password: str) -> None:
    """카드결의 진입 체인 7노드를 순차 실행. 실패 시 RuntimeError."""
    events: asyncio.Queue = asyncio.Queue()

    async def _drain() -> None:
        while True:
            await events.get()

    drainer = asyncio.create_task(_drain())
    state = {"page": page, "events": events, "userid": userid, "password": password, "params": {}}
    try:
        for name, node in [
            ("login", make_login_node()),
            ("user_type", make_user_type_node("회계")),
            ("menu_nav", make_menu_nav_node()),
            ("set_gubun", make_set_gubun_node("카드")),
            ("add_row", make_add_row_node()),
            ("open_evdn", make_open_evdn_node()),
            ("select_evdn", make_select_evdn_node("01")),
        ]:
            out = await node(state)
            state.update(out or {})
            if state.get("error"):
                raise RuntimeError(f"진입 실패({name}): {state['error']}")
    finally:
        drainer.cancel()


async def _sync_budget_units(page, sessionmaker: async_sessionmaker) -> int:
    rows = await steps.dump_budget_units(page)
    if not rows:
        return 0
    now = datetime.now(timezone.utc)
    codes = {r["code"] for r in rows}
    async with sessionmaker() as s:
        for r in rows:
            await s.merge(
                ErpCodeCatalog(
                    kind="budget_unit",
                    dept="",  # 전사 공용 — 부서 매칭은 조회 시 이름 정규화로.
                    code=r["code"],  # BG|BIZPLAN|BGACCT 복합(선택 단위 = 조합 행).
                    name=r["name"],
                    extra={
                        "bizplanCd": r.get("bizplanCd") or "",
                        "bizplanNm": r.get("bizplanNm") or "",
                        "bgacctCd": r.get("bgacctCd") or "",
                        "bgacctNm": r.get("bgacctNm") or "",
                    },
                    synced_at=now,
                )
            )
        # 전량 덤프이므로 kind 전체에서 stale 제거. 과거 dept 스코프로 저장된 잔여 행
        # (dept != '')은 코드가 같아도 중복이므로 함께 정리한다(초기 구현 정정 마이그레이션 겸용).
        await s.execute(
            delete(ErpCodeCatalog).where(
                ErpCodeCatalog.kind == "budget_unit",
                (ErpCodeCatalog.code.notin_(codes)) | (ErpCodeCatalog.dept != ""),
            )
        )
        await s.commit()
    # 카탈로그(9자리 예산계정)가 갱신됐으니 전사 시드(card_seed_notes)를 현 ERP 코드로 재정렬한다.
    # 옛 자료의 5자리 계정과목 코드는 현 ERP 와 겹치지 않으므로, 이름으로 현 코드에 재키잉해야
    # 개입 화면의 계정별 적요 조회(seed tier)가 실제로 매칭된다. 멱등 — 실패해도 동기화는 유지.
    try:
        async with sessionmaker() as s:
            stats = await remap_seed_notes_to_catalog(s)
        logger.info("budget_unit 동기화 후 card_seed_notes 재키잉: %s", stats)
    except Exception:  # noqa: BLE001 — 재키잉 실패가 카탈로그 동기화 성공을 되돌려선 안 된다.
        logger.exception("budget_unit 동기화 후 시드 재키잉 실패(동기화 자체는 성공)")
    return len(rows)


async def _sync_projects(page, sessionmaker: async_sessionmaker) -> int:
    # 1순위: 끝행 포커스+ArrowDown 페이지 로딩으로 전량 수집(스크롤 더보기 실측 대응).
    rows: list[dict] = []
    server_total: int | None = None
    raw_loaded = 0
    try:
        rows, server_total, raw_loaded = await steps.dump_projects_scroll(page)
    except Exception:  # noqa: BLE001 — 스크롤 수집 실패는 스윕 폴백으로.
        logger.exception("프로젝트 스크롤 수집 실패 — 접두 스윕으로 폴백")
    logger.info(
        "프로젝트 스크롤 수집 — 원시 %d행 로드(서버 total=%s), 고유 프로젝트 %d건",
        raw_loaded, server_total, len(rows),
    )
    # 완결 판정은 원시 행 수 기준 — dedupe 키가 PJT_NO|WBS_NO 복합이라 dedupe 후 행 수가
    # 원시(2,358)와 거의 같다(WBS 세분성 유지). 원시 로드가 total 에 못 미치면 접두 스윕 보강.
    if raw_loaded < (server_total or steps.PROJECT_PICKER_CAP + 1):
        logger.warning("프로젝트 로드 미달(%d/%s) — 접두 스윕 보강", raw_loaded, server_total)
        sweep_rows, cap_hit = await steps.dump_projects_sweep(page, list(_PROJECT_PREFIXES))
        if cap_hit:
            logger.warning("프로젝트 스윕 캡(500) 도달 접두 — 누락 가능: %s", ", ".join(cap_hit))
        by_code = {r["code"]: r for r in rows}
        for r in sweep_rows:
            by_code.setdefault(r["code"], r)
        rows = list(by_code.values())
    if not rows:
        return 0
    now = datetime.now(timezone.utc)
    codes = {r["code"] for r in rows}
    async with sessionmaker() as s:
        prev = (
            await s.execute(
                select(func.count())
                .select_from(ErpCodeCatalog)
                .where(ErpCodeCatalog.kind == "project", ErpCodeCatalog.dept == "")
            )
        ).scalar() or 0
        for r in rows:
            await s.merge(
                ErpCodeCatalog(
                    kind="project",
                    dept="",
                    code=r["code"],  # PJT_NO|WBS_NO 복합 — WBS 행 단위.
                    name=r["name"],
                    extra={
                        "pjtNo": r.get("pjtNo") or "",
                        "wbsNo": r.get("wbsNo") or "",
                        "wbsNm": r.get("wbsNm") or "",
                        "loc": r.get("loc") or "",
                        "useYn": r.get("useYn") or "",
                        "partnerNm": r.get("partnerNm") or "",
                    },
                    synced_at=now,
                )
            )
        # 안전장치: 부분 스윕(집계가 기존보다 적음)이면 stale 삭제를 건너뛴다(카탈로그 보존).
        if len(codes) >= prev:
            await s.execute(
                delete(ErpCodeCatalog).where(
                    ErpCodeCatalog.kind == "project",
                    ErpCodeCatalog.dept == "",
                    ErpCodeCatalog.code.notin_(codes),
                )
            )
        else:
            logger.warning(
                "프로젝트 집계(%d) < 기존(%d) — stale 삭제 생략(부분 스윕 보호)", len(codes), prev
            )
        await s.commit()
    return len(rows)


async def _sync_partners(page, sessionmaker: async_sessionmaker) -> int:
    """거래처(partner) 전량 덤프 → upsert(kind='partner', dept='') + stale 삭제(kind 스코프).

    실제 피커 덤프(dump_partners)는 Track A(trip_domestic)가 프로브 후 구현한다. 앱 기동을
    깨지 않도록 함수 내부에서 지연 import 하고, 미구현 시 한국어 오류로 실패한다(백그라운드
    태스크가 sync_state[partner].error 로 남긴다).
    """
    try:
        from app.agents.trip_domestic.steps import dump_partners
    except ImportError as exc:  # Track A 미완료 — 명확한 한국어 오류로 실패.
        raise RuntimeError("거래처 덤프 미구현 — Track A 대기") from exc

    rows = await dump_partners(page)
    now = datetime.now(timezone.utc)
    codes = {r["code"] for r in rows}
    async with sessionmaker() as s:
        prev = (
            await s.execute(
                select(func.count())
                .select_from(ErpCodeCatalog)
                .where(ErpCodeCatalog.kind == "partner")
            )
        ).scalar() or 0
        # 덤프가 비었는데 기존 카탈로그가 있으면 = 중단/실패 의심. 부분(0) 결과로 기존 3천여 건을
        # 지우지 않도록 **예외로 실패**시킨다(_run_catalog_sync 가 sync_state.error 로 남긴다).
        # 첫 적재(prev=0)에서 진짜 0건이면 정상 종료(0 반환).
        if not rows:
            if prev > 0:
                raise RuntimeError(
                    f"거래처 덤프 결과가 비어 있습니다(기존 {prev}건) — 중단/실패 의심, 카탈로그 보존"
                )
            return 0
        for r in rows:
            await s.merge(
                ErpCodeCatalog(
                    kind="partner",
                    dept="",  # 전사 공용 — 거래처 마스터는 부서 스코프가 없다.
                    code=r["code"],  # 거래처코드(선택 단위).
                    name=r["name"],  # 거래처명.
                    extra={"bizNo": r.get("bizNo") or ""},  # 사업자번호(있으면).
                    synced_at=now,
                )
            )
        # 부분 덤프 보호(_sync_projects 미러) — 집계가 기존보다 적으면 stale 삭제를 건너뛴다.
        # 페이징 중단으로 일부만 수집됐을 때 정상 거래처를 대량 삭제하는 사고를 막는다(리뷰 HIGH).
        if len(codes) >= prev:
            await s.execute(
                delete(ErpCodeCatalog).where(
                    ErpCodeCatalog.kind == "partner",
                    ErpCodeCatalog.code.notin_(codes),
                )
            )
        else:
            logger.warning(
                "거래처 집계(%d) < 기존(%d) — stale 삭제 생략(부분 덤프 보호)", len(codes), prev
            )
        await s.commit()
    return len(rows)


async def _sync_org(userid: str, password: str, browser_factory, sessionmaker: async_sessionmaker) -> dict:
    """조직도 스크레이프 → 본부▸팀 평탄화 → upsert(kind='org_unit', dept='') + stale 삭제.

    안정 ERP 코드가 없어 code 는 이름 기반: 본부='본부명', 팀='본부명|팀명'. extra 에 종류(hq/team)·
    상위 본부·인원수·정렬순서를 담는다(프론트 뷰어/향후 OrgUnit 정합용). 빈 결과는 보존 실패 처리.

    미리보기(catalog) upsert 성공 후, 실제 권한 단위인 org_units 로도 반영(apply_org_tree)하고
    department 기준 사용자 재배치(reconcile_users)한다. 반환 {count, applied, reassigned}.
    """
    from app.services.org_sync import fetch_org_tree

    tree = await fetch_org_tree(userid, password, browser_factory)
    flat = tree["flat"]
    now = datetime.now(timezone.utc)

    # (본부, 팀) → catalog code. 본부 자체도 1행(type=hq)으로 남겨 계층을 복원 가능하게 한다.
    catalog: dict[str, dict] = {}
    order = 0
    for r in flat:
        hq_code = r["hq"]
        if hq_code not in catalog:
            catalog[hq_code] = {
                "code": hq_code, "name": r["hq"],
                "extra": {"type": "hq", "hq": None, "memberCount": r.get("hqCount"), "sortOrder": order},
            }
            order += 1
        team_code = f"{r['hq']}|{r['team']}"
        if team_code not in catalog:
            catalog[team_code] = {
                "code": team_code, "name": r["team"],
                "extra": {"type": "team", "hq": r["hq"], "memberCount": r.get("teamCount"), "sortOrder": order},
            }
            order += 1

    codes = set(catalog)
    async with sessionmaker() as s:
        prev = (
            await s.execute(
                select(func.count()).select_from(ErpCodeCatalog).where(ErpCodeCatalog.kind == "org_unit")
            )
        ).scalar() or 0
        if not catalog:  # 빈 결과 — 기존 보존(스크레이프 실패 의심).
            if prev > 0:
                raise RuntimeError(f"조직도 결과가 비어 있습니다(기존 {prev}건) — 중단/실패 의심, 보존")
            return {"count": 0, "applied": {}, "reassigned": []}
        for row in catalog.values():
            await s.merge(
                ErpCodeCatalog(kind="org_unit", dept="", code=row["code"], name=row["name"], extra=row["extra"], synced_at=now)
            )
        await s.execute(
            delete(ErpCodeCatalog).where(
                ErpCodeCatalog.kind == "org_unit", ErpCodeCatalog.code.notin_(codes)
            )
        )
        await s.commit()

    # 미리보기(catalog) 반영 성공 후, 실제 권한 단위(org_units)로 멱등 반영 + 사용자 재배치.
    # 카탈로그 커밋과 분리된 세션/트랜잭션이라, 반영이 실패해도 미리보기는 이미 남는다.
    applied: dict = {}
    reassigned: list[dict] = []
    if flat:
        from app.services.org_apply import apply_org_tree, reconcile_users

        async with sessionmaker() as s:
            applied = await apply_org_tree(s, flat)
            reassigned = await reconcile_users(s)
            await s.commit()
        logger.info(
            "조직도 org_units 반영 — 추가 %d·갱신 %d·미변경 %d·ERP미포함 %d·사용자 재배치 %d명",
            len(applied.get("added", [])),
            len(applied.get("updated", [])),
            applied.get("unchanged", 0),
            len(applied.get("local_only", [])),
            len(reassigned),
        )
    return {"count": len(catalog), "applied": applied, "reassigned": reassigned}


async def sync_catalog(
    kind: str,
    userid: str,
    password: str,
    browser_factory,
    sessionmaker: async_sessionmaker,
) -> dict:
    """kind('budget_unit'|'project'|'partner'|'org_unit') 카탈로그 헤드리스 동기화.

    반환 {count, syncedAt}. org_unit 은 org_units 반영·사용자 재배치 요약(applied·reassigned)도 함께.
    """
    # 조직도(org_unit)는 랜딩 우상단에 있어 카드 진입 체인이 불필요 — 로그인만 하고 스크레이프.
    if kind == "org_unit":
        org = await _sync_org(userid, password, browser_factory, sessionmaker)
        return {
            "count": org["count"],
            "syncedAt": datetime.now(timezone.utc).isoformat(),
            "applied": org.get("applied"),
            "reassigned": org.get("reassigned"),
        }

    browser = await browser_factory()
    try:
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        await _run_entry_chain(page, userid, password)

        if kind == "budget_unit":
            count = await _sync_budget_units(page, sessionmaker)
        elif kind == "project":
            count = await _sync_projects(page, sessionmaker)
        elif kind == "partner":
            count = await _sync_partners(page, sessionmaker)
        else:
            raise ValueError(f"알 수 없는 kind: {kind}")
        return {"count": count, "syncedAt": datetime.now(timezone.utc).isoformat()}
    finally:
        await browser.close()
