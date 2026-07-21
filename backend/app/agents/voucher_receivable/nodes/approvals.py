"""결재 순회 노드(loop_approvals) — 대상 전표를 한 건씩 결제창까지 열고 '가상 상신' 후 닫는다.

한 행씩: 키(DOCU_NO) 읽기 → checkRow → [D7: 체크행수=1 검증] → 결재 버튼 → 결제창(별도 Page)
→ 렌더 대기 → [D7: 결제창 전표번호=대상 DOCU_NO 대조] → **가상 상신 로그** → 창 닫기.
처리 건수는 기본 **전체**(max_rows=None → rowcount 전 건, 사용자 결정 2026-07-21); max_rows 를
명시하면 그 수만큼. 매 건 진행 상황(`[i/N]`·누적 실행 건수)을 로그로 노출한다.

⚠⚠ 절대 안전 ⚠⚠
  - 결제창(EAP)에서 **상신·보관 버튼을 절대 클릭하지 않는다**. 이 노드가 결제창에 하는 일은
    (1) 렌더 완료 판정을 위한 상단 버튼 텍스트 **읽기**, (2) 전표번호 **읽기**(D7 대조),
    (3) `close_child()` 로 **닫기** 뿐이다.
  - 실제 상신은 사용자가 최종 단계에서 직접 일괄 처리한다(handoff_note).

⚠ D7(배치 순회 정합성, 2026-07-21 배치 라이브 스모크로 도입): 행/팝업 어긋남(결제창이 대상
  행과 다른 문서를 열었을 가능성)이 배치 순회의 유일한 미검증 리스크였다 — 두 가지 읽기전용
  검증을 안전 크리티컬 하드 실패로 추가했다.
  1. 결제 열기 **직전** 체크된 행이 정확히 1개인지(`checked_row_indexes`) — 확인됐는데
     1개가 아니면 결제창을 열지 않고 즉시 중단.
  2. 결제창 렌더 후 표시된 전표번호(`read_child_docu_no`)가 대상 행 DOCU_NO 와 **확정적으로**
     (매치 정확히 1개) 다르면 즉시 중단. 매치 0개/2개+(모호)는 하드 실패 근거로 쓰지 않고
     경고만 남긴다 — 셀렉터/패턴 불확실성으로 인한 오탐을 배치 중단으로 이어가지 않기 위함.
"""

from __future__ import annotations

import time

from app.live.events import emit_log, emit_step
from nbkit.patterns import emit_shot

