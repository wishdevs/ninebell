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

import asyncio
import time

from app.config import get_settings
from app.live.events import emit_log, emit_step
from nbkit.browser.popups import close_foreign_pages
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

        # ── 처리 대상 선별(순회 **전에** 확정) ────────────────────────────────────
        # 카드(on_popup): 결의서번호(ABDOCU_NO)가 결재번호 맵에 있는 행만 결제 대상이다. 결의서번호가
        # 없거나(직접 전표=전표입력/지급내역전표처리) 카드 결의서로 수집되지 않은 행은 참조문서
        # 대상이 아니라 **결제창을 열지 않는다**(사용자 확인 2026-07-21).
        # ⚠ 표시 방식 정정(사용자 리포트 2026-07-27): 종전에는 전체 행을 순회하며 대상이 아닌 행마다
        #   '건너뜀' 로그를 찍고 진행률 분모도 조회 건수(예: 19)로 잡았다 — 실제로 처리할 4건이
        #   묻혀 "무엇을 하고 있는지" 보이지 않았다. 이제 **먼저 선별**해 분모를 처리 대상 건수로
        #   잡고(4/4), 제외분은 요약 한 줄로만 남긴다.
        payment_map = state.get("payment_map") or {}
        targets: list[tuple[int, str | None, str | None]] = []  # (행 인덱스, DOCU_NO, GWDOCU_NO)
        skipped_no_ab: list[str] = []  # 결의서번호 자체가 없는 행(직접 전표)
        skipped_unmapped: list[str] = []  # 결의서번호는 있으나 결재번호 맵에 없는 행
        for idx in range(rowcount):
            if on_popup is None:
                # 매출/매입: 사전 전량 read 를 하지 않는다 — rowcount 가 큰 화면에서 전 행
                # getJsonRows 순회가 가상스크롤 partial fetch 를 유발해 이후 체크 상태를
                # 되돌릴 수 있다는 프로브 가설(2026-07-30, D7 [] 소량 재현 실패 후 구조적
                # 완화). key(DOCU_NO)는 순회 루프에서 해당 행 차례에 lazy 로 읽는다.
                targets.append((idx, None, None))
                continue
            key = await steps.read_row_key(page, idx)
            abdocu_no = await steps.read_row_abdocu_no(page, idx)
            # 공백 정규화 후 매칭 — 그리드 표기값에 앞뒤 공백이 섞이면 정확일치 lookup 이 조용히
            # 실패한다(맵 키도 read_payment_map 에서 strip 해 양쪽을 맞춘다).
            ab_key = str(abdocu_no).strip() if abdocu_no else ""
            gw = payment_map.get(ab_key) if ab_key else None
            if gw is None:
                (skipped_no_ab if not ab_key else skipped_unmapped).append(key or "(번호미상)")
                continue
            targets.append((idx, key, gw))

        # max_rows 는 **처리 대상** 기준으로 자른다(제외분이 상한을 잡아먹지 않게).
        if max_rows is not None:
            targets = targets[: max(0, int(max_rows))]
        process_count = len(targets)
        skipped = len(skipped_no_ab) + len(skipped_unmapped)

        if on_popup is not None:
            # 커버리지(결의서번호 보유 행 중 맵에 있는 비율)를 명시한다 — 0% 면 수집 조건이
            # 어긋난 것이지 '대상이 없는' 것이 아니다(2026-07-27: 결의부서가 좁혀져 맵 4건·
            # 커버 0건이던 사고를 로그만 보고 판별할 수 있게 한다).
            with_ab_n = process_count + len(skipped_unmapped)
            await emit_log(
                events,
                f"조회 {rowcount}건 중 결의서번호 보유 {with_ab_n}건 → 결재 대상 {process_count}건"
                f"(결재번호 맵 {len(payment_map)}건, 매칭 {process_count}/{with_ab_n}).",
                "info" if process_count else "warn",
            )
            if with_ab_n and not process_count:
                await emit_log(
                    events,
                    "⚠ 결의서번호가 있는 행이 있는데 결재번호 맵과 하나도 매칭되지 않았습니다 — "
                    "결의서조회승인 수집 조건(결의부서 전체·결의자 비움·회계일)이 대상과 어긋났을 "
                    "가능성이 큽니다.",
                    "warn",
                )
            if skipped:
                # 제외 사유는 두 종류를 구분해 **한 줄 요약**으로만(행별 나열은 화면을 덮는다).
                parts = []
                if skipped_no_ab:
                    parts.append(f"결의서번호 없음(직접 전표) {len(skipped_no_ab)}건")
                if skipped_unmapped:
                    sample = ", ".join(skipped_unmapped[:3])
                    more = "…" if len(skipped_unmapped) > 3 else ""
                    parts.append(
                        f"결재번호 맵에 없음 {len(skipped_unmapped)}건(전표 {sample}{more})"
                    )
                await emit_log(events, f"결재 대상 제외 {skipped}건 — {' · '.join(parts)}.", "info")
        else:
            scope = "전체" if max_rows is None or int(max_rows) >= rowcount else f"{process_count}/{rowcount}"
            await emit_log(
                events, f"대상 {rowcount}건 중 {scope} 순회 시작(각 건 결제창 열기→가상 상신→닫기).", "info"
            )

        processed_docu_nos: list[str] = []
        # 참조문서 결과 집계(on_popup 훅이 str 을 반환할 때만) — (전표, '첨부'|미첨부 사유).
        refdoc_results: list[tuple[str, str]] = []
        if process_count <= 0:
            await emit_log(events, "결재를 진행할 대상이 없습니다 — 정상 완료.", "info")
            await emit_step(events, "loop_approvals", "done", _ms(t0))
            return {
                "processed": 0,
                "processed_docu_nos": [],
                "result": (
                    f"처리 완료 — 조회 {rowcount}건 중 결재 대상이 없어 진행하지 않았습니다"
                    f"(제외 {skipped}건)."
                ),
            }

        # 워크플로우 노드에 진행 카운트 노출(0/N 부터) — 분모는 **처리 대상 건수**다.
        await emit_step(events, "loop_approvals", "running", progress={"done": 0, "total": process_count})

        async def fail(idx: int, reason) -> dict:
            await emit_step(events, "loop_approvals", "failed")
            msg = f"{idx + 1}번째 전표 결재창 처리 실패: {reason}"
            await emit_log(events, msg, "error")
            return {"error": msg, "processed": len(processed_docu_nos), "processed_docu_nos": processed_docu_nos}

        for seq, (idx, key, gwdocu_no) in enumerate(targets, start=1):
            if key is None and on_popup is None:
                key = await steps.read_row_key(page, idx)  # lazy — 위 사전 스캔 제거 참조.
            key_label = key or "(번호미상)"
            # 진행 상황 노출 — 처리 대상 기준 몇 번째인지(제외분은 분모에 넣지 않는다).
            await emit_log(
                events,
                f"[{seq}/{process_count}] 전표 {key_label} 결제창 확인 중… "
                f"(완료 {len(processed_docu_nos)}/{process_count})",
                "action",
            )

            # 배치 순회에서 직전 대상 행의 체크가 남아 결재가 여러 문서를 잡는 것을 막는다 —
            # 대상 행 체크 전에 전체 해제해 정확히 한 행만 체크된 상태로 결재창을 연다.
            # (해제 실패 신호는 1회 재시도 — 최종 심판은 아래 D7 체크행수 대조다.)
            if not await steps.uncheck_all_rows(page):
                await steps.uncheck_all_rows(page)

            # 행 선택 — checkRow 필수(setCurrent 만으론 결재 대상 미인식, D4 실측).
            if not await steps.check_row(page, idx):
                return await fail(idx, "행 선택(checkRow) 실패")

            # D7: 결제 열기 직전 정확히 1행만 체크됐는지 확인(확인 가능한 경우만 — API 미확정
            # 이거나 읽기 실패면 ok=False 로 조용히 건너뛴다. 확인됐는데 1행이 아니면 재체크
            # 1회 후에도 어긋날 때만 하드 실패 — 조회 직후 지연 재렌더가 체크를 되돌리는
            # 케이스 대비(프로브 가설 2026-07-30: 실사용 '[]' 사고, 소량 데이터 재현 실패).
            chk = await steps.checked_row_indexes(page)
            if isinstance(chk, dict) and chk.get("ok"):
                chk_rows = chk.get("rows") or []
                if len(chk_rows) != 1:
                    await emit_log(
                        events,
                        f"D7 체크행수 불일치({chk_rows}) — 재체크 후 재확인합니다(전표 {key_label}).",
                        "warn",
                    )
                    await asyncio.sleep(1.0)  # 지연 재렌더 정착 대기(실시간).
                    if not await steps.uncheck_all_rows(page):
                        await steps.uncheck_all_rows(page)
                    if not await steps.check_row(page, idx):
                        return await fail(idx, "행 선택(checkRow) 재시도 실패")
                    await asyncio.sleep(0.5)
                    chk = await steps.checked_row_indexes(page)
                    if isinstance(chk, dict) and chk.get("ok"):
                        chk_rows = chk.get("rows") or []
                    if len(chk_rows) != 1:
                        return await fail(
                            idx,
                            f"결제 열기 직전 체크된 행 수가 1이 아닙니다(D7 정합성, 재체크 후에도): {chk_rows}",
                        )
                await emit_log(events, f"D7 체크행수 확인 ✅ — 전표 {key_label}: {chk_rows}", "info")
            else:
                await emit_log(
                    events, f"D7 체크행수 확인 불가(soft, 전표 {key_label}): {chk}", "warn"
                )

            # 결재 버튼 → 별도 팝업 Page(EAP) 캡처.
            # 결제창을 열기 **직전** 남은 외부 창(공지·홈페이지)을 정리한다 — 화면을 덮은
            # 채 결재 버튼을 누르면 클릭이 가로채인다. ⚠ 이 시점엔 결제창이 아직 없으므로
            # 업무 창을 닫을 위험이 없다(결제창은 아래에서 연다).
            for url in await close_foreign_pages(page, get_settings().erp_base):
                await emit_log(events, f"결재 전 외부 창을 닫았습니다 — {url}", "info")

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
                        f"⚠ D7 정합성 오류: [{seq}/{process_count}] {idx + 1}번째 행 예상 전표 "
                        f"{key_label} 이지만 "
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
                        # gwdocu_no 는 이 행의 결의서번호로 위에서 이미 해소(없으면 이 행은 스킵됐다).
                        try:
                            outcome = await on_popup(child, gwdocu_no, events)
                        except Exception as exc:  # noqa: BLE001 — 참조문서 훅은 비크리티컬.
                            outcome = "오류"
                            await emit_log(
                                events,
                                f"참조문서 처리 중 경고(무시하고 진행) — 전표 {key_label}: {exc}",
                                "warn",
                            )
                        if isinstance(outcome, str):
                            refdoc_results.append((key_label, outcome))
                    # ⚠ 상신(~922,30)·보관(~860,30) 절대 클릭 금지 — 가상 상신 로그만 남긴다.
                    processed_docu_nos.append(key_label)
                    await emit_log(
                        events,
                        f"[{seq}/{process_count}] 가상 상신 완료 — 전표 {key_label} "
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
        skip_txt = f"(결재 대상 제외 {skipped}건)" if skipped else ""
        # 참조문서 집계(카드 전용 훅) — 누락이 요약에서 보이게 한다(2026-08-06 포렌식:
        # 중간 warn 한 줄뿐이라 요약만 보면 전 건 성공으로 읽히던 보고 갭).
        refdoc_txt = ""
        if refdoc_results:
            ok_n = sum(1 for _, o in refdoc_results if o == "첨부")
            misses = [(k, o) for k, o in refdoc_results if o != "첨부"]
            miss_txt = (
                f" · 미첨부 {len(misses)}건(" + ", ".join(f"{k}: {o}" for k, o in misses) + ")"
                if misses
                else ""
            )
            refdoc_txt = f" 참조문서 첨부 {ok_n}건{miss_txt}."
        await emit_log(
            events,
            f"결재창 확인 완료 — 결재 대상 {process_count}건 중 {len(processed_docu_nos)}건 가상 상신"
            f"(실제 상신 없음). 조회 {rowcount}건 {skip_txt}.{refdoc_txt} 전표: {summary}",
            "ok",
        )
        await emit_step(events, "loop_approvals", "done", _ms(t0))
        return {
            "processed": len(processed_docu_nos),
            "processed_docu_nos": processed_docu_nos,
            "result": (
                f"처리 완료 — 결재 대상 {process_count}건 중 {len(processed_docu_nos)}건 결제창 확인"
                f"(가상 상신, 실제 상신 없음). 조회 {rowcount}건 {skip_txt}.{refdoc_txt} 전표: {summary}. "
                "실제 상신은 옴니솔에서 직접 진행하세요."
            ),
        }

    return loop_approvals
