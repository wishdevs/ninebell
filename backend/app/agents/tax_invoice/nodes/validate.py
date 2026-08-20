"""params 검증 노드 — 브라우저 앞단(login 전).

실행 전 폼이 보낸 `state["params"]["tax_invoice"]` 를 정규화해 plan 으로 만든다. 증빙유형
코드는 여기서 확정(서버 도출 — evidence_for)돼 이후 노드가 재판단하지 않는다. 실패는
한국어 error 로 단락(이후 노드가 전부 건너뛰고 러너가 error 프레임으로 종료).
"""

from __future__ import annotations

from app.live.events import emit_log, emit_step

from ..params import parse_tax_invoice_params


def make_validate_params_node():
    """실행 전 폼 params 검증·정규화 → plan(dict)."""

    async def validate_params(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        await emit_step(events, "validate_params", "running")
        try:
            plan = parse_tax_invoice_params(state.get("params") or {})
        except ValueError as exc:  # 한국어 메시지 — 그대로 error 프레임으로.
            await emit_step(events, "validate_params", "failed")
            return {"error": str(exc)}

        bits = [f"증빙유형 {plan['evidence_code']}({plan['evidence_label']})"]
        if plan["supply_amount"] is not None:
            bits.append(f"공급가액 {plan['supply_amount']:,}원")
        if plan["partner_name"]:
            bits.append(f"거래처 {plan['partner_name']}")
        if plan["split"]:
            bits.append(f"비용분할 {len(plan['split_rows'])}행")
        if plan["issue"] == "post":
            bits.append(f"조회기간 {plan['period_from']}~{plan['period_to']}")
        await emit_log(events, "입력 검증 완료 — " + " · ".join(bits) + ".", "ok")
        await emit_step(events, "validate_params", "done")
        return {"plan": plan}

    return validate_params
