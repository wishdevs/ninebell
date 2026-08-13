"""read_bom — 이동요청 해제 → 조회(F2) → 트리그리드 전량 읽기 → plannerBom 조립.

'구매요청만' 뷰(이동요청 해제 = MV_FG='N' 리프 + 구조행, CX85-137 실측 354행/리프 337 스케일)
로 좁힌 뒤 getLevel/getValue 루프 리더(getJsonRows 는 트리그리드에서 null)로 전량 읽는다.
레벨 매핑·의사거래처 분류는 planner.assemble_planner_bom(순수 함수)이 담당.
"""

from __future__ import annotations

import logging
import time

from app.agents.purchase_order import planner, steps
from app.live.events import emit_log, emit_step
from nbkit.patterns import emit_shot

logger = logging.getLogger(__name__)

STEP = "read_bom"


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


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
        planner_bom = planner.assemble_planner_bom(read.get("rows") or [], project)
        summary = planner.summarize_bom(planner_bom, read.get("count") or 0)
        if summary["parts"] == 0:
            await emit_step(events, STEP, "failed")
            return {
                "error": (
                    f"BOM {summary['gridRows']}행을 읽었지만 부품(리프) 행을 조립하지 못했습니다 — "
                    "레벨 매핑을 확인해 주세요."
                )
            }

        await emit_log(
            events,
            f"BOM 읽기 완료 — 그리드 {summary['gridRows']}행 → 장비 {summary['machines']} · "
            f"모듈(SET) {summary['modules']} · 부품 {summary['parts']}"
            f"(구매대상 {summary['purchasableParts']}).",
            "ok",
        )
        await emit_shot(events.put, page)
        await emit_step(events, STEP, "done", _ms(t0))
        # 프로젝트 wbs 는 그리드(WBS_NM)에서 회수될 수 있어 조립 결과의 project 로 갱신한다.
        return {
            "planner_bom": planner_bom,
            "bom_summary": summary,
            "project": planner_bom["project"],
        }

    return read_bom
