"""params 검증 노드 — 브라우저 앞단(login 전).

실행 전 폼이 보낸 `state["params"]["gyeongjo"]` 를 pydantic 으로 검증·정규화해 plan_rows(단건)로
만들고, 공급가액(근속<1년 50%)을 확정한다. 예산단위 조합매칭에 필요한 부서(department)·비용구분
(cost_type)이 있는지 확인한다. 실패는 한국어 error 로 단락(이후 노드가 전부 건너뛰고 러너가 error
프레임으로 종료).
"""

from __future__ import annotations

from app.live.events import emit_log, emit_step

from ..params import parse_gyeongjo_params


def make_validate_params_node():
    """실행 전 폼 params 검증·정규화 → plan_rows / acct_date_compact / department / cost_type."""

    async def validate_params(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        await emit_step(events, "validate_params", "running")
        params = state.get("params") or {}
        try:
            plan_rows, acct_compact = parse_gyeongjo_params(params)
        except ValueError as exc:  # 한국어 메시지 — 그대로 error 프레임으로.
            await emit_step(events, "validate_params", "failed")
            return {"error": str(exc)}

        department = str(params.get("department") or "").strip()
        cost_type = str(params.get("cost_type") or "").strip()
        if not department:
            await emit_step(events, "validate_params", "failed")
            return {
                "error": "사용자 부서 정보가 없습니다 — 예산단위(복리후생비-경조) 조합을 "
                "특정할 수 없습니다. 관리자에게 부서 지정을 요청하세요."
            }
        if not cost_type:
            await emit_step(events, "validate_params", "failed")
            return {
                "error": "비용구분(판관비/제조원가) 정보가 없습니다 — 소속 팀의 비용구분 설정을 "
                "확인하세요."
            }

        supply = int((plan_rows[0] or {}).get("amount") or 0)
        await emit_log(
            events,
            f"입력 검증 완료 — 회계일 {acct_compact} · 공급가액 {supply:,}원 · 부서 {department} · {cost_type}.",
            "ok",
        )
        await emit_step(events, "validate_params", "done")
        return {
            "plan_rows": plan_rows,
            "acct_date_compact": acct_compact,
            "department": department,
            "cost_type": cost_type,
        }

    return validate_params
