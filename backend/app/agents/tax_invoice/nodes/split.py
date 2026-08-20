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

from app.live.events import emit_log, emit_step
from nbkit.patterns import emit_shot

from .. import steps


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
            bal_idx = steps.balance_row_index(grid_rows)
            if bal_idx is not None:  # 잔액행 적요는 정리 **전**에 채운다(순서 민감 — 실측).
                r = await steps.set_split_note(page, bal_idx, last["note"])
                if not r.get("ok"):
                    return await fail("잔액행 적요", r.get("reason"))
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
        await emit_shot(events.put, page)
        await emit_step(events, "split_costs", "done", _ms(t0))
        return {"split_done": True}

    return split_costs
