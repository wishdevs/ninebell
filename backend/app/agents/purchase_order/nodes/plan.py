"""plan — 계획서 HITL(신규 kind 'planner') — plannerBom 프레임 방출 → {"plan": ...} 대기.

프레임(공유 계약): {"hitl": {"id","kind":"planner","title":"발주 계획서 작성","prompt","plannerBom"}}.
제출 payload 는 프론트 buildPlanPayload 반환 shape 그대로(runs.py PlanIn 이 경계 검증):
  {"plan": {"project": {"code","name"}, "wbs", "units": [{"seq","purchaseReason","dueDate",
    "modules": [...], "vendorGroups": [...]}]}}

서버측 경량 검증(planner.validate_plan): units≥1 · 각 unit purchaseReason·dueDate ·
미지정 의사 거래처 없음. 위반 시 프레임 재방출(notice 포함 — 재개입 공지 와이어 계약,
LiveGridCard 선례) 후 재대기.

⏱ timeout_s=1800 — 계획 작성은 오래 걸린다(config 기본 600 오버라이드). 대기 중 런 활동
예산은 자동 정지(_BudgetPausedQueue).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from app.agents.purchase_order import planner
from app.live.events import emit_hitl, emit_log, emit_step
from app.live.hitl import close_hitl_channel, open_hitl_channel
from app.services import purchase_order_plans

logger = logging.getLogger(__name__)

STEP = "plan"
TITLE = "발주 계획서 작성"
PROMPT = (
    "모듈(SET)을 발주단위로 묶고, 발주단위별 구매사유·납기예정일과 거래처 그룹별 실거래처·"
    "납기·비고를 확정한 뒤 계획을 제출하세요. 이 실행은 계획 확정까지만 진행하며 "
    "ERP 저장은 하지 않습니다."
)
PLAN_TIMEOUT_S = 1800  # 계획 작성 전용 상한(30분). 2026-08-14 부터 config.hitl_timeout_s
#                      기본값도 1800 이라 값은 같지만, 전역을 낮춰도 이 개입은 지키도록 명시 유지.


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def make_plan_node():
    async def plan(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        planner_bom = state.get("planner_bom")
        if not planner_bom:
            return {"error": "계획서에 실을 BOM 이 없습니다(read_bom 미완료)."}
        await emit_step(events, STEP, "running")
        t0 = time.monotonic()

        decision_id = uuid.uuid4().hex
        q = open_hitl_channel(decision_id, owner=state.get("owner"), run_id=state.get("run_id"))

        async def _emit_frame(reason: str | None = None) -> None:
            # 프론트는 run.hitl 을 통째로 교체 — 재방출마다 plannerBom 전체를 싣는다
            # (세션 버퍼 상주 비용 감수 — HITL 통합 설계 확정). 검증 위반 재방출엔 notice 로
            # 사유를 싣는다 — 프론트 와이어 계약 필드(LiveHitl.notice, LiveGridCard 선례).
            # reason 같은 비계약 키는 카드가 렌더하지 않아 사용자에게 보이지 않는다.
            extra: dict = {"plannerBom": planner_bom}
            if reason:
                extra["notice"] = reason
            await emit_hitl(
                events,
                decision_id=decision_id,
                kind="planner",
                title=TITLE,
                prompt=PROMPT,
                **extra,
            )

        await _emit_frame()
        try:
            while True:
                try:
                    resp = await asyncio.wait_for(q.get(), timeout=PLAN_TIMEOUT_S)
                except (TimeoutError, asyncio.TimeoutError):
                    await emit_step(events, STEP, "failed")
                    return {
                        "error": f"계획서 제출 대기 시간 초과({PLAN_TIMEOUT_S // 60}분) — "
                        "계획이 확정되지 않았습니다."
                    }

                submitted = resp.get("plan") if isinstance(resp, dict) else None
                if submitted is None:
                    logger.debug("purchase-order plan: 무시된 메시지 %r", resp)
                    continue

                ok, reason = planner.validate_plan(submitted)
                if not ok:
                    await emit_log(events, f"계획 검증 실패 — {reason}", "warn")
                    await _emit_frame(reason)
                    continue

                units = submitted.get("units") or []
                await emit_log(
                    events, f"계획 확정 — 발주단위 {len(units)}개 수령.", "ok"
                )
                await emit_step(events, STEP, "done", _ms(t0))
                # 확정 계획서 보관 — 부가기능이라 실패해도 런은 계속.
                try:
                    await purchase_order_plans.record_plan(
                        state.get("owner"),
                        run_id=state.get("run_id"),
                        agent_id="purchase-order",
                        plan=submitted,
                        project=state.get("project"),
                        bom_summary=state.get("bom_summary"),
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("purchase-order plan: 계획서 보관 실패")
                # 상태 키는 confirmed_plan — 노드명 'plan' 과 같은 키는 LangGraph 가 거부한다.
                return {"confirmed_plan": submitted}
        finally:
            close_hitl_channel(decision_id)

    return plan
