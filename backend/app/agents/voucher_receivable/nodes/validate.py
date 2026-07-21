"""params 검증 노드 — 브라우저 앞단(login 전).

실행 전 폼 params 를 검증해 처리 행 수(max_rows)를 확정한다. 기본 None=전체(사용자 결정
2026-07-21). 실제 상신은 하지 않는다(가상 상신) — 절대 안전은 loop_approvals 에서 보장.
"""

from __future__ import annotations

from app.live.events import emit_log, emit_step

from ..params import parse_voucher_params


def make_validate_params_node():
    """실행 전 폼 params 검증 → max_rows(None=전체, 브라우저 불필요)."""

    async def validate_params(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        await emit_step(events, "validate_params", "running")
        try:
            p = parse_voucher_params(state.get("params") or {})
        except ValueError as exc:  # 한국어 메시지 — 그대로 error 프레임으로.
            await emit_step(events, "validate_params", "failed")
            return {"error": str(exc)}

        scope = "전체(조회된 전 건)" if p.max_rows is None else f"최대 {p.max_rows}건"
        await emit_log(events, f"실행 파라미터 확인 — {scope} 순회(실제 상신 없음).", "ok")
        await emit_step(events, "validate_params", "done")
        return {"max_rows": p.max_rows}

    return validate_params
