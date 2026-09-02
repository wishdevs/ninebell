"""read_bom — 이동요청 해제 → 조회(F2) → 트리그리드 전량 읽기 → plannerBom 조립.

'구매요청만' 뷰(이동요청 해제 = MV_FG='N' 리프 + 상위 행, CX85-137 실측 354행 = 구조 17 + 리프 337)
로 좁힌 뒤 ds.getLevel/ds.getValue 루프 리더(getJsonRows 는 트리그리드에서 null, grid.getValue
는 한 행 앞섬 — js.TREEGRID_READ_JS 참조)로 전량 읽는다. 레벨 매핑·의사거래처 분류는
planner.assemble_planner_bom(순수 함수)이 담당.
"""

from __future__ import annotations

import logging
import time

from langgraph.graph import END

from app.agents.purchase_order import planner, steps
from app.live.events import emit_log, emit_step
from app.services import purchase_order_resume
from nbkit.patterns import emit_shot

logger = logging.getLogger(__name__)

STEP = "read_bom"


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def route_after_read_bom(state: dict) -> str:
    """read_bom 다음 노드 결정(순수) — graph 의 조건 분기와 스킵 스텝 마감이 같은 판정을 쓴다.

    우선순위: submit_prqs(상신부터 재실행) > order_prqs(발주만) > 자동 재개(잔여 PRQ → save_move,
    IRQ 기록으로 스킵) > no_modules(END) > plan(계획서 HITL).
    """
    po = (state.get("params") or {}).get("purchase_order") or {}
    if po.get("submit_prqs"):
        return "self_approve"
    if po.get("order_prqs"):
        return "place_orders"
    if (state.get("resume") or {}).get("prqs"):
        return "save_move"
    if state.get("no_modules"):
        return END
    return "plan"


#: 분기가 건너뛰는 스텝 — 프레임을 안 보내면 워크플로우 패널에서 영원히 '대기'로 남아
#: 개입 예고("곧 입력을 요청합니다")·타임라인 마커 이탈·N/11 미달이 생긴다(2026-09-02 ETRI-026
#: 재개 런 실측). 건너뛴 스텝은 done(ms 0)으로 마감한다.
_SKIPPED_STEPS_BY_ROUTE: dict[str, tuple[str, ...]] = {
    "save_move": ("plan",),
    "self_approve": ("plan", "save_move", "save_units"),
    "place_orders": ("plan", "save_move", "save_units", "self_approve"),
}


async def _close_skipped_steps(events, state: dict, out: dict) -> None:
    """read_bom 산출을 반영한 분기 기준으로 건너뛰는 스텝을 done 으로 마감한다."""
    route = route_after_read_bom({**state, **out})
    for step in _SKIPPED_STEPS_BY_ROUTE.get(route, ()):
        await emit_step(events, step, "done", 0)


