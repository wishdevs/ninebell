"""count_details 노드 — 결재 **전에** 대상 전표별 하위(계정정보) 건수를 파악해 배치를 계획한다.

사용자 요구(2026-07-27, 외상매출금): "전체 갯수를 파악 후 각 리스트가 가진 하위 그리드 리스트
갯수를 파악한다. 단독 200 이상은 먼저 결재하고, 나머지는 묶어서 200이 안 되도록 일괄 결재한다."

run_query 와 loop_approvals **사이**에 삽입된다(배치 모드에서만 — 카드는 미삽입).
산출: state['approval_plan'] = 결재 순서대로의 그룹 목록(단독 먼저, 그 뒤 묶음).
메뉴 필터(state['menu_filters'], 2026-08-20 유형별 병합): 행별 순회 전에 MENU_NM 을 일괄
읽어 필터 밖 행을 계획에서 제외한다 — 읽기 실패는 하드 중단(조용한 무필터 상신 금지).

⚠ 읽기 전용 — 행을 setCurrent 해 디테일을 읽을 뿐 체크·결재·저장을 하지 않는다.
  실측 비용(2026-07-27 프로브, 138건): 평균 372ms/행 · 전수 52초.
"""

from __future__ import annotations

import time

from app.live.events import emit_log, emit_step
from nbkit.patterns import emit_shot

from .. import steps
from ..batching import ApprovalTarget, plan_approval_groups


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def make_count_details_node(limit: int):
    """대상 행을 훑어 하위 건수를 모으고 결재 그룹을 계획하는 노드를 만든다."""

    async def count_details(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, "count_details", "running")
        t0 = time.monotonic()

        rowcount = int(state.get("master_rowcount", 0))
        max_rows = state.get("max_rows")
        n = rowcount if max_rows is None else min(int(max_rows), rowcount)
        if n <= 0:
            await emit_log(events, "대상 전표가 없어 건수 파악을 건너뜁니다.", "info")
            await emit_step(events, "count_details", "done", _ms(t0))
            return {"approval_plan": [], "detail_counts": {}}

        # ── 메뉴 필터(2026-08-20 유형별 병합) — 행별 순회(372ms/행) **전에** 일괄 제외 ──────
        # MENU_NM 을 왕복 1회로 일괄 읽어 필터 밖 행의 인덱스를 확정한다. 제외 행은 계획
        # (targets/approval_plan)에 아예 넣지 않는다 — approvals_batch 의 인덱스 재매핑은
        # 상신된 행만 차감하므로 계획 단계 제외는 안전하다(제외 행은 그리드에 그대로 남는다).
        menu_filters = list(state.get("menu_filters") or [])
        indexes = list(range(n))
        if menu_filters:
            res = await steps.read_master_menus(page, n)
            rows = res.get("rows") if isinstance(res, dict) and res.get("ok") else None
            if rows is None or len(rows) < n:
                # ⚠ 조용한 무필터 진행 금지(실패 표면화) — 필터는 사용자가 지정한 제약이라,
                # 못 읽으면 의도 밖 전표가 상신될 수 있으므로 하드 중단한다.
                await emit_step(events, "count_details", "failed")
                msg = (
                    "메뉴 컬럼을 읽지 못해 메뉴 필터를 적용할 수 없습니다 — 필터 없이 진행하면 "
                    f"의도 밖 전표가 상신될 수 있어 중단합니다. ({res})"
                )
                await emit_log(events, msg, "error")
                return {"error": msg}
            allowed = set(menu_filters)
            indexes = [r["idx"] for r in rows[:n] if str(r.get("menu") or "").strip() in allowed]
            await emit_log(
                events,
                f"메뉴 필터({'·'.join(menu_filters)}) — 대상 {n}건 중 {n - len(indexes)}건 제외, "
                f"{len(indexes)}건 진행.",
                "info",
            )
            if not indexes:
                await emit_log(events, "메뉴 필터로 전 건이 제외돼 결재 대상이 없습니다.", "info")
                await emit_step(events, "count_details", "done", _ms(t0))
                return {"approval_plan": [], "detail_counts": {}}

        total = len(indexes)
        await emit_log(events, f"대상 {total}건의 하위(계정정보) 건수를 파악합니다…", "action")
        await emit_step(events, "count_details", "running", progress={"done": 0, "total": total})

        targets: list[ApprovalTarget] = []
        counts: dict[str, int] = {}
        unverified = 0
        for pos, idx in enumerate(indexes):
            key = await steps.read_row_key(page, idx)
            r = await steps.read_detail_count(page, idx, key)
            count = int(r.get("count", -1))
            targets.append(ApprovalTarget(idx=idx, docu_no=key, count=count))
            if key:
                counts[key] = count
            if not r.get("verified"):
                unverified += 1
                # 소유 확인 실패 = 그 행의 디테일임을 보장 못 함 → 단독 처리로 빠진다(계획 단계).
                await emit_log(
                    events,
                    f"[{pos + 1}/{total}] 전표 {key or '(번호미상)'} 하위 건수 확인 실패 — 단독 결재로 분류. "
                    f"({r.get('reason')})",
                    "warn",
                )
            if (pos + 1) % 10 == 0 or pos + 1 == total:
                await emit_step(
                    events, "count_details", "running", progress={"done": pos + 1, "total": total}
                )

        groups = plan_approval_groups(targets, limit)
        plan = [
            {
                "kind": g.kind,
                "indexes": g.indexes,
                "docu_nos": g.docu_nos,
                "total": g.total,
            }
            for g in groups
        ]
        solo_n = sum(1 for g in groups if g.kind != "batch")
        batch_n = len(groups) - solo_n
        readable = [t.count for t in targets if t.count >= 0]
        await emit_log(
            events,
            f"하위 건수 파악 완료 — 대상 {total}건 / 하위 합계 {sum(readable)}건"
            f"(최소 {min(readable) if readable else 0}·최대 {max(readable) if readable else 0}). "
            f"결재 계획: 단독 {solo_n}건(한도 {limit} 이상 또는 건수 미상) + 일괄 {batch_n}묶음 "
            f"= 총 {len(groups)}회 결재.",
            "ok",
        )
        if unverified:
            await emit_log(
                events, f"⚠ 건수를 확인하지 못한 {unverified}건은 단독 결재로 처리합니다.", "warn"
            )
        await emit_shot(events.put, page)
        await emit_step(events, "count_details", "done", _ms(t0))
        return {"approval_plan": plan, "detail_counts": counts}

    return count_details
