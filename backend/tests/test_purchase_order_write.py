"""구매발주 Phase B(쓰기) — 순수 로직 + 노드 게이트 단위 검증(브라우저 없음).

  (1) descendant_rows/find_set_rows — ds 행 공간에서 SET+자손 집합을 만든다(다음 SET 은 포함 금지).
  (2) check_rows_exact — 체크 집합이 기대와 다르면 저장 전에 하드 실패.
  (3) submit_guard — 결재상태 '저장' ∧ 상신코드 빈칸만 상신.
  (4) self_approve — 디버그 모드/allow_submit=False 면 상신 없이 가상 상신.
"""

from __future__ import annotations

import asyncio

import pytest

from app.agents.purchase_order import steps_write
from app.agents.purchase_order.graph import PurchaseOrderState, build_purchase_order_graph
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


def test_graph_write_nodes_auto_chain():
    """계획 확정 이후 자동 진행(2026-08-31) — plan→save_move 직결, 확인 노드 없음."""
    g = build_purchase_order_graph().get_graph()
    assert {"save_move", "save_units", "self_approve", "place_orders"} <= set(g.nodes)
    assert "confirm_write" not in g.nodes
    edges = {(e.source, e.target) for e in g.edges}
    assert ("plan", "save_move") in edges and ("save_units", "self_approve") in edges


# ── 화면 ③ 구매발주일괄입력 — 계획서 ↔ 팝업/마스터 매핑(순수) ────────────────────
def test_screen3_vendor_keyword_and_matching():
    from app.agents.purchase_order import steps_screen3 as s3

    assert s3.vendor_keyword("주식회사 해룡엔지니어링") == "해룡엔지니어링"
    assert s3.vendor_keyword("(주)와이엔에스테크닉스") == "와이엔에스테크닉스"
    assert s3.vendor_keyword("알파테크") == "알파테크"
    unit = {"seq": 1, "dueDate": "2026-09-30", "vendorGroups": [
        {"vendorClass": "가공품", "vendor": "주식회사 해룡엔지니어링", "dueDate": "2026-09-30", "note": "A [직배송]"},
        {"vendorClass": "판금품", "vendor": "알파테크", "dueDate": "2026-09-23", "note": "B"},
        {"vendorClass": "(주)아진물산", "vendor": "(주)아진물산", "dueDate": "2026-09-23", "note": "C"},
    ]}
    rows = [{"PRINCIPALPARTN_NM": "가공품"}, {"PRINCIPALPARTN_NM": "(주)아진물산"},
            {"PRINCIPALPARTN_NM": "판금품"}, {"PRINCIPALPARTN_NM": "가공품"}]
    assert s3.plan_vendor_changes(unit, rows) == {"주식회사 해룡엔지니어링": [0, 3], "알파테크": [2]}
    assert s3.vendor_group_for(unit, "주식회사 해룡엔지니어링")["note"] == "A [직배송]"
    assert s3.vendor_group_for(unit, "(주)아진물산")["dueDate"] == "2026-09-23"
    assert s3.vendor_group_for(unit, "없는거래처") is None


def test_place_orders_targets_from_state_and_order_prqs_param():
    from app.agents.purchase_order.nodes.place_orders import targets_from_state

    plan = {"units": [{"seq": 1, "vendorGroups": []}, {"seq": 2, "vendorGroups": []}]}
    st = {"confirmed_plan": plan, "purchase_request_nos": [{"seq": 2, "number": "PRQ2"}, {"seq": 1, "number": None}]}
    assert targets_from_state(st) == [("PRQ2", plan["units"][1], False)]
    st2 = {"params": {"purchase_order": {"plan": plan, "order_prqs": ["PRQ1=1", "PRQ9=9"]}}}
    assert targets_from_state(st2) == [("PRQ1", plan["units"][0], True), ("PRQ9", {}, True)]
    # 자동 재개 — resume.prqs 는 그 런의 보관 계획서(planByRun)에서 unit 을 찾아 prior=True 로 합류.
    old_plan = {"units": [{"seq": 1, "vendorGroups": [], "dueDate": "2026-09-01"}]}
    st3 = {
        "confirmed_plan": plan,
        "purchase_request_nos": [{"seq": 1, "number": "PRQ-NEW"}],
        "resume": {
            "prqs": [
                {"seq": 1, "number": "PRQ-OLD", "runId": "r-old"},
                {"seq": 1, "number": "PRQ-NEW", "runId": "r-old"},  # 중복은 미합류
            ],
            "planByRun": {"r-old": old_plan},
        },
    }
    t3 = targets_from_state(st3)
    assert ("PRQ-NEW", plan["units"][0], False) in t3
    assert ("PRQ-OLD", old_plan["units"][0], True) in t3 and len(t3) == 2


def test_screen3_due_before_today():
    from app.agents.purchase_order.steps_screen3 import due_before_today

    assert due_before_today("2026-08-21", "2026-08-28")
    assert not due_before_today("2026-08-28", "2026-08-28")
    assert not due_before_today("2026-09-30", "2026-08-28")
    assert not due_before_today("", "2026-08-28")


# ── 자동 재개(2026-08-31) — 런 로그 파서(순수) ─────────────────────────────────
def test_resume_parse_run_artifacts():
    from app.services.purchase_order_resume import parse_run_artifacts

    logs = [
        {"message": "실행 전 선택한 프로젝트 'ETRIBE ERP TEST 005' 적용 중… (도움창 검색어 'ETRI-005', 코드 ETRI-005)"},
        {"message": "프로젝트 'ETRIBE ERP TEST 005'(코드 ETRI-005) 적용 — 필드 반영 확인 ✅"},
        {"message": "이동요청 저장 완료 — 92행, 이동요청번호 IRQ2026081447."},
        {"message": "발주단위 #1 저장 완료 — 구매요청번호 PRQ2026080754."},
        {"message": "발주단위 #4 저장 완료 — 구매요청번호 PRQ2026080757."},
        {"level": "error", "message": "발주단위 #5 구매요청 저장 실패 — ..."},
    ]
    art = parse_run_artifacts(logs)
    assert art["projectCode"] == "ETRI-005"
    assert art["moveRequestNo"] == "IRQ2026081447"
    assert art["units"] == [(1, "PRQ2026080754"), (4, "PRQ2026080757")]
    assert parse_run_artifacts([]) == {"projectCode": None, "moveRequestNo": None, "units": []}
