"""비용분할 노드 — 분할처리 팝업 확정 레시피(PROCESS.md D2/D7 + 쓰기 프로브 최종 라운드).

확정 레시피 순서: 명시 행들(추가·적요·금액) → [잔액행이면] 더미 행 추가·적요 → 실클릭 선택 →
차액반영(새 잔액행 생성 사양) → 잔액행 적요 입력 → 잉여 빈 행 삭제 → **전 행** 비용센터
(#keyword)·프로젝트(#s_search_key) → 적용→예→확인(닫힘 미확인 = 하드 실패) →
**잔존 '예산현황' 창 닫기**(분할 확정이 추가로 띄운다 — 안 닫으면 F7 이 게이트에 막힌다).

⚠ 분할행의 상대계정(FEOTH_ACCT)은 채우지 않는다 — 편집 위젯이 없고 저장 시 자동 파생되는
필드다(2026-08-19 headed 세션 확정). 분할 F7 반려의 진짜 원인은 자금과목(FUND_CD) 미입력이며
그건 fill_rows 가 행0에 채운다.

분할이 아닌 실행은 스텝만 닫고 통과한다.
"""

from __future__ import annotations

import time

from app.agents.card_collect.mgmt_items import _select_detail_row as select_detail_row
from app.live.events import emit_log, emit_step
from nbkit.omnisol import js_lib
from nbkit.patterns import emit_shot

from .. import steps


