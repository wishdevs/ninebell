"""배치 결재 노드(loop_approvals 배치 모드) — 계획된 그룹 단위로 **한 번에** 결재창을 연다.

사용자 요구(2026-07-27, 외상매출금): 건별 결재 대신 하위(계정정보) 건수 기준 배치 —
단독 200 이상은 먼저 단독으로, 나머지는 합계 200 미만으로 묶어 일괄. 계획은 앞 노드
(`count_details`)가 `state['approval_plan']` 으로 넘긴다.

실측 근거(2026-07-27 프로브 `e2e/voucher_receivable_batch_approval_probe.py`):
  여러 행을 체크한 뒤 결재를 1회 누르면 **자식창(EAP)이 1개** 뜨고 그 안에 **체크한 전표번호가
  모두** 표시된다 = 묶음 결재가 성립한다. 2행으로 확인(대상 2건 전부 커버).

⚠⚠ 절대 안전(건별 모드와 동일) ⚠⚠
  - 결제창에서 **상신·보관 절대 클릭 금지**. 렌더 판정·전표번호 읽기·닫기만 한다.
  - 실제 상신은 사용자가 EAP 에서 직접(handoff_note).

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


def make_batch_approvals_node():
    """`approval_plan` 의 그룹을 순서대로 결재하는 loop_approvals(배치 모드)."""

    async def loop_approvals(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, "loop_approvals", "running")
        t0 = time.monotonic()

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
            indexes = list(group["indexes"])
            keys = [k for k in group.get("docu_nos") or [] if k]
            label = _kind_label(group.get("kind", "batch"), int(group.get("total", 0)), len(indexes))
            await emit_log(
                events,
                f"[{gi + 1}/{len(plan)}] {label} 결재창 확인 중… "
                f"전표: {', '.join(keys) if keys else '(번호미상)'}",
                "action",
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
                    # ⚠ 상신·보관 절대 클릭 금지 — 가상 상신 로그만.
                    processed_docu_nos.extend(keys)
                    await emit_log(
                        events,
                        f"[{gi + 1}/{len(plan)}] 가상 상신 완료 — {len(keys)}건 "
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

            await emit_shot(events.put, page)

        await emit_log(
            events,
            f"결재창 확인 완료 — {len(plan)}회 결재로 {len(processed_docu_nos)}건 가상 상신"
            "(실제 상신 없음).",
            "ok",
        )
        await emit_step(events, "loop_approvals", "done", _ms(t0))
        return {
            "processed": len(processed_docu_nos),
            "processed_docu_nos": processed_docu_nos,
            "result": (
                f"처리 완료 — {len(processed_docu_nos)}건을 {len(plan)}회 결재로 확인"
                "(가상 상신, 실제 상신 없음). 실제 상신은 옴니솔에서 직접 진행하세요."
            ),
        }

    return loop_approvals