def make_read_bom_node():
    async def read_bom(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, STEP, "running")
        t0 = time.monotonic()

        # 이동요청 해제 → 구매요청만(D4/D5 실측: 진입 시 둘 다 체크 = 합집합 뷰).
        r = await steps.set_checkbox(page, steps.CHECKBOX_MOVE, False)
        if not r.get("ok"):
            await emit_step(events, STEP, "failed")
            return {"error": r.get("reason") or "이동요청 체크박스를 해제하지 못했습니다."}

        # stale-grid 레이스 방지(2026-08-13 스모크 실측: pick_project 의 직전 무필터 410행이
        # 'rows>0' 을 즉시 충족해 필터 재조회 전에 읽힘): 조회 전 시그니처를 캡처해 두고,
        # F2 후 '필터 반영'(mvY=0 + 변화 또는 이미 깨끗)을 내용으로 독립 확인한다.
        prev_sig = await steps.read_bom_signature(page)
        await steps.click_lookup(page)
        rows_n = await steps.wait_bom_filtered(page, prev_sig)
        if rows_n <= 0:
            await emit_step(events, STEP, "failed")
            return {"error": "구매요청만 조회(F2) 후 필터 반영된 BOM 그리드를 확인하지 못했습니다."}

        read = await steps.read_bom_rows(page, planner.READ_FIELDS)
        if not read.get("ok"):
            await emit_step(events, STEP, "failed")
            return {
                "error": f"BOM 트리그리드를 읽지 못했습니다 — {read.get('reason') or read.get('err')}"
            }

        project = dict(state.get("project") or {})
        rows = read.get("rows") or []
        planner_bom = planner.assemble_planner_bom(rows, project)
        summary = planner.summarize_bom(planner_bom, read.get("count") or 0)
        # 그리드 SET 행수 대비 남은 모듈 — 차이 = 하위 부품이 없어 제외된(발주 완료) SET.
        set_rows = sum(1 for r in rows if r.get("level") == planner.LEVEL_MODULE)
        excluded = set_rows - summary["modules"]

        if summary["modules"] == 0:
            if set_rows == 0:
                await emit_step(events, STEP, "failed")
                return {
                    "error": (
                        f"BOM {summary['gridRows']}행을 읽었지만 SET(모듈) 행을 조립하지 "
                        "못했습니다 — 레벨 매핑을 확인해 주세요."
                    )
                }
            # SET 은 있는데 전부 하위 부품이 없다 = 구매요청 저장이 끝난 프로젝트. 실패가 아니라
            # '할 일 없음'이므로 계획서(HITL)를 띄우지 않고 끝낸다(사용자 확정 2026-08-14).
            # ⚠ 자동 재개(2026-08-31): 저장은 다 됐지만 상신/발주 전에 중단된 프로젝트도 여기로
            #   들어온다 — 이전 중단 런 잔여물이 있으면 END 대신 뒷단계로 이어간다(graph 분기).
            msg = (
                f"발주할 모듈이 없습니다 — SET {set_rows}건이 모두 하위 부품 없이 "
                "조회됐습니다(구매요청 저장 완료)."
            )
            resume = await purchase_order_resume.prior_artifacts(
                str(planner_bom["project"].get("code") or ""), exclude_run_id=state.get("run_id")
            )
            if resume.get("prqs"):
                await emit_log(
                    events,
                    msg + f" 이전 중단 런의 구매요청 {len(resume['prqs'])}건을 이어서 처리합니다"
                    "(이미 상신/발주된 건은 자동 스킵).",
                    "info",
                )
            else:
                await emit_log(events, msg, "warn")
            await emit_shot(events.put, page)
            await emit_step(events, STEP, "done", _ms(t0))
            out = {
                "planner_bom": planner_bom,
                "bom_summary": summary,
                "project": planner_bom["project"],
                "no_modules": True,
                "resume": resume,
                "result": msg,
            }
            await _close_skipped_steps(events, state, out)
            return out

        # 제외분은 조용히 버리지 않고 로그에 남긴다 — 그리드 행수와 모듈 수가 안 맞는 이유가 된다.
        excluded_txt = (
            f" 하위 부품 없는 SET {excluded}건은 발주 완료로 보고 제외했습니다." if excluded > 0 else ""
        )
        await emit_log(
            events,
            f"BOM 읽기 완료 — 그리드 {summary['gridRows']}행 → 장비 {summary['machines']} · "
            f"모듈(SET) {summary['modules']} · 부품 {summary['parts']}"
            f"(구매대상 {summary['purchasableParts']}).{excluded_txt}",
            "ok",
        )
        # 자동 재개(2026-09-01 사용자 확정): 이전 중단 런의 잔여 PRQ 가 있으면 BOM 에 모듈이
        # 남아 있어도(계획서 미포함 신규 항목) 계획서 HITL 을 띄우지 않는다 — 재개는 중단
        # 지점부터, 신규 항목은 재개 완주 후 새 계획서로 처리한다(graph 분기가 resume 우선).
        resume = await purchase_order_resume.prior_artifacts(
            str(planner_bom["project"].get("code") or ""), exclude_run_id=state.get("run_id")
        )
        if resume.get("prqs"):
            await emit_log(
                events,
                f"이전 중단 런의 구매요청 {len(resume['prqs'])}건이 남아 있어 계획서를 건너뛰고 "
                f"남은 상신·발주부터 이어갑니다. 계획서 미포함 모듈 {summary['modules']}건은 "
                "재개 완료 후 새로 실행해 계획서를 작성하세요.",
                "info",
            )
        await emit_shot(events.put, page)
        await emit_step(events, STEP, "done", _ms(t0))
        # 프로젝트 wbs 는 그리드(WBS_NM)에서 회수될 수 있어 조립 결과의 project 로 갱신한다.
        out = {
            "planner_bom": planner_bom,
            "bom_summary": summary,
            "project": planner_bom["project"],
            "resume": resume,
        }
        await _close_skipped_steps(events, state, out)
        return out

    return read_bom