async def _detail_rowcount(page) -> int:
    n = await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)
    return n if isinstance(n, int) else -1


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def make_split_costs_node():
    """분할처리 팝업 다행 분개 확정. 실패는 즉시 error 단락(비가역 게이트 준수)."""

    async def split_costs(state: dict) -> dict:
        if state.get("error") or state.get("aborted"):
            return {}
        events = state["events"]
        page = state["page"]
        plan = state.get("plan") or {}
        await emit_step(events, "split_costs", "running")
        t0 = time.monotonic()
        if not plan.get("split"):
            await emit_log(events, "분할 없음 — 비용분할을 건너뜁니다.", "info")
            await emit_step(events, "split_costs", "done", _ms(t0))
            return {}

        async def fail(what: str, reason) -> dict:
            await emit_step(events, "split_costs", "failed")
            msg = f"비용분할 실패({what}): {reason}"
            await emit_log(events, msg, "error")
            return {"error": msg}

        # 분할 계획 출처: 발행 후는 개입(splitPlan → state.split_plan), 발행 전 폼 경로는 plan.
        # ⚠ 차액반영 판정이 출처마다 다르다 — 개입 계획은 마지막 amount=None 이 곧 차액반영이고,
        #   폼 경로는 정규화(resolve_split_amounts)가 잔액을 이미 채워 넣어 amount 로는 알 수 없다
        #   (그래서 plan 의 split_balance_last 플래그를 쓴다).
        hitl_rows = state.get("split_plan") or []
        if hitl_rows:
            rows = hitl_rows
            via_balance = rows[-1].get("amount") is None
        else:
            rows = plan.get("split_rows") or []
            via_balance = bool(plan.get("split_balance_last"))
        if not rows:
            return await fail("분할 계획", "분할 계획이 비어 있습니다.")

        op = await steps.open_split_popup(page)
        if not op.get("ok"):
            return await fail("팝업 열기", op.get("reason"))
        await emit_log(events, f"분할처리 팝업 진입 — 계획 {len(rows)}행.", "info")

        # 1) 명시 금액 행들 — 추가(행수 증가 확인) → 적요 → 금액.
        explicit = rows[:-1] if via_balance else rows
        for i, row in enumerate(explicit):
            r = await steps.add_split_row(page)
            if not r.get("ok"):
                return await fail(f"{i + 1}행 추가", r.get("reason"))
            r = await steps.set_split_note(page, i, row["note"])
            if not r.get("ok"):
                return await fail(f"{i + 1}행 적요", r.get("reason"))
            r = await steps.set_split_amount(page, i, row["amount"])
            if not r.get("ok"):
                return await fail(f"{i + 1}행 금액", r.get("reason"))

        # 2) 잔액행(마지막 amount=null) — 더미 행 추가·적요 → 실클릭 선택 → 차액반영 →
        #    잔액행 적요 → 잉여(금액 공백) 행 삭제. 차액반영은 **새 행을 생성**하는 사양이라
        #    미리 만든 더미는 고아로 남는다(녹화도 직후 삭제 — 확정 레시피 그대로).
        if via_balance:
            last = rows[-1]
            dummy_idx = len(explicit)
            r = await steps.add_split_row(page)
            if not r.get("ok"):
                return await fail("잔액용 행 추가", r.get("reason"))
            r = await steps.set_split_note(page, dummy_idx, last["note"])
            if not r.get("ok"):
                return await fail("잔액용 행 적요", r.get("reason"))
            r = await steps.select_split_row(page, dummy_idx)
            if not r.get("ok"):
                return await fail("잔액용 행 선택", r.get("reason"))
            r = await steps.apply_balance(page)
            if not r.get("ok"):
                return await fail("차액반영", r.get("reason"))
            grid_rows = r.get("rows") or []
            # 차액반영은 **새 행을 뒤에 만든다** — 직전 행수(명시행 + 더미 1) 이후가 잔액행이다.
            # 적요로 찾으면 안 된다: ERP 가 그 행에 **문서 적요를 복사**해 넣는다(실측).
            bal_idx = steps.balance_row_index(grid_rows, dummy_idx + 1)
            if bal_idx is not None:  # 잔액행 적요는 정리 **전**에 채운다(순서 민감 — 실측).
                r = await steps.set_split_note(page, bal_idx, last["note"])
                if not r.get("ok"):
                    return await fail("잔액행 적요", r.get("reason"))
            else:
                # 조용히 넘기지 않는다 — 못 찾으면 사용자가 입력한 마지막 행 적요가 반영되지
                # 않은 채 저장된다(2026-08-25 RN202608250010 에서 실제로 그랬다).
                await emit_log(
                    events,
                    f"⚠ 잔액행을 특정하지 못해 마지막 분할행 적요 '{last['note']}' 를 넣지 못했습니다 "
                    f"(차액반영 후 {len(grid_rows)}행, 기대 인덱스 ≥{dummy_idx + 1}) "
                    "— 금액 배분은 정상이며, 저장 후 ERP 에서 적요만 확인해 주세요.",
                    "warn",
                )
            grid_rows = await steps.dump_split_rows(page)
            # 잉여(금액 공백) 행 정리 — 뒤에서부터 삭제(인덱스 흔들림 방지).
            for oi in sorted(steps.orphan_row_indexes(grid_rows), reverse=True):
                r = await steps.delete_split_row(page, oi)
                if not r.get("ok"):
                    return await fail(f"잉여 행 삭제(행 {oi + 1})", r.get("reason"))

        # 3) 전 행 비용센터·프로젝트 — 남은 모든 행에 채워야 '적용'이 닫힌다(실측 확정 조건).
        grid_rows = await steps.dump_split_rows(page)
        mapping = steps.map_split_plan_to_grid(rows, grid_rows)
        if mapping is None:
            return await fail(
                "행 매핑",
                f"분할 그리드 행수({len(grid_rows)})가 계획({len(rows)})과 다릅니다.",
            )
        for plan_row, gi in zip(rows, mapping):
            r = await steps.fill_split_picker(
                page, gi, steps.DIST_CC_FIELD, f"비용센터(행{gi + 1})", plan_row["cost_center"]
            )
            if not r.get("ok"):
                return await fail(f"행{gi + 1} 비용센터", r.get("reason"))
            r = await steps.fill_split_picker(
                page, gi, steps.DIST_PJT_FIELD, f"프로젝트(행{gi + 1})", plan_row["project_wbs"],
                wbs_exact=True,
            )
            if not r.get("ok"):
                return await fail(f"행{gi + 1} 프로젝트", r.get("reason"))
        await emit_shot(events.put, page)

        # 4) 적용→예→확인 — 팝업 닫힘(개수 감소) 미확인이면 하드 실패(팬텀 저장 방지).
        r = await steps.confirm_split_apply(page)
        if not r.get("ok"):
            return await fail("적용 확정", r.get("reason"))
        await emit_log(events, "분할 확정 — 메인 그리드에 배부비용행 반영.", "ok")

        # 5) 분할 확정이 추가로 띄우는 '예산현황' 창 정리 — 잔존하면 save_doc 의 F7 사전
        #    게이트(열린 팝업 0)에 걸려 저장이 중단된다(SPLIT11 스모크 3회 동일 재현).
        bs = await steps.close_budget_status_popup(page)
        if not bs.get("ok"):
            return await fail("예산현황 창 정리", bs.get("reason"))
        if bs.get("closed"):
            await emit_log(events, f"'예산현황' 창 {bs['closed']}장을 닫았습니다.", "info")

        # 6) 배부비용행의 계정 관리항목 — 분할이 **새 detail 행을 만들기 때문에**, apply_invoices
        #    가 원본행에만 채운 결제조건·자금예정일이 새 행에는 없다. 비과세 계정(13)은 그래서
        #    "계정의 관리항목[결제조건] …" 으로 F7 이 반려됐다(2026-08-25 실측 — 과세 11 은 그
        #    계정이 요구하지 않아 통과했다). 행마다 선택해 **요구하는 것만** 채운다(둘 다 gated).
        due_date = ""
        for sel in state.get("invoice_selection") or []:
            due_date = (sel.get("grid_row") or {}).get("invoiceDate") or ""
            break
        n_rows = await _detail_rowcount(page)
        for i in range(max(0, n_rows)):
            if not await select_detail_row(page, i):
                return await fail(f"배부행 선택(행 {i + 1})", "상세 행을 선택하지 못했습니다.")
            st = await steps.fill_settlement_terms(page)
            if not st.get("ok"):
                return await fail(f"배부행 결제조건(행 {i + 1})", st.get("reason"))
            dd = await steps.fill_fund_due_date(page, due_date)
            if not dd.get("ok"):
                return await fail(f"배부행 자금예정일(행 {i + 1})", dd.get("reason"))
        await emit_shot(events.put, page)
        await emit_step(events, "split_costs", "done", _ms(t0))
        return {"split_done": True}

    return split_costs
