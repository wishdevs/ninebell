"""증빙유형 적용 노드 — 코드 선택·적용 + "전자발행된 증빙…" 다이얼로그 응답.

공유 make_select_evdn_node(common.nodes) 와 달리 세금계산서는 적용 직후 다이얼로그
"전자발행된 증빙으로 입력하시겠습니까?" 처리가 추가로 필요하다(PROCESS.md D5/D6): 발행 전 =
"아니요"(계산서 조회 스킵) / 발행 후 = "예". 03 처럼 다이얼로그 없이 바로 진행하는 코드도 있다.

**적용이 곧 계산서 리스트 모달을 연다**(2026-08-20 사용자 교정) — 발행 후는 이 노드가 모달
출현까지 확인한다. 화면 전체의 조회(F2)는 이 플로우에서 누르지 않는다.

적용 판정은 재독한 증빙 셀(EVDN_TP_NM)이 팝업에서 고른 항목명을 담고 있는지로 한다 —
엉뚱한 증빙으로 결의서가 저장되는 것을 막는 게이트라 불일치는 한국어 error 로 단락한다.
"""

from __future__ import annotations

import time

from app.live.events import emit_log, emit_step
from nbkit.patterns import emit_shot

from .. import steps


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def make_select_evdn_node():
    """plan.evidence_code 를 적용하고 다이얼로그를 발행/분할 여부에 맞게 응답."""

    async def select_evdn(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        plan = state.get("plan") or {}
        await emit_step(events, "select_evdn", "running")
        t0 = time.monotonic()
        code = plan.get("evidence_code")
        answer = steps.evdn_dialog_answer(plan.get("issue"))
        r = await steps.select_evidence(page, code, answer)
        if not r.get("ok"):
            await emit_step(events, "select_evdn", "failed")
            return {"error": r.get("reason") or f"증빙유형 {code} 적용 실패"}
        cell = str(r.get("cell") or "")
        picked = str(r.get("picked_name") or "")
        if not picked or picked not in cell:
            await emit_step(events, "select_evdn", "failed")
            msg = (
                f"증빙유형 {code}({plan.get('evidence_label')}) 적용이 상세 증빙 셀에 "
                f"반영되지 않았습니다(셀 '{cell or '비어 있음'}') — 다른 증빙으로 저장되는 것을 "
                "막기 위해 중단합니다."
            )
            await emit_log(events, msg, "error")
            return {"error": msg}
        # 발행 후는 이 시점에 계산서 리스트 모달이 열려야 정상이다(D5 재교정 2026-08-20 —
        # 모달을 여는 것은 증빙 적용이지 조회(F2)가 아니다). 이후 스텝이 그 모달 안에서만
        # 동작하므로 여기서 확인하고, 안 열렸으면 엉뚱한 화면 조작 전에 단락한다.
        if plan.get("issue") == "post":
            popup = await steps.wait_invoice_popup_ready(page, limit=0)
            if not popup.get("ok") or steps.best_invoice_grid(popup) is None:
                await emit_step(events, "select_evdn", "failed")
                msg = (
                    "증빙 적용 후 계산서 모달이 열리지 않았습니다"
                    f"({steps._popup_diag(popup)}) — 발행 후 경로는 이 모달에서 조회합니다."
                )
                await emit_log(events, msg, "error")
                return {"error": msg}
        dialog = (
            f" — 다이얼로그 '{r['answered']}' 응답" if r.get("answered") else " — 다이얼로그 없음"
        )
        await emit_log(
            events,
            f"증빙유형 {code}({plan.get('evidence_label')}) 적용{dialog}. 저장(F7)은 마지막에 1회.",
            "ok",
        )
        await emit_shot(events.put, page)
        await emit_step(events, "select_evdn", "done", _ms(t0))
        return {}

    return select_evdn
