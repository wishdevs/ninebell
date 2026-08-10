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

        # 필터 패널을 '조회 버튼이 보이는 상태'로 만든다(토글이라 이미 펼쳐졌으면 누르지 않는다).
        # ⚠ 확인 실패해도 **여기서 중단하지 않는다**(2026-07-27 회귀 교훈): 종전 코드는 이 단계가
        #   best-effort 라 실패해도 문서번호를 넣고 조회를 시도했는데, 확인을 붙이며 조기 반환으로
        #   바꿨더니 **문서번호조차 입력되지 않는** 더 나쁜 상태가 됐다. 확인은 진단을 위한 것이지
        #   할 수 있는 일을 못 하게 만드는 게이트가 아니다 — 못 편 것 같아도 입력·조회는 시도하고,
        #   실제로 못 누른 경우는 아래 run_refdoc_search 반환값이 정확히 잡아준다.
        if not await steps.expand_refdoc_filter(child):
            await emit_log(
                events,
                f"참조문서 조회 조건 패널 확장을 확인하지 못했습니다({gwdocu_no}) — 입력·조회는 그대로 시도합니다.",
                "warn",
            )

        if not await steps.fill_refdoc_docno(child, gwdocu_no):
            await emit_log(
                events, f"참조문서 문서번호({gwdocu_no}) 입력 확인 실패 — 조회는 시도합니다.", "warn"
            )
        # 조회 **직전** 총 건수를 기준선으로 잡는다 — 이게 없으면 필터 반영 전 값을 결과로
        # 오독해 "대상 특정 불가"로 조기 종료한다(2026-07-27 회귀).
        before = await steps.read_refdoc_state(child)
        prev_total = before.get("total") if isinstance(before, dict) else None

        if not await steps.run_refdoc_search(child):
            await emit_log(
                events,
                f"참조문서 '조회' 버튼을 누르지 못했습니다({gwdocu_no}) — 검색 미실행. 가상 상신으로 진행.",
                "warn",
            )
            await steps.close_refdoc_dialog(child)
            return

        # 결과 판정 — 목록이 **RealGrid 캔버스**라 DOM 행 스캔이 불가능하다(2026-07-27 실측).
        # dialog 의 텍스트 앵커('총 N개' / '조회된 데이터가 없습니다.')로 확인한다.
        state = await steps.poll_refdoc_result(child, prev_total=prev_total)
        total = state.get("total")
        if state.get("noData") or total == 0:
            await emit_log(
                events,
                f"참조문서 검색 결과 0건({gwdocu_no}) — 조회는 정상 실행됨. "
                "결재번호로 참조 가능한 문서가 없습니다. 가상 상신으로 진행.",
                "warn",
            )
            await steps.close_refdoc_dialog(child)
            return
        if not state.get("settled"):
            await emit_log(
                events,
                f"참조문서 조회 결과를 확인하지 못했습니다({gwdocu_no}) — 목록 갱신 미확인. "
                "가상 상신으로 진행.",
                "warn",
            )
            await steps.close_refdoc_dialog(child)
            return
        if total is not None and total > 1:
            # 결재번호로 좁혔는데도 여럿이면 첫 행이 대상이라는 보장이 없다 — 붙이지 않는다.
            await emit_log(
                events,
                f"참조문서 검색 결과가 {total}건입니다({gwdocu_no}) — 대상을 특정할 수 없어 "
                "선택하지 않고 진행합니다.",
                "warn",
            )
            await steps.close_refdoc_dialog(child)
            return

        await emit_log(events, f"참조문서 검색 {total}건 확인({gwdocu_no}) — 선택 후 이동합니다.", "info")
        if not await steps.select_refdoc_first_row(child):
            await emit_log(events, "참조문서 목록 행을 선택하지 못했습니다 — 가상 상신으로 진행.", "warn")
            await steps.close_refdoc_dialog(child)
            return

        moved = await steps.move_refdoc_down(child, gwdocu_no)
        # 최종 성공 판정(사용자 확정 2026-07-27): **첨부 후 참조문서 1건 이상**.
        # move 내부 확인과 별개로, dialog 를 닫기 직전 상태를 한 번 더 독립 확인한다.
        final_ok = await steps.selected_list_has_doc(child, gwdocu_no)
        if moved.get("verified") and final_ok is False:
            await emit_log(
                events,
                f"참조문서 첨부 직후엔 담겼으나 최종 확인에서 목록에 없습니다({gwdocu_no}) — 실패로 처리합니다.",
                "warn",
            )
            moved = {**moved, "verified": False, "reason": "최종 확인에서 0건"}
        if moved.get("verified"):
            await emit_log(
                events,
                f"참조문서 첨부 완료 — 선택된 문서 목록 {moved.get('count')}건, "
                f"문서번호 {gwdocu_no} 포함 확인 ✅.",
                "ok",
            )
        else:
            await emit_log(
                events,
                f"참조문서 첨부 실패({gwdocu_no}) — {moved.get('reason')} 가상 상신으로 진행.",
                "warn",
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
