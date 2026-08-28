"""구매발주 Phase B(쓰기) — 순수 로직 + 노드 게이트 단위 검증(브라우저 없음).

  (1) descendant_rows/find_set_rows — ds 행 공간에서 SET+자손 집합을 만든다(다음 SET 은 포함 금지).
  (2) check_rows_exact — 체크 집합이 기대와 다르면 저장 전에 하드 실패.
  (3) submit_guard — 결재상태 '저장' ∧ 상신코드 빈칸만 상신.
  (4) confirm_write — '중단' 이면 write_aborted + result(저장 0건), 그래프는 END 로.
  (5) self_approve — 디버그 모드/allow_submit=False 면 상신 없이 가상 상신.
"""

from __future__ import annotations

import asyncio

import pytest

from app.agents.purchase_order import steps_write
from app.agents.purchase_order.graph import PurchaseOrderState, build_purchase_order_graph
from app.agents.purchase_order.nodes import make_confirm_write_node
from app.live.hitl import resolve_hitl, set_hitl_owner
from tests.support.state_contract import assert_keys_declared

ROWS = [
    {"i": 1, "level": 1, "ITEM_CD": "PJT"},
    {"i": 2, "level": 2, "ITEM_CD": "MACH"},
    {"i": 3, "level": 3, "ITEM_CD": "SET-A"},
    {"i": 4, "level": 4, "ITEM_CD": "P1"},
    {"i": 5, "level": 4, "ITEM_CD": "P2"},
    {"i": 6, "level": 3, "ITEM_CD": "SET-B"},
    {"i": 7, "level": 4, "ITEM_CD": "P3"},
    {"i": 8, "level": 3, "ITEM_CD": "SET-A"},  # 중복 코드(다른 장비)
]


def test_descendant_rows_stops_at_next_set():
    assert steps_write.descendant_rows(ROWS, 3) == [4, 5]
    assert steps_write.descendant_rows(ROWS, 6) == [7]
    assert steps_write.descendant_rows(ROWS, 99) == []


def test_find_set_rows_missing_and_duplicate_are_explicit():
    assert steps_write.find_set_rows(ROWS[:7], ["SET-B"]) == {"ok": True, "rows": [6]}
    r = steps_write.find_set_rows(ROWS, ["SET-X"])
    assert r["ok"] is False and "찾지 못했습니다" in r["reason"]
    r = steps_write.find_set_rows(ROWS, ["SET-A"])
    assert r["ok"] is False and "여러 개" in r["reason"]


def test_view_accepts_move_only_vs_purchase_only():
    assert steps_write.view_accepts({"count": 163, "mvY": 132, "mvN": 31, "leafN": 0}, move_only=True)
    assert not steps_write.view_accepts({"count": 164, "mvY": 0, "mvN": 31, "leafN": 0}, move_only=True)
    assert not steps_write.view_accepts({"count": 793, "mvY": 132, "mvN": 661, "leafN": 630}, move_only=True)
    assert steps_write.view_accepts({"count": 664, "mvY": 0}, move_only=False)
    assert not steps_write.view_accepts({"count": 0, "mvY": 0}, move_only=False)


class _GridPage:
    """checkAll/checkRows 만 흉내 — checkRow 전파 결과(checked)를 시험 시나리오로 주입."""

    def __init__(self, checked_after: list[int]):
        self.checked_after = checked_after

    async def evaluate(self, script, arg=None):
        if "checkAll" in script:
            return {"ok": True, "before": 0, "after": 0}
        if "checkRow" in script:
            return {"ok": True, "checked": self.checked_after}
        raise AssertionError(script[:40])


@pytest.mark.asyncio
async def test_check_rows_exact_rejects_overflow_into_next_unit():
    ok = await steps_write.check_rows_exact(_GridPage([3, 4, 5]), [3], [3, 4, 5])
    assert ok["ok"] is True
    bad = await steps_write.check_rows_exact(_GridPage([3, 4, 5, 6, 7]), [3], [3, 4, 5])
    assert bad["ok"] is False and "초과 [6, 7]" in bad["reason"]


def test_due_date_digits_normalizes_js_date_to_kst():
    from datetime import datetime, timezone

    from app.agents.purchase_order.nodes.save_units import _digits

    assert _digits(datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)) == "20260828"
    assert _digits("2026-08-28") == "20260828"
    assert _digits("2026-08-28T00:00:00") == "20260828"


def test_submit_guard():
    assert steps_write.submit_guard({"ATHZ_ST_NM": "저장", "GWDOCU_NO": ""}) is None
    assert steps_write.submit_guard({"ATHZ_ST_NM": "진행", "GWDOCU_NO": "(주)나인벨-2026-1"})
    assert steps_write.submit_guard({"ATHZ_ST_NM": "저장", "GWDOCU_NO": "X"})


def _plan():
    return {
        "project": {"code": "1", "name": "ETRI-001"},
        "units": [{"seq": 1, "purchaseReason": "ETRI-001 BUFFER", "dueDate": "2026-12-31",
                   "modules": [{"itemCode": "SET-A", "name": "외주조립-BUFFER"}], "vendorGroups": []}],
    }


@pytest.mark.asyncio
async def test_confirm_write_abort_ends_without_error():
    events = asyncio.Queue()
    node = make_confirm_write_node()
    state = {"events": events, "confirmed_plan": _plan(), "project": {"code": "1"}, "owner": "u", "run_id": "r"}
    task = asyncio.create_task(node(state))
    frame = None
    for _ in range(50):
        await asyncio.sleep(0.01)
        while not events.empty():
            f = events.get_nowait()
            if "hitl" in f:
                frame = f["hitl"]
        if frame:
            break
    assert frame and frame["kind"] == "confirm" and [o["value"] for o in frame["options"]] == ["yes", "no"]
    set_hitl_owner(frame["id"], "u")
    assert resolve_hitl(frame["id"], {"value": "no"})
    out = await task
    assert out["write_aborted"] is True and "error" not in out
    assert_keys_declared(PurchaseOrderState, out)


def test_graph_has_write_nodes_and_abort_edge():
    g = build_purchase_order_graph().get_graph()
    assert {"confirm_write", "save_move", "save_units", "self_approve"} <= set(g.nodes)
    edges = {(e.source, e.target) for e in g.edges}
    assert ("confirm_write", "save_move") in edges and ("confirm_write", "__end__") in edges
