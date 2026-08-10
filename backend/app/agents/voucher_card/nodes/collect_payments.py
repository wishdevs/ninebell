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

from app.agents.voucher_receivable import steps as shared_steps
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

        # 결의서번호(ABDOCU_NO) 보유 행이 0건이면 결재 대상 자체가 없다 — 결의서조회승인
        # 다중탭을 열 필요 없이 즉시 종료 경로로 보낸다(사용자 확정 2026-07-30: 불필요한
        # 탭 이동·수집 제거). 판정 실패(ok:False)는 기존 경로(수집 진행)로 폴백.
        ab = await shared_steps.count_rows_with_abdocu(page)
        if ab.get("ok") and int(ab.get("withAb", 0)) == 0:
            await emit_log(
                events,
                f"조회 {ab.get('n', 0)}건 모두 결의서번호가 없어(직접 전표) 결재 대상이 "
                "없습니다 — 결의서조회승인 수집을 생략하고 종료합니다.",
                "info",
            )
            await emit_step(events, "collect_payments", "done", _ms(t0))
            return {"payment_map": {}, "payment_map_count": 0}
        if not ab.get("ok"):
            await emit_log(
                events,
                f"결의서번호 사전 판정 실패({ab.get('reason')}) — 기존대로 수집을 진행합니다.",
                "warn",
            )

        await emit_log(events, "결의서조회승인 탭을 열어 결재번호를 수집합니다…", "action")
        # 화면 도착 확인(하드) — 탭이 안 열렸는데 전표조회승인 화면을 결의서 화면으로 착각하고
        # 조작하면 조회조건이 엉뚱한 폼에 들어간다.
        opened = await steps.open_collect_tab(page)
        if not opened.get("ok"):
            await emit_step(events, "collect_payments", "failed")
            return {"error": opened.get("reason") or "결의서조회승인 탭을 열지 못했습니다."}

        # 조회폼 세팅 — 각 스텝이 '세팅 → 반영 확인'까지 끝낸 뒤 결과를 돌려준다.
        # 결의부서/결의자/회계일은 결과 범위만 넓히는 보조 조건이라 실패해도 진행(warn)하지만,
        # **결의구분=카드는 수집 대상 자체를 정의**하므로 확인 실패 시 조회하지 않고 중단한다
        # (틀린 결의구분으로 수집된 맵은 loop_approvals 가 전건을 '맵에 없음'으로 건너뛴다).
        # ⚠ 결의부서는 '보조 조건'이 아니라 **수집 대상을 정의**한다(2026-07-27 라이브 규명):
        #   전체선택이 안 되면 로그인 부서(예: 회계팀)로 좁혀져, 전표조회승인 대상 행들의
        #   결의서번호와 하나도 겹치지 않는 맵이 만들어지고(실측: 맵 4건·커버 0건) 전 행이
        #   '맵에 없음'으로 건너뛰어진다 = 아무것도 처리하지 못한다. 그래서 하드 실패다.
        if not await steps.set_collect_dept_all(page):
            await emit_step(events, "collect_payments", "failed")
            return {
                "error": "결의부서 전체선택을 확인하지 못했습니다 — 로그인 부서로 좁혀진 채 "
                "수집하면 결재번호 맵이 대상과 어긋나므로 중단합니다.",
            }
        if not await steps.clear_collect_writer(page):
            await emit_log(events, "결의자 비움 미확인(로그인 계정으로 좁혀질 수 있음).", "warn")
        if not await steps.set_collect_period(page, state.get("period_from"), state.get("period_to")):
            await emit_log(events, "회계일 기간 미확인(화면 기본값=당월으로 진행).", "warn")
        if not await steps.set_collect_gubun_card(page):
            await emit_step(events, "collect_payments", "failed")
            return {
                "error": "결의구분=카드 설정을 확인하지 못했습니다 — 잘못된 결의구분으로 "
                "결재번호를 수집하지 않도록 중단합니다.",
            }

        if not await steps.run_collect_query(page):
            await emit_step(events, "collect_payments", "failed")
            return {"error": "결의서조회승인 조회 결과를 확인하지 못했습니다(그리드 미응답)."}
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