from .. import steps


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def make_loop_approvals_node(on_popup=None):
    """조회된 전표를 max_rows 만큼 순회하며 결제창을 열고 '가상 상신' 로그만 남기고 닫는다.

    on_popup(child, gwdocu_no, events) (기본 None): 결제창(EAP) 안에서 **가상 상신 로그 전에**
    추가 조작이 필요한 에이전트(미지급금 법인카드=참조문서 선택)를 위한 optional 훅.
      - None(외상매출금/매입금): 기존과 100% 동일(훅 미호출 — read/close 만).
      - 콜러블(카드): 렌더+D7 통과 후, 이 행의 결의서번호(ABDOCU_NO)로 state['payment_map']에서
        GWDOCU_NO 를 구해 `await on_popup(child, gwdocu_no, events)` 를 호출한다. 훅은 참조문서
        검색·선택까지만 하고 **확인·상신은 절대 클릭하지 않는다**(훅 자체가 게이트·우아한 실패
        책임을 진다 — 여기서는 예외를 삼켜 배치가 참조문서 이슈로 중단되지 않게 한다).
    """

    async def loop_approvals(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, "loop_approvals", "running")
        t0 = time.monotonic()

        rowcount = int(state.get("master_rowcount", 0))
        # max_rows None(기본) = 전체 순회. 양수면 그 수만큼(부분/테스트).
        max_rows = state.get("max_rows")
        if rowcount <= 0:
            await emit_log(events, "처리 대상 전표가 없습니다(조회 0건) — 정상 완료.", "info")
            await emit_step(events, "loop_approvals", "done", _ms(t0))
            return {
                "processed": 0,
                "processed_docu_nos": [],
                "result": "처리 완료 — 대상 전표가 없어 결재를 진행하지 않았습니다.",
            }

        process_count = rowcount if max_rows is None else min(int(max_rows), rowcount)
        # 처리 범위를 명시적으로 노출(전체/부분·건수) — 조용한 상한 방지.
        scope = "전체" if max_rows is None or int(max_rows) >= rowcount else f"{process_count}/{rowcount}"
        await emit_log(events, f"대상 {rowcount}건 중 {scope} 순회 시작(각 건 결제창 열기→가상 상신→닫기).", "info")
        # 워크플로우 노드에 진행 카운트 노출(0/N 부터) — 각 건 완료 시 갱신.
        await emit_step(events, "loop_approvals", "running", progress={"done": 0, "total": process_count})
        processed_docu_nos: list[str] = []

        async def fail(idx: int, reason) -> dict:
            await emit_step(events, "loop_approvals", "failed")
            msg = f"{idx + 1}번째 전표 결재창 처리 실패: {reason}"
            await emit_log(events, msg, "error")
            return {"error": msg, "processed": len(processed_docu_nos), "processed_docu_nos": processed_docu_nos}

        for idx in range(process_count):
            key = await steps.read_row_key(page, idx)
            key_label = key or "(번호미상)"

            # 진행 상황 노출 — 몇 건 중 몇 번째를 여는지(사용자 가시성).
            await emit_log(
                events,
                f"[{idx + 1}/{process_count}] 전표 {key_label} 결제창 확인 중… "
                f"(완료 {len(processed_docu_nos)}/{process_count})",
                "action",
            )

            # 배치 순회에서 직전 대상 행의 체크가 남아 결재가 여러 문서를 잡는 것을 막는다 —
            # 대상 행 체크 전에 전체 해제해 정확히 한 행만 체크된 상태로 결재창을 연다.
            await steps.uncheck_all_rows(page)

            # 행 선택 — checkRow 필수(setCurrent 만으론 결재 대상 미인식, D4 실측).
            if not await steps.check_row(page, idx):
                return await fail(idx, "행 선택(checkRow) 실패")

            # D7: 결제 열기 직전 정확히 1행만 체크됐는지 확인(확인 가능한 경우만 — API 미확정
            # 이거나 읽기 실패면 ok=False 로 조용히 건너뛴다. 확인됐는데 1행이 아니면 하드 실패).
            chk = await steps.checked_row_indexes(page)
            if isinstance(chk, dict) and chk.get("ok"):
                chk_rows = chk.get("rows") or []
                if len(chk_rows) != 1:
                    return await fail(
                        idx, f"결제 열기 직전 체크된 행 수가 1이 아닙니다(D7 정합성): {chk_rows}"
                    )
                await emit_log(events, f"D7 체크행수 확인 ✅ — 전표 {key_label}: {chk_rows}", "info")
            else:
                await emit_log(
                    events, f"D7 체크행수 확인 불가(soft, 전표 {key_label}): {chk}", "warn"
                )

            # 결재 버튼 → 별도 팝업 Page(EAP) 캡처.
            child = await steps.open_approval(page)
            if child is None:
                return await fail(idx, "결재창(별도 팝업 Page)이 열리지 않았습니다.")

            mismatch: str | None = None
            try:
                # 렌더 완료 판정(상단 버튼 텍스트 표출까지 조건 폴링) — 읽기 전용.
                top = await steps.poll_child_ready(child)
                if not top:
                    await emit_log(
                        events,
                        f"전표 {key_label} 결제창 렌더를 상한 내 확인하지 못했습니다(그래도 상신하지 않고 닫습니다).",
                        "warn",
                    )

                # D7: 결제창이 실제로 이 행의 문서를 열었는지 대조(읽기전용). 매치가 정확히
                # 1개이고 대상 DOCU_NO 와 다를 때만 확정 불일치로 취급(모호는 경고만).
                child_docu = await steps.read_child_docu_no(child)
                if len(child_docu) == 1 and key and child_docu[0] != key:
                    mismatch = child_docu[0]
                    await emit_log(
                        events,
                        f"⚠ D7 정합성 오류: {idx + 1}번째 행 예상 전표 {key_label} 이지만 "
                        f"결제창은 {mismatch} 을 표시합니다.",
                        "error",
                    )
                elif len(child_docu) != 1:
                    await emit_log(
                        events,
                        f"D7 정합성 확인 불가(soft, 후보 {len(child_docu)}개) — 전표 {key_label}: {child_docu}",
                        "warn",
                    )
                else:
                    await emit_log(events, f"D7 정합성 확인 ✅ — 전표 {key_label} 결제창 일치.", "ok")

                if mismatch is None:
                    # 카드 고유(on_popup): 결제창 안 참조문서 선택 — 가상 상신 로그 **전에** 수행.
                    # 이 행의 결의서번호(ABDOCU_NO)로 payment_map 에서 GWDOCU_NO 를 구해 넘긴다.
                    # 훅은 확인·상신을 절대 클릭하지 않으며 0건/오류를 우아하게 로그한다 —
                    # 참조문서 이슈로 배치가 중단되지 않게 여기서 예외를 삼킨다(best-effort).
                    if on_popup is not None:
                        abdocu_no = await steps.read_row_abdocu_no(page, idx)
                        payment_map = state.get("payment_map") or {}
                        gwdocu_no = payment_map.get(abdocu_no) if abdocu_no else None
                        try:
                            await on_popup(child, gwdocu_no, events)
                        except Exception as exc:  # noqa: BLE001 — 참조문서 훅은 비크리티컬.
                            await emit_log(
                                events,
                                f"참조문서 처리 중 경고(무시하고 진행) — 전표 {key_label}: {exc}",
                                "warn",
                            )
                    # ⚠ 상신(~922,30)·보관(~860,30) 절대 클릭 금지 — 가상 상신 로그만 남긴다.
                    processed_docu_nos.append(key_label)
                    await emit_log(
                        events,
                        f"[{idx + 1}/{process_count}] 가상 상신 완료 — 전표 {key_label} "
                        f"(누적 {len(processed_docu_nos)}/{process_count}건 실행).",
                        "ok",
                    )
                    # 워크플로우 노드 진행 카운트 갱신(누적 완료/전체).
                    await emit_step(
                        events,
                        "loop_approvals",
                        "running",
                        progress={"done": len(processed_docu_nos), "total": process_count},
                    )
            finally:
                # 성공/실패 무관하게 결제창은 반드시 닫는다(상신/보관 미클릭 = 비영속).
                await steps.close_child(child)

            # 다음 반복(또는 이번이 마지막이어도 무해)의 결재 오픈이 견고하도록 부모 정착 —
            # 2026-07-21 실측: 정착 없이 곧바로 다음 결재를 누르면 새 Page 가 안 뜨는 사례 관찰.
            await steps.settle_parent_after_child_close(page, child)

            if mismatch is not None:
                # 안전 크리티컬 — 배치를 계속 진행하지 않는다(코디네이터 지시).
                return await fail(
                    idx, f"결제창 전표번호 불일치(예상 {key_label} / 실제 {mismatch}) — 배치 즉시 중단"
                )

            await emit_shot(events.put, page)

        summary = ", ".join(processed_docu_nos)
        await emit_log(
            events,
            f"결재창 확인 완료 — 대상 {process_count}건 중 {len(processed_docu_nos)}건 가상 상신"
            f"(실제 상신 없음). 전표: {summary}",
            "ok",
        )
        await emit_step(events, "loop_approvals", "done", _ms(t0))
        return {
            "processed": len(processed_docu_nos),
            "processed_docu_nos": processed_docu_nos,
            "result": (
                f"처리 완료 — {len(processed_docu_nos)}건 결제창 확인(가상 상신, 실제 상신 없음). "
                f"전표: {summary}. 실제 상신은 옴니솔에서 직접 진행하세요."
            ),
        }

    return loop_approvals
