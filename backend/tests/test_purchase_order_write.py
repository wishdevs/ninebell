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
    logs.append({"message": "PRQ2026080754: 상신 완료 — 결재상태 종결 · 결재상신코드 (주)나인벨-2026-17482."})
    logs.append({"message": "PRQ2026080754: 발주 저장 완료 — 발주번호 ['PUR2026082421']."})
    art = parse_run_artifacts(logs)
    assert art["projectCode"] == "ETRI-005"
    assert art["moveRequestNo"] == "IRQ2026081447"
    assert art["units"] == [(1, "PRQ2026080754"), (4, "PRQ2026080757")]
    assert art["submitted"] == {"PRQ2026080754"} and art["ordered"] == {"PRQ2026080754"}
    empty = parse_run_artifacts([])
    assert empty["projectCode"] is None and empty["units"] == [] and empty["submitted"] == set()


@pytest.mark.asyncio
async def test_resume_candidates_lists_only_pending_projects(sm):
    """중단 배너 후보 — 잔여 PRQ 가 있는 프로젝트만, 소유 스코프로 반환."""
    import uuid as _uuid
    from datetime import datetime, timezone

    from app.models.agent_run import AgentRun
    from app.services.purchase_order_resume import resume_candidates

    uid = _uuid.uuid4()
    t = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
    interrupted = [  # ETRI-006: PRQ2 저장만 되고 상신·발주 미완 → 후보
        {"message": "프로젝트 'ETRIBE ERP TEST 006'(코드 ETRI-006) 적용 — 필드 반영 확인 ✅"},
        {"message": "이동요청 저장 완료 — 10행, 이동요청번호 IRQ0006."},
        {"message": "발주단위 #1 저장 완료 — 구매요청번호 PRQ0001."},
        {"message": "발주단위 #2 저장 완료 — 구매요청번호 PRQ0002."},
        {"message": "PRQ0001: 상신 완료 — 결재상태 종결."},
        {"message": "PRQ0001: 발주 저장 완료 — 발주번호 ['PUR1']."},
    ]
    completed = [  # ETRI-005: 전 PRQ 상신+발주 완료 → 후보 아님
        {"message": "프로젝트 'ETRIBE ERP TEST 005'(코드 ETRI-005) 적용 — 필드 반영 확인 ✅"},
        {"message": "발주단위 #1 저장 완료 — 구매요청번호 PRQ0005."},
        {"message": "PRQ0005: 상신 완료 — 결재상태 종결."},
        {"message": "PRQ0005: 발주 저장 완료 — 발주번호 ['PUR5']."},
    ]
    async with sm() as s:
        s.add(AgentRun(id="r-int", agent_id="purchase-order", user_id=uid,
                       status="failed", started_at=t, logs=interrupted))
        s.add(AgentRun(id="r-done", agent_id="purchase-order", user_id=uid,
                       status="succeeded", started_at=t, logs=completed))
        await s.commit()

    out = await resume_candidates(user_id=uid)
    assert [c["projectCode"] for c in out] == ["ETRI-006"]
    assert out[0]["projectName"] == "ETRIBE ERP TEST 006"
    assert out[0]["pendingPrqs"] == ["PRQ0002"]
    assert (out[0]["lastRunAt"] or "").startswith("2026-08-31T10:00:00")  # SQLite 는 tz 미보존
    # 소유 스코프 — 다른 사용자에게는 빈 목록.
    assert await resume_candidates(user_id=_uuid.uuid4()) == []


def test_resume_regexes_match_node_skip_wordings():
    """가드 스킵 로그(기록 자가 보정)가 재개 파서 규격과 일치해야 한다 — 문구 드리프트 방지."""
    from app.services.purchase_order_resume import RE_ORDERED, RE_SUBMITTED

    # self_approve 가드 스킵 / 실상신, place_orders 팝업 0행 스킵 / 실발주 — 노드 f-string 과 동일 형태.
    assert RE_SUBMITTED.search("PRQ1: 상신 완료 — 이전 런에서 상신됨(결재상태 '진행'). 건너뜁니다.")
    assert RE_SUBMITTED.search("PRQ1: 상신 완료 — 결재상태 종결 · 결재상신코드 (주)나인벨-2026-1.")
    assert RE_ORDERED.search("PRQ1: 발주 저장 완료 — 이전 런에서 발주됨(팝업 잔여 0행). 건너뜁니다.")
    assert RE_ORDERED.search("PRQ1: 발주 저장 완료 — 발주번호 ['PUR1'].")
    # 가상 상신(디버그)은 완료로 오인하면 안 된다.
    assert not RE_SUBMITTED.search("PRQ1: (가상 상신) 결재창 확인 후 닫습니다.")


def test_graph_read_bom_resume_edge_registered():
    """no_modules ∧ resume.prqs 재개 분기(read_bom→save_move)가 엣지 매핑에 있어야 한다.

    2026-08-31 ETRI-007 실런: 라우터는 'save_move' 를 반환했지만 add_conditional_edges 매핑에
    없어 KeyError 로 죽었다 — 라우터 반환값 전수(plan/self_approve/place_orders/save_move)를 잠근다.
    """
    g = build_purchase_order_graph().get_graph()
    edges = {(e.source, e.target) for e in g.edges}
    for target in ("plan", "self_approve", "place_orders", "save_move"):
        assert ("read_bom", target) in edges, f"read_bom→{target} 엣지 누락"
