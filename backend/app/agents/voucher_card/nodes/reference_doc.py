"""reference_doc 훅(카드 고유) — Phase C: 결제창(EAP) 안 참조문서 선택.

loop_approvals(공유)가 결제창을 열고 렌더+D7 을 통과한 뒤, **가상 상신 로그 전에** 이 훅을
`await on_popup(child, gwdocu_no, events)` 로 호출한다. 훅은 참조문서 dialog 에서:
  필터 확장 → 문서번호=GWDOCU_NO 입력 → 조회 → (매치 시) 선택 → 아래(↓) 버튼(선택목록 이동)
까지 한다.

⚠⚠ 절대 안전(엄수) ⚠⚠
  - **실제 상신 절대 클릭 금지** — 이 훅은 결제창 상신 버튼을 건드리지 않는다(로그만).
  - **참조문서 '확인'도 게이트**(allow_confirm=False 기본 — 미클릭). 기본 경로는 선택+아래버튼
    까지만 하고 확인·상신은 "가상" 로그만 남긴다(비영속 — 이후 결제창 close 로 정리).
  - **참조문서 검색 0건(현재 테스트 상태 — 시스템 승인 이슈)이면 우아하게 로그**하고 진행
    (크래시 금지). 사용자 지시(2026-07-21): "나온다고 가정하고 진행, 추후 손봄."
"""

from __future__ import annotations

from app.live.events import emit_log

from .. import steps


def make_reference_doc_hook(*, allow_confirm: bool = False):
    """loop_approvals 에 주입할 on_popup(child, gwdocu_no, events) 훅을 만든다.

    allow_confirm(기본 False): 참조문서 '확인' 클릭 게이트. 기본은 절대 미클릭(가상 로그만).
    True 로 승격하는 것은 시스템 승인 이슈 해소 후 비영속 검증을 마친 뒤에만(코드 게이트).
    """

    async def on_popup(child, gwdocu_no, events) -> None:
        # 결재번호(GWDOCU_NO)가 없으면(payment_map 누락 — Phase A 행에 ABDOCU_NO 없거나 미매핑)
        # 검색할 값이 없다 — 우아하게 로그하고 넘어간다.
        if not gwdocu_no:
            await emit_log(
                events, "참조문서 미검색 — 결재번호 미상(payment_map 누락). 가상 상신으로 진행.", "warn"
            )
            return

        if not await steps.open_refdoc_dialog(child):
            await emit_log(events, "참조문서 선택 버튼을 찾지 못했습니다 — 가상 상신으로 진행.", "warn")
            return

        await steps.expand_refdoc_filter(child)
        if not await steps.fill_refdoc_docno(child, gwdocu_no):
            await emit_log(
                events, f"참조문서 문서번호({gwdocu_no}) 입력 확인 실패 — 조회는 시도합니다.", "warn"
            )
        await steps.run_refdoc_search(child)
        found = await steps.poll_refdoc_matches(child)
        matches = found.get("docNoMatches") or []

        if not matches:
            # 현재 테스트 계정 상태(시스템 승인 이슈)로 0건 — 우아하게 로그 후 진행(크래시 금지).
            await emit_log(
                events,
                f"참조문서 미검색({gwdocu_no}) — 시스템 승인 대기(추후 손봄). 가상 상신으로 진행.",
                "warn",
            )
            await steps.close_refdoc_dialog(child)
            return

        # 매치 존재 — 선택 → 아래(↓) 버튼으로 '선택된 문서 목록' 이동(비영속).
        selected = await steps.select_refdoc_row(child, gwdocu_no)
        if selected:
            await steps.move_refdoc_down(child)
            await emit_log(events, f"참조문서 선택·아래버튼 완료({gwdocu_no}).", "ok")
        else:
            await emit_log(
                events, f"참조문서 목록에서 {gwdocu_no} 행을 선택하지 못했습니다 — 가상 상신으로 진행.", "warn"
            )

        if allow_confirm:
            # ⚠ 게이트 개방(비영속 검증 완료 후에만) — 실제 확인 클릭.
            await steps.click_refdoc_confirm(child)
            await emit_log(events, "참조문서 확인 클릭(allow_confirm=True).", "action")
        else:
            # 기본 — 확인·상신은 로그만(비영속). dialog 는 취소(X)로 정리.
            await emit_log(events, "가상: 참조문서 확인·상신 (미클릭 — 비영속).", "info")
            await steps.close_refdoc_dialog(child)

    return on_popup
