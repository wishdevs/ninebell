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
                    code=r["code"],
                    name=r["name"],
                    extra=None,
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
    return len(rows)


async def _sync_projects(page, sessionmaker: async_sessionmaker) -> int:
    rows, cap_hit = await steps.dump_projects_sweep(page, list(_PROJECT_PREFIXES))
    if cap_hit:
        logger.warning("프로젝트 스윕 캡(500) 도달 접두 — 누락 가능: %s", ", ".join(cap_hit))
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
                    code=r["code"],
                    name=r["name"],
                    extra={"useYn": r["useYn"]},
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


async def sync_catalog(
    kind: str,
    userid: str,
    password: str,
    browser_factory,
    sessionmaker: async_sessionmaker,
) -> dict:
    """kind('budget_unit'|'project') 코드 카탈로그를 헤드리스로 동기화. 반환 {count, syncedAt}."""
    browser = await browser_factory()
    try:
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        await _run_entry_chain(page, userid, password)

        if kind == "budget_unit":
            count = await _sync_budget_units(page, sessionmaker)
        elif kind == "project":
            count = await _sync_projects(page, sessionmaker)
        else:
            raise ValueError(f"알 수 없는 kind: {kind}")
        return {"count": count, "syncedAt": datetime.now(timezone.utc).isoformat()}
    finally:
        await browser.close()
