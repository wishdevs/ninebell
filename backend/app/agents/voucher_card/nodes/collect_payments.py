"""collect_payments 노드(카드 고유) — Phase B: 결의서조회승인에서 결재번호 맵 수집.

전표조회승인(Phase A) 조회 뒤, run_query 와 loop_approvals **사이**에 삽입된다:
  결의서조회승인(GLDDOC00400) **다중 메뉴 탭** 열기 → 결의부서 전체·결의자 비움·회계일·
  결의구분=카드 → 조회 → 결과 마스터에서 **ABDOCU_NO→GWDOCU_NO(결재번호) 맵** 수집 →
  캐시된 전표조회승인 탭으로 복귀. 맵은 state['payment_map'] 로 넘겨 loop_approvals 의
  참조문서 훅(reference_doc)이 행별 GWDOCU_NO 를 조회하는 데 쓴다.

⚠ 조회(F2)만 실행 — 결제·상신·저장·삭제 없음. 맵 수집 실패는 error 로 단락하지 않고 **빈 맵**
   으로 진행한다(참조문서 훅이 0건을 우아하게 로그 — 사용자 지시: "나온다고 가정하고 진행,
   추후 손봄"). 단, 탭 복귀 실패는 loop_approvals 가 엉뚱한 탭을 조작할 위험이라 error 로 단락.
"""

from __future__ import annotations

import time

from app.live.events import emit_log, emit_step
from nbkit.patterns import emit_shot

from .. import steps


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def make_collect_payments_node():
    """결의서조회승인 다중탭에서 결의구분=카드 일괄 조회 → ABDOCU_NO→GWDOCU_NO 맵 수집."""

    async def collect_payments(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, "collect_payments", "running")
        t0 = time.monotonic()

        # 대상 전표가 없으면(Phase A 0건) 결의서조회승인을 열 필요 없이 빈 맵으로 통과.
        if int(state.get("master_rowcount", 0)) <= 0:
            await emit_log(events, "대상 전표 0건 — 결재번호 수집을 건너뜁니다.", "info")
            await emit_step(events, "collect_payments", "done", _ms(t0))
            return {"payment_map": {}, "payment_map_count": 0}

        await emit_log(events, "결의서조회승인 탭을 열어 결재번호를 수집합니다…", "action")
        await steps.open_collect_tab(page)

        # 조회폼 세팅(전부 best-effort — 실패해도 폼 기본값으로 조회 진행).
        if not await steps.set_collect_dept_all(page):
            await emit_log(events, "결의부서 전체선택 실패(폼 기본값으로 진행).", "warn")
        await steps.clear_collect_writer(page)
        await steps.set_collect_period(page, state.get("accounting_ym"))
        if not await steps.set_collect_gubun_card(page):
            await emit_log(events, "결의구분=카드 설정 실패(폼 기본값으로 진행).", "warn")

        await steps.run_collect_query(page)
        res = await steps.read_payment_map(page)
        payment_map: dict[str, str] = res.get("map") or {}
        if not res.get("ok"):
            await emit_log(
                events,
                f"결재번호 수집 그리드를 읽지 못했습니다({res.get('reason')}) — 빈 맵으로 진행.",
                "warn",
            )
        await emit_log(
            events,
            f"결재번호 수집 완료 — 결의서 {res.get('n', 0)}건 중 매핑 {len(payment_map)}건"
            "(ABDOCU_NO→GWDOCU_NO).",
            "ok",
        )
        await emit_shot(events.put, page)

        # 캐시된 전표조회승인 탭으로 복귀 — 실패하면 loop 가 엉뚱한 탭을 조작할 위험(하드 실패).
        if not await steps.switch_back_to_voucher_tab(page):
            await emit_step(events, "collect_payments", "failed")
            return {
                "error": "전표조회승인 탭 복귀 실패 — 결재 순회 전에 중단합니다.",
                "payment_map": payment_map,
                "payment_map_count": len(payment_map),
            }

        await emit_step(events, "collect_payments", "done", _ms(t0))
        return {"payment_map": payment_map, "payment_map_count": len(payment_map)}

    return collect_payments
