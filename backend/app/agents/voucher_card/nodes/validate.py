"""params 검증 노드(카드) — 브라우저 앞단(login 전).

공유 검증(max_rows)에 회계일 기간(period_from~period_to)을 더한다. 기본 max_rows=None(전체)·
기간 미지정(=화면 기본 당월). 구 accounting_ym 은 params 모델이 그 월의 기간으로 흡수한다.
실제 상신·참조문서 확인은 하지 않는다(가상) — 절대 안전은 loop_approvals + reference_doc
훅(게이트)에서 보장.
"""

from __future__ import annotations

from app.live.events import emit_log, emit_step

from ..params import parse_voucher_card_params


def make_validate_params_node():
    """실행 전 폼 params 검증 → {max_rows(None=전체), period_from/period_to(None=당월)}."""

    async def validate_params(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        await emit_step(events, "validate_params", "running")
        try:
            p = parse_voucher_card_params(state.get("params") or {})
        except ValueError as exc:  # 한국어 메시지 — 그대로 error 프레임으로.
            await emit_step(events, "validate_params", "failed")
            return {"error": str(exc)}

        scope = "전체(조회된 전 건)" if p.max_rows is None else f"최대 {p.max_rows}건"
        await emit_log(
            events,
            f"실행 파라미터 확인 — {scope} 순회 · 회계일 {p.period_label}"
            "(실제 상신·참조문서 확인 없음).",
            "ok",
        )
        await emit_step(events, "validate_params", "done")
        return {
            "max_rows": p.max_rows,
            "period_from": p.period_from,
            "period_to": p.period_to,
        }

    return validate_params
