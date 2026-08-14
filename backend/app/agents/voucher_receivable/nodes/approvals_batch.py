"""배치 결재 노드(loop_approvals 배치 모드) — 계획된 그룹 단위로 **한 번에** 결재창을 연다.

사용자 요구(2026-07-27, 외상매출금): 건별 결재 대신 하위(계정정보) 건수 기준 배치 —
단독 200 이상은 먼저 단독으로, 나머지는 합계 200 미만으로 묶어 일괄. 계획은 앞 노드
(`count_details`)가 `state['approval_plan']` 으로 넘긴다.

실측 근거(2026-07-27 프로브 `e2e/voucher_receivable_batch_approval_probe.py`):
  여러 행을 체크한 뒤 결재를 1회 누르면 **자식창(EAP)이 1개** 뜨고 그 안에 **체크한 전표번호가
  모두** 표시된다 = 묶음 결재가 성립한다. 2행으로 확인(대상 2건 전부 커버).

⚠⚠ 안전 규율(건별 모드와 동일 — 정책 전환 2026-08-07) ⚠⚠
  - 상신은 `allow_submit`(기본 False) 게이트 뒤에서만 실클릭한다(steps.click_child_submit,
    묶음 1회 클릭 = 그룹 N건 상신). 게이트가 닫히면 종전대로 렌더 판정·전표번호 읽기·닫기만.
  - **보관은 게이트와 무관하게 절대 클릭 금지.** 상신 실패는 하드 중단(조용한 미상신 금지).

⚠ D7(정합성)은 배치에 맞게 확장된다:
  1. 결재 열기 직전 체크된 행 집합이 **계획한 그룹과 정확히 일치**해야 한다(확인 가능한 경우).
  2. 자식창에 **계획에 없는 전표번호**가 보이면 확정 불일치 → 즉시 중단(다른 문서 혼입).
     계획한 전표 일부가 안 보이는 것(부분 표시)은 대량 배치의 렌더/스크롤 편차일 수 있어
     경고만 남긴다 — 모호를 하드 실패 근거로 쓰지 않는 기존 규율과 동일.
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


def _kind_label(kind: str, total: int, n: int) -> str:
    if kind == "solo":
        return f"단독(하위 {total}건 — 한도 이상)"
    if kind == "unknown":
        return "단독(하위 건수 미상)"
    return f"일괄 {n}건(하위 합계 {total}건)"


def make_batch_approvals_node(*, allow_submit: bool = False):
    """`approval_plan` 의 그룹을 순서대로 결재하는 loop_approvals(배치 모드).

    allow_submit(기본 False): 결제창 '상신' 실클릭 게이트 — 건별 모드와 동일 규율.
    True(매출/매입 빌더)면 그룹당 상신 1회 클릭으로 그 그룹 전표 전부가 상신된다.
    """

    async def loop_approvals(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, "loop_approvals", "running")
        t0 = time.monotonic()
        # 디버그 모드(로그인 체크박스 → params.debug → validate 의 debug_mode, 2026-08-10):
        # 상신 게이트를 **런타임에** 닫는다 — 빌더 게이트(allow_submit)와 AND. 닫히면 종전
        # 가상 상신 경로 그대로(행이 남으므로 재조회·재매핑도 없음).
        submit_on = allow_submit and not bool(state.get("debug_mode"))
        if allow_submit and not submit_on:
            await emit_log(
                events, "디버그 모드 — 상신 버튼을 클릭하지 않습니다(가상 상신, 목록 유지).", "info"
            )

        rowcount = int(state.get("master_rowcount", 0))
        plan = state.get("approval_plan") or []
        if rowcount <= 0 or not plan:
            await emit_log(events, "처리 대상 전표가 없습니다(조회 0건) — 정상 완료.", "info")
            await emit_step(events, "loop_approvals", "done", _ms(t0))
            return {
                "processed": 0,
                "processed_docu_nos": [],
                "result": "처리 완료 — 대상 전표가 없어 결재를 진행하지 않았습니다.",
            }

        total_docs = sum(len(g["indexes"]) for g in plan)
        solo_n = sum(1 for g in plan if g.get("kind") != "batch")
        await emit_log(
            events,
            f"결재 시작 — 대상 {total_docs}건을 {len(plan)}회로 처리합니다"
            f"(단독 {solo_n}회 + 일괄 {len(plan) - solo_n}회).",
            "info",
        )
        await emit_step(
            events, "loop_approvals", "running", progress={"done": 0, "total": total_docs}
        )

        processed_docu_nos: list[str] = []
        # ── 상신 반영 인덱스 재매핑(allow_submit 전용, 2026-08-07 사용자 리포트) ──────
        # 실상신되면 그 행들은 조회 필터(미결·전자결재저장)에서 **사라진다** — 초기 그리드로
        # 계획한 뒤 그룹들의 인덱스가 전부 어긋난다(가상 상신 시절엔 행이 남아 무문제).
        # 규율: 그룹 상신 성공마다 재조회(F2)로 그리드를 확정 상태로 만들고, 이후 그룹의
        # 인덱스는 "이미 상신된 앞 행 수"만큼 차감해 재매핑하며, 체크 **직전** 행 키(DOCU_NO)
        # 대조로 확정 검증한다(불일치=하드, 읽기 실패=모호 soft — D7 규율 동일).
        submitted_original: list[int] = []  # 상신 완료된 그룹들의 **원** 인덱스 누적.
        remaining_expected = rowcount  # 재조회 후 기대 잔여 행수(soft 대조용).

        async def _row_key(idx: int) -> str | None:
            try:
                return await steps.read_row_key(page, idx)
            except Exception:  # noqa: BLE001 — 읽기 실패는 모호(soft) — 키 대조를 생략한다.
                return None

        async def fail(gi: int, reason) -> dict:
            await emit_step(events, "loop_approvals", "failed")
            msg = f"{gi + 1}번째 결재 묶음 처리 실패: {reason}"
            await emit_log(events, msg, "error")
            return {
                "error": msg,
                "processed": len(processed_docu_nos),
                "processed_docu_nos": processed_docu_nos,
            }

        for gi, group in enumerate(plan):
            orig_indexes = list(group["indexes"])
            indexes = orig_indexes
            keys = [k for k in group.get("docu_nos") or [] if k]
            label = _kind_label(group.get("kind", "batch"), int(group.get("total", 0)), len(indexes))
            await emit_log(
                events,
                f"[{gi + 1}/{len(plan)}] {label} 결재창 확인 중… "
                f"전표: {', '.join(keys) if keys else '(번호미상)'}",
                "action",
            )

            if submit_on and submitted_original:
                # 앞 그룹 상신으로 사라진 행 수만큼 현재 위치를 차감(원 인덱스 → 현재 인덱스).
                indexes = [
                    i - sum(1 for s in submitted_original if s < i) for i in orig_indexes
                ]
                await emit_log(
                    events,
                    f"상신 반영 인덱스 재매핑 — 원 {orig_indexes} → 현재 {indexes}.",
                    "info",
                )
                # 체크 직전 행 키 대조 — 재매핑이 실제 그리드와 일치하는지 확정 검증.
                # ⚠ docu_nos 는 planning 때 못 읽은 키가 **필터로 빠진** 리스트다(ApprovalGroup).
                #   길이가 indexes 와 다르면 위치 정렬이 어긋나 엉뚱한 키와 대조한다(리뷰 확정
                #   2026-08-07: 정상 그리드를 오판해 하드 중단) — 길이 일치일 때만 위치별
                #   대조하고, 어긋난 그룹의 최종 방어선은 기존 D7-2(계획 밖 전표 혼입)다.
                raw_keys = list(group.get("docu_nos") or [])
                if len(raw_keys) != len(indexes):
                    await emit_log(
                        events,
                        f"행 키 대조 생략(soft) — 계획 키 {len(raw_keys)}건 ≠ 대상 {len(indexes)}행"
                        "(planning 때 일부 키 미독 — D7-2 로 최종 확인).",
                        "warn",
                    )
                else:
                    for pos, idx in enumerate(indexes):
                        expected = str(raw_keys[pos]).strip() if raw_keys[pos] else None
                        if not expected:
                            continue
                        got = await _row_key(idx)
                        if got and str(got).strip() != expected:
                            return await fail(
                                gi,
                                f"상신 반영 후 행 재확인 실패 — {idx + 1}행 예상 {expected} / "
                                f"실제 {got}(확정 불일치, 재조회 후 위치 어긋남)",
                            )

            # 직전 묶음의 체크가 남아 다른 문서가 함께 올라가지 않도록 전체 해제 후 대상만 체크.
            # (해제 실패 신호는 1회 재시도 — 최종 심판은 아래 D7 체크 집합 대조다.)
            if not await steps.uncheck_all_rows(page):
                await steps.uncheck_all_rows(page)
            for idx in indexes:
                if not await steps.check_row(page, idx):
                    return await fail(gi, f"{idx + 1}행 선택(checkRow) 실패")

            # D7-1: 체크 집합이 계획과 정확히 일치하는지(확인 가능한 경우만 하드). 불일치 시
            # 재체크 1회 — checkRow true 직후 getCheckedRows 가 빈 배열인 지연 재렌더 과도상태가
            # 실측돼 있다(e2e/voucher_payable_d7_probe.py 헤더, 건별 순회와 동일 규율 2026-08-07).
            chk = await steps.checked_row_indexes(page)
            if isinstance(chk, dict) and chk.get("ok"):
                got = sorted(chk.get("rows") or [])
                if got != sorted(indexes):
                    await emit_log(
                        events,
                        f"D7 체크행 불일치(계획 {sorted(indexes)} / 실제 {got}) — 재체크 후 재확인합니다.",
                        "warn",
                    )
                    await asyncio.sleep(1.0)  # 지연 재렌더 정착 대기(실시간).
                    if not await steps.uncheck_all_rows(page):
                        await steps.uncheck_all_rows(page)
                    for idx in indexes:
                        if not await steps.check_row(page, idx):
                            return await fail(gi, f"{idx + 1}행 선택(checkRow) 재시도 실패")
                    await asyncio.sleep(0.5)
                    chk = await steps.checked_row_indexes(page)
                    if isinstance(chk, dict) and chk.get("ok"):
                        got = sorted(chk.get("rows") or [])
                    if got != sorted(indexes):
                        return await fail(
                            gi,
                            "체크된 행이 계획과 다릅니다(D7 정합성, 재체크 후에도): "
                            f"계획 {sorted(indexes)} / 실제 {got}",
                        )
                await emit_log(events, f"D7 체크행 확인 ✅ — {len(got)}행 {got}", "info")
            else:
                await emit_log(events, f"D7 체크행 확인 불가(soft): {chk}", "warn")

            # 결제창을 열기 **직전** 남은 외부 창(공지·홈페이지)을 정리한다 — 화면을 덮은
            # 채 결재 버튼을 누르면 클릭이 가로채인다. ⚠ 이 시점엔 결제창이 아직 없으므로
            # 업무 창을 닫을 위험이 없다(결제창은 아래에서 연다).
            for url in await close_foreign_pages(page, get_settings().erp_base):
                await emit_log(events, f"결재 전 외부 창을 닫았습니다 — {url}", "info")

            child = await steps.open_approval(page)
            if child is None:
                return await fail(gi, "결재창(별도 팝업 Page)이 열리지 않았습니다.")

            mismatch: list[str] = []
            submit_fatal: str | None = None  # 상신 실클릭 실패(게이트 개방 시) — 즉시 중단.
            try:
                if not await steps.poll_child_ready(child):
                    await emit_log(
                        events,
                        f"[{gi + 1}/{len(plan)}] 결제창 렌더를 상한 내 확인하지 못했습니다"
                        "(그래도 상신하지 않고 닫습니다).",
                        "warn",
                    )

                # D7-2: 자식창에 계획 밖 전표가 보이면 확정 불일치(하드), 일부 미표시는 경고.
                shown = await steps.read_child_docu_no(child)
                mismatch = [d for d in shown if d not in keys]
                missing = [k for k in keys if k not in shown]
                if mismatch:
                    await emit_log(
                        events,
                        f"⚠ D7 정합성 오류: 계획에 없는 전표가 결제창에 있습니다 — {mismatch}",
                        "error",
                    )
                elif missing:
                    await emit_log(
                        events,
                        f"D7 부분 확인(soft) — 결제창에서 {len(keys) - len(missing)}/{len(keys)}건 확인"
                        f"(미표시 {missing[:5]}{'…' if len(missing) > 5 else ''}).",
                        "warn",
                    )
                else:
                    await emit_log(
                        events, f"D7 정합성 확인 ✅ — 계획 {len(keys)}건 전부 결제창에 표시됨.", "ok"
                    )

                if not mismatch:
                    if submit_on:
                        # 게이트 개방(2026-08-07) — 묶음 1회 상신 클릭 = 그룹 N건 상신.
                        sub = await steps.click_child_submit(child)
                        if not sub.get("ok"):
                            submit_fatal = (
                                f"상신 실패 — 묶음 {gi + 1}({len(keys)}건): "
                                f"{sub.get('reason') or '사유 미상'}"
                            )
                    if submit_fatal is None:
                        # ⚠ 보관은 게이트와 무관하게 절대 클릭 금지.
                        processed_docu_nos.extend(keys)
                        done_word = "상신 완료" if submit_on else "가상 상신 완료"
                        await emit_log(
                            events,
                            f"[{gi + 1}/{len(plan)}] {done_word} — {len(keys)}건 "
                            f"(누적 {len(processed_docu_nos)}/{total_docs}건).",
                            "ok",
                        )
                        await emit_step(
                            events,
                            "loop_approvals",
                            "running",
                            progress={"done": len(processed_docu_nos), "total": total_docs},
                        )
            finally:
                await steps.close_child(child)

            await steps.settle_parent_after_child_close(page, child)

            if mismatch:
                return await fail(gi, f"결제창에 계획 밖 전표 혼입({mismatch}) — 배치 즉시 중단")
            if submit_fatal is not None:
                # 상신 실패(게이트 개방) — 미상신이 성공으로 둔갑하지 않게 즉시 중단.
                return await fail(gi, submit_fatal)

            if submit_on:
                # 이 그룹 상신 성공 — 원 인덱스를 누적하고, 다음 그룹이 남았으면 재조회(F2)로
                # 그리드를 확정 상태로 만든다(상신된 행은 조회 필터에서 사라진다).
                submitted_original.extend(orig_indexes)
                remaining_expected -= len(orig_indexes)
                if gi + 1 < len(plan):
                    # expected: 기대 잔여 건수 일치 시 즉시 확정 — 무변화 HEAVY 소진(~7s)으로
                    # 매 묶음 지연되는 것을 막는다(사용자 리포트 2026-08-07: 결제 후 ~10s 딜레이).
                    rq = await steps.run_query(page, expected=remaining_expected)
                    if not (isinstance(rq, dict) and rq.get("ok")):
                        return await fail(gi, f"상신 반영 재조회(F2) 실패: {rq}")
                    # 리로드 잔여 오버레이 방어 — 다음 그룹의 checkRow 가 씻겨나가지 않게(라이브
                    # 회귀 2026-08-07: 리로드 완료 전 체크 → '행 미선택' 결재 시도).
                    await steps.wait_loading_overlay_gone(page)
                    got_n = rq.get("rowcount")
                    if got_n != remaining_expected:
                        await emit_log(
                            events,
                            f"상신 반영 재조회 — 잔여 {got_n}건(기대 {remaining_expected}건, soft). "
                            "다음 묶음은 행 키 대조로 확정합니다.",
                            "warn",
                        )
                    else:
                        await emit_log(
                            events, f"상신 반영 재조회 ✅ — 잔여 {got_n}건(기대 일치).", "info"
                        )

            await emit_shot(events.put, page)

        mode_txt = "상신(전자결재 상신 완료)" if submit_on else "가상 상신(실제 상신 없음)"
        await emit_log(
            events,
            f"결재창 확인 완료 — {len(plan)}회 결재로 {len(processed_docu_nos)}건 {mode_txt}.",
            "ok",
        )
        await emit_step(events, "loop_approvals", "done", _ms(t0))
        tail = (
            "취소가 필요하면 전자결재(상신문서)에서 결재취소로 회수할 수 있습니다."
            if submit_on
            else "실제 상신은 옴니솔에서 직접 진행하세요."
        )
        return {
            "processed": len(processed_docu_nos),
            "processed_docu_nos": processed_docu_nos,
            "result": (
                f"처리 완료 — {len(processed_docu_nos)}건을 {len(plan)}회 결재로 {mode_txt}. {tail}"
            ),
        }

    return loop_approvals
