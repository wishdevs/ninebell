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
    # ETRI-028 실측(2026-09-02): 이동요청만 뷰에 N 리프 5행 잔존 — leafN==0 하드 조건이면 영원히 미수락.
    assert steps_write.view_accepts({"count": 112, "mvY": 76, "mvN": 36, "leafN": 5}, move_only=True)
    # 조회 전 스테일 구매요청만 뷰(mvY 잔존 2)는 이동요청만으로 수락하면 안 된다.
    assert not steps_write.view_accepts({"count": 686, "mvY": 2, "mvN": 684, "leafN": 650}, move_only=True)
    assert not steps_write.view_accepts({"count": 793, "mvY": 132, "mvN": 661, "leafN": 630}, move_only=True)
    assert steps_write.view_accepts({"count": 664, "mvY": 0, "mvN": 664, "leafN": 633}, move_only=False)
    # ETRI-014 잔존 mvY(2026-09-01 라이브) — 구매불가 리프가 MV_FG='Y' 로 남아도 구매요청만 수락.
    assert steps_write.view_accepts({"count": 619, "mvY": 2, "mvN": 617, "leafN": 588}, move_only=False)
    # 구조행뿐(리프 0)인 스냅샷은 구매요청만으로 수락하지 않는다.
    assert not steps_write.view_accepts({"count": 164, "mvY": 0, "mvN": 164, "leafN": 0}, move_only=False)
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


def test_screen3_empty_principal_vendor_rows():
    """품목주거래처 공란 행 — ERP 가 하단 적용을 조용히 거부(2026-09-01 프로브)하는 케이스.

    '미지정' 그룹에 실거래처가 있으면 변경거래처 매핑에 포함, 라벨 echo('미지정')뿐이면
    unorderable 로 분류해 하단 적용에서 제외한다.
    """
    from app.agents.purchase_order import steps_screen3 as s3

    rows = [{"PRINCIPALPARTN_NM": "(주)아진물산"}, {"PRINCIPALPARTN_NM": ""}, {"PRINCIPALPARTN_NM": None}]
    # ① 실거래처 미지정(라벨 echo) → 매핑 없음 + 공란 행 전부 제외 대상.
    unit_echo = {"seq": 3, "vendorGroups": [{"vendorClass": "미지정", "vendor": "미지정"}]}
    assert s3.plan_vendor_changes(unit_echo, rows) == {}
    assert s3.unorderable_positions(unit_echo, rows) == [1, 2]
    # ② '미지정' 그룹에 실거래처 지정 → 공란 행을 그 거래처로 매핑, 제외 없음.
    unit_real = {"seq": 3, "vendorGroups": [{"vendorClass": "미지정", "vendor": "알파테크"}]}
    assert s3.plan_vendor_changes(unit_real, rows) == {"알파테크": [1, 2]}
    assert s3.unorderable_positions(unit_real, rows) == []
    # ③ '미지정' 그룹 자체가 없으면(공란 부품 없던 계획) 공란 행은 제외 대상.
    unit_none = {"seq": 3, "vendorGroups": []}
    assert s3.unorderable_positions(unit_none, rows) == [1, 2]


@pytest.mark.asyncio
async def test_place_orders_parallel_workers_split_queue_and_aggregate(monkeypatch):
    """병렬 발주(2026-09-01) — 워커 3개(메인+부트스트랩 2)가 PRQ 큐를 분담하고, 실패 PRQ 는
    기록만 남기고 나머지를 완주한 뒤 종합 보고한다. done 은 대상 순서로 정렬된다."""
    import asyncio

    from app.agents.purchase_order.nodes import place_orders as po_mod

    boots: list = []
    processed: list[str] = []

    class _Ctx:
        async def close(self):  # noqa: D401
            pass

    async def _fake_bootstrap(browser, *, userid, password, base, scale):
        boots.append(userid)
        return _Ctx(), object()

    async def _fake_navigate(page, schema, base, *, emit=None, **kw):
        return None

    async def _fake_process(page, prq, unit, prior, events, today):
        await asyncio.sleep(0)  # 다른 워커에 양보 — 실제 분담을 흉내.
        processed.append(prq)
        if prq == "PRQ3":
            return {"ok": False, "reason": "PRQ3: 실패 재현"}
        if prq == "PRQ4":
            return {"ok": True, "record": None}  # 이미 발주 스킵.
        return {"ok": True, "record": {"prq": prq, "seq": unit.get("seq"), "orders": [f"PUR-{prq}"], "vendors": []}}

    monkeypatch.setattr(po_mod, "_bootstrap_worker_page", _fake_bootstrap)
    monkeypatch.setattr(po_mod, "navigate_schema", _fake_navigate)
    monkeypatch.setattr(po_mod, "_process_prq", _fake_process)

    units = [{"seq": i, "purchaseReason": "r", "dueDate": "2026-12-31"} for i in range(1, 6)]
    state = {
        "events": asyncio.Queue(),
        "page": object(),
        "browser": object(),
        "userid": "이트라이브2",
        "password": "x",
        "params": {},
        "confirmed_plan": {"units": units},
        "purchase_request_nos": [{"seq": i, "number": f"PRQ{i}"} for i in range(1, 6)],
    }
    out = await po_mod.make_place_orders_node()(state)
    assert len(boots) == 2  # 메인 페이지 + 부트스트랩 2 = 워커 3.
    # 전 건 소비 + 실패 1건(소수)은 직렬 재시도 2회(총 3차) 뒤 표면화(2026-09-02 재시도 패스).
    assert sorted(set(processed)) == ["PRQ1", "PRQ2", "PRQ3", "PRQ4", "PRQ5"] and processed.count("PRQ3") == 3
    assert [r["prq"] for r in out["purchase_orders"]] == ["PRQ1", "PRQ2", "PRQ5"]  # 대상 순서 정렬.
    assert "PRQ3" in out["error"] and "1건 실패" in out["error"] and "3건 저장 완료" in out["error"]
    # 워커 상태 프레임(FE 라이브 스테이지 칩) — 부트스트랩 직후 3세션 브로드캐스트, 처리 항목(prq)
    # 이 실리고, 마지막 프레임은 전 워커 done.
    frames = []
    while not state["events"].empty():
        frames.append(state["events"].get_nowait())
    wframes = [f["workers"] for f in frames if isinstance(f, dict) and "workers" in f]
    assert wframes and len(wframes[0]) == 3
    assert any(any(w.get("prq") for w in ws) for ws in wframes)
    assert all(w["status"] == "done" for w in wframes[-1])


@pytest.mark.asyncio
async def test_submit_one_requery_verdict_and_reopen_retry(monkeypatch):
    """상신 무반응 계열(2026-09-01 실측) — 재조회(결재상태)가 진실원천: ① 닫힘 지연이지만
    재조회 종결 → 성공(재시도 없음) ② 재조회 '저장'(미상신 확정) → 결재창 재오픈 1회 재시도 후
    성공 ③ 2차까지 무반응 → 실패(사유에 재조회 상태·재시도 이력)."""
    import asyncio

    from app.agents.purchase_order.nodes import self_approve as sa_mod

    calls = {"open": 0}
    script: dict = {}

    async def _query(page, no):
        return {"ok": True, "row": script["rows"].pop(0)}

    async def _select(page, i):
        return True

    async def _open(page):
        calls["open"] += 1
        return {"ok": True, "child": object(), "selector": "x"}

    async def _ready(child):
        return [{"text": "상신"}]

    async def _click(child):
        return script["clicks"].pop(0)

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(sa_mod.steps_write, "query_request", _query)
    monkeypatch.setattr(sa_mod.steps_write, "select_request_row", _select)
    monkeypatch.setattr(sa_mod.steps_write, "open_request_approval", _open)
    monkeypatch.setattr(sa_mod.voucher_steps, "poll_child_ready", _ready)
    monkeypatch.setattr(sa_mod.voucher_steps, "click_child_submit", _click)
    monkeypatch.setattr(sa_mod.voucher_steps, "close_child", _noop)
    monkeypatch.setattr(sa_mod.voucher_steps, "settle_parent_after_child_close", _noop)
    monkeypatch.setattr(sa_mod, "emit_shot", _noop)

    saved = {"i": 0, "ATHZ_ST_NM": "저장", "GWDOCU_NO": ""}
    done = {"i": 0, "ATHZ_ST_NM": "종결", "GWDOCU_NO": "GW-1"}
    close_fail = {"ok": False, "reason": "상신 클릭 후 결제창이 닫히지 않았습니다(적용 미확인)."}

    # ① 닫힘 지연 + 재조회 종결 → 성공, 결재창은 1번만 열림.
    script.update(rows=[dict(saved), dict(done)], clicks=[dict(close_fail)])
    out = await sa_mod._submit_one(object(), {"number": "PRQA"}, asyncio.Queue(), True)
    assert out["ok"] and out["record"]["status"] == "종결" and calls["open"] == 1

    # ② 1차 무반응(재조회 '저장') → 결재창 재오픈 재시도 → 성공.
    calls["open"] = 0
    script.update(rows=[dict(saved), dict(saved), dict(done)], clicks=[dict(close_fail), {"ok": True}])
    out2 = await sa_mod._submit_one(object(), {"number": "PRQB"}, asyncio.Queue(), True)
    assert out2["ok"] and out2["record"]["submitted"] is True and calls["open"] == 2

    # ③ 2차까지 무반응 → 실패.
    calls["open"] = 0
    script.update(rows=[dict(saved), dict(saved), dict(saved)], clicks=[dict(close_fail), dict(close_fail)])
    out3 = await sa_mod._submit_one(object(), {"number": "PRQC"}, asyncio.Queue(), True)
    assert not out3["ok"] and "재조회 결재상태" in out3["reason"] and calls["open"] == 2


@pytest.mark.asyncio
async def test_self_approve_parallel_workers_then_cleanup_pass(monkeypatch):
    """병렬 상신(2026-09-01) — 워커 3개가 PRQ 큐를 분담, 실패 PRQ 는 기록 후 나머지 완주.
    끝나면 정리 패스가 추가 세션을 전부 닫고 FE 자식창 표시를 해제한다('한 개의 창' 정돈 —
    발주는 새 병렬 세션으로, 사용자 지시)."""
    import asyncio

    from app.agents.purchase_order.nodes import self_approve as sa_mod

    boots: list = []
    closed: list = []
    processed: list[str] = []

    class _Ctx:
        async def close(self):
            closed.append(1)

    async def _fake_bootstrap(browser, *, userid, password, base, scale):
        boots.append(userid)
        return _Ctx(), object()

    async def _fake_navigate(page, schema, base, *, emit=None, **kw):
        return None

    async def _fake_plant(page):
        return {"ok": True}

    async def _fake_submit(page, x, events, submit_on):
        await asyncio.sleep(0)
        processed.append(x["number"])
        if x["number"] == "PRQ2":
            return {"ok": False, "reason": "PRQ2: 상신 실패 재현"}
        return {"ok": True, "record": {"number": x["number"], "submitted": True}}

    monkeypatch.setattr(sa_mod, "_bootstrap_worker_page", _fake_bootstrap)
    monkeypatch.setattr(sa_mod, "navigate_schema", _fake_navigate)
    monkeypatch.setattr(sa_mod.steps_write, "ensure_req_plant", _fake_plant)
    monkeypatch.setattr(sa_mod, "_submit_one", _fake_submit)

    state = {
        "events": asyncio.Queue(),
        "page": object(),
        "browser": object(),
        "userid": "이트라이브2",
        "password": "x",
        "params": {},
        "purchase_request_nos": [{"seq": i, "number": f"PRQ{i}"} for i in range(1, 5)],
    }
    out = await sa_mod.make_self_approve_node(allow_submit=True)(state)
    assert len(boots) == 2 and len(closed) == 2  # 워커 3 부트스트랩, 정리 패스가 추가 세션 종료.
    assert sorted(set(processed)) == ["PRQ1", "PRQ2", "PRQ3", "PRQ4"] and processed.count("PRQ2") == 3  # 직렬 재시도 2회.
    assert [r["number"] for r in out["submitted"]] == ["PRQ1", "PRQ3", "PRQ4"]
    assert "PRQ2" in out["error"] and "1건 실패" in out["error"]
    assert "worker_pool" not in out  # 인계 폐기 — 발주는 새 세션으로.
    # 워커 칩 프레임 — 3세션 브로드캐스트 + 처리 항목 탑재 + 최종 전원 done. 정리 패스는
    # FE 자식창(PIP) 표시 해제 프레임을 남긴다.
    frames = []
    while not state["events"].empty():
        frames.append(state["events"].get_nowait())
    wframes = [f["workers"] for f in frames if isinstance(f, dict) and "workers" in f]
    assert wframes and len(wframes[0]) == 3
    assert any(any(w.get("prq") for w in ws) for ws in wframes)
    assert all(w["status"] == "done" for w in wframes[-1])
    assert any(isinstance(f, dict) and f.get("closed") and f.get("window") == "child" for f in frames)


@pytest.mark.asyncio
async def test_place_orders_serial_fallback_without_browser(monkeypatch):
    """browser 가 없거나 대상이 1건이면 부트스트랩 없이 메인 페이지 단독(직렬)으로 완주한다."""
    import asyncio

    from app.agents.purchase_order.nodes import place_orders as po_mod

    async def _boom(*a, **k):  # 부트스트랩이 불리면 안 된다.
        raise AssertionError("bootstrap should not be called")

    async def _fake_navigate(page, schema, base, *, emit=None, **kw):
        return None

    async def _fake_process(page, prq, unit, prior, events, today):
        return {"ok": True, "record": {"prq": prq, "seq": unit.get("seq"), "orders": [], "vendors": []}}

    monkeypatch.setattr(po_mod, "_bootstrap_worker_page", _boom)
    monkeypatch.setattr(po_mod, "navigate_schema", _fake_navigate)
    monkeypatch.setattr(po_mod, "_process_prq", _fake_process)
    state = {
        "events": asyncio.Queue(),
        "page": object(),
        "browser": None,
        "params": {},
        "confirmed_plan": {"units": [{"seq": 1}, {"seq": 2}]},
        "purchase_request_nos": [{"seq": 1, "number": "PRQ1"}, {"seq": 2, "number": "PRQ2"}],
    }
    out = await po_mod.make_place_orders_node()(state)
    assert "error" not in out
    assert [r["prq"] for r in out["purchase_orders"]] == ["PRQ1", "PRQ2"]


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


# ── 화면 ③ 팝업 — 행 식별키 재탐색(2026-09-02 ETRI-026 118/119 변경거래처 미반영 23/23) ─────
# 조회 직후 잡은 행 번호가 늦게 온 필터 재조회로 무효화되면 반영 확인(전부 None)·재클릭(체크 0행)이
# 헛돌았다. 행 번호 대신 식별키(구매요청번호|순번|품목코드#n)로 매 단계 다시 찾는다.
from app.agents.purchase_order import steps_screen3 as _s3  # noqa: E402


class _PopupPage:
    """팝업 그리드 흉내 — rows 를 시나리오가 갈아끼우고, [적용] 클릭 시 on_apply 콜백이 반영을 흉내낸다."""

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.checked: list[int] = []
        self.on_apply = None
        self.apply_clicks = 0
        self.pick_calls = 0

    async def evaluate(self, script, arg=None):
        if "checkAll(" in script:
            self.checked = []
            return {"ok": True, "before": 0, "after": 0}
        if "checkRow(" in script:
            _, idxs = arg
            for i in idxs:
                if i not in self.checked:
                    self.checked.append(i)
            return {"ok": True, "checked": list(self.checked)}
        if "getJsonRows" in script:
            return {"ok": True, "rowCount": len(self.rows), "rows": [dict(r) for r in self.rows]}
        if "getValue(i, f)" in script:
            _, idxs, fields = arg
            return {i: {f: (self.rows[i].get(f) if i < len(self.rows) else None) for f in fields} for i in idxs}
        raise AssertionError(script[:60])


def _prow(prq: str, item: str, cls: str = "판금품") -> dict:
    return {"PURREQ_NO": prq, "ITEM_CD": item, "PRINCIPALPARTN_NM": cls, "CHG_PARTNER_NM": None, "CHG_PARTNER_CD": None}


def _patch_popup(monkeypatch, page: _PopupPage):
    async def _pick(pg, field, kw):
        page.pick_calls += 1
        return {"ok": True, "display": kw}

    async def _click(pg, elem_id):
        page.apply_clicks += 1
        if page.on_apply:
            page.on_apply(page)
        return {"ok": True}

    async def _sleep(_s):
        return None

    monkeypatch.setattr(_s3, "pick_code_document", _pick)
    monkeypatch.setattr(_s3, "click_by_id", _click)
    monkeypatch.setattr(_s3.verify, "DEFAULT_SLEEP", _sleep)


def test_row_keys_distinguish_duplicate_items_by_order():
    rows = [_prow("P1", "A"), _prow("P1", "A"), _prow("P2", "A")]
    assert _s3.row_keys(rows) == ["P1||A#0", "P1||A#1", "P2||A#0"]


@pytest.mark.asyncio
async def test_popup_apply_vendor_relocates_rows_after_grid_refresh(monkeypatch):
    # 조회 시점: 타 요청 잔존 2행 + 대상 2행(번호 2,3). [적용] 직후 그리드가 필터 재조회로
    # 갈아끼워져 대상 행이 0,1 번으로 옮겨가고 값은 그 새 행에 반영된다 → 키로 다시 찾아 성공.
    page = _PopupPage([_prow("X1", "Z"), _prow("X2", "Z"), _prow("P1", "A"), _prow("P1", "B")])
    keys = [_s3.row_keys(page.rows)[2], _s3.row_keys(page.rows)[3]]

    def _apply(pg: _PopupPage):
        pg.rows = [_prow("P1", "A"), _prow("P1", "B")]
        for r in pg.rows:
            r["CHG_PARTNER_NM"], r["CHG_PARTNER_CD"] = "알파테크", "10061"
        pg.checked = []

    page.on_apply = _apply
    _patch_popup(monkeypatch, page)
    r = await _s3.popup_apply_vendor(page, [2, 3], "알파테크", keys=keys)
    assert r["ok"] is True and r["relocated"] is True and r["retried"] is False
    assert r["idxs"] == [0, 1] and r["codes"] == ["10061"]


@pytest.mark.asyncio
async def test_popup_apply_vendor_retry_rechecks_rows_and_repicks(monkeypatch):
    # 1차 [적용]이 무반응(체크만 풀림) → 종전엔 빈 적용을 재클릭해 헛돌았다. 이제 행 재체크 +
    # 피커 재선택 후 재클릭하고, 2차에서 반영되면 retried=True 로 성공한다.
    page = _PopupPage([_prow("P1", "A"), _prow("P1", "B"), _prow("P1", "C", "가공품")])
    keys = _s3.row_keys(page.rows)[:2]

    def _apply(pg: _PopupPage):
        if pg.apply_clicks == 1:
            pg.checked = []  # 무반응 + 체크 풀림
            return
        assert sorted(pg.checked) == [0, 1], "재클릭 전에 행이 다시 체크돼 있어야 한다"
        for i in pg.checked:
            pg.rows[i]["CHG_PARTNER_NM"], pg.rows[i]["CHG_PARTNER_CD"] = "알파테크", "10061"

    page.on_apply = _apply
    _patch_popup(monkeypatch, page)
    r = await _s3.popup_apply_vendor(page, [0, 1], "알파테크", keys=keys)
    assert r["ok"] is True and r["retried"] is True and r["idxs"] == [0, 1]
    assert page.apply_clicks == 2 and page.pick_calls == 2
    assert page.rows[2]["CHG_PARTNER_NM"] is None  # 대상 아닌 행은 손대지 않는다.


@pytest.mark.asyncio
async def test_popup_apply_vendor_fails_when_rows_vanish(monkeypatch):
    page = _PopupPage([_prow("P1", "A")])
    keys = _s3.row_keys(page.rows)

    def _apply(pg: _PopupPage):
        pg.rows = [_prow("Q9", "Z")]  # 대상 행이 사라짐(재조회 결과에 없음)
        pg.checked = []

    page.on_apply = _apply
    _patch_popup(monkeypatch, page)
    r = await _s3.popup_apply_vendor(page, [0], "알파테크", keys=keys)
    assert r["ok"] is False and "재탐색 실패" in r["reason"]


@pytest.mark.asyncio
async def test_popup_bottom_apply_relocates_by_keys(monkeypatch):
    # 변경거래처 적용 뒤 그리드가 재정렬돼도 하단 적용은 키로 찾은 새 번호를 체크한다.
    page = _PopupPage([_prow("P1", "A"), _prow("P1", "B")])
    keys = _s3.row_keys(page.rows)  # A#0, B#0
    page.rows = [_prow("P1", "B"), _prow("P1", "A")]  # 재정렬
    seen: dict = {}

    async def _box(*a, **k):
        return None  # 버튼 탐색 실패로 끊어 체크 결과만 검증

    orig = page.evaluate

    async def _ev(script, arg=None):
        if "confirm.ok" in script:
            seen["checked"] = list(page.checked)
            return None
        return await orig(script, arg)

    page.evaluate = _ev
    r = await _s3.popup_bottom_apply(page, [0, 1], keys=keys)
    assert r["ok"] is False and "버튼" in r["reason"]
    assert sorted(seen["checked"]) == [0, 1]
    # 부분 키만 남아도 새 번호로 매핑된다.
    page.checked = []
    r2 = await _s3.popup_bottom_apply(page, [0], keys=[keys[0]])  # A → 재정렬 후 1번
    assert r2["ok"] is False and seen["checked"] == [1]


# ── 재시도 패스(2026-09-02 사용자 설계) — 병렬 1차 → 소수 실패는 직렬, 다수 실패는 재병렬 ────
from app.agents.purchase_order import parallel as _par  # noqa: E402


def test_plan_retry_thresholds():
    assert _par.plan_retry(0, 5, 1) is None
    assert _par.plan_retry(1, 5, 1) == "serial"  # 소수(3 미만·절반 미만)
    assert _par.plan_retry(3, 5, 1) == "parallel"  # 3건 이상
    assert _par.plan_retry(2, 4, 1) == "parallel"  # 절반 이상
    assert _par.plan_retry(1, 1, 1) == "serial"  # 1건 배치는 직렬(세션 1개면 충분)
    assert _par.plan_retry(4, 5, 2) == "serial"  # 2차 이후는 항상 직렬
    assert _par.plan_retry(1, 5, 3) is None  # 최대 3차


@pytest.mark.asyncio
async def test_run_with_retry_logs_each_pass_and_returns_last_errors():
    events = asyncio.Queue()
    calls: list[tuple[str, int, list]] = []

    async def _pass(batch, mode, pass_no):
        calls.append((mode, pass_no, list(batch)))
        # 1차: a,b,c 실패(다수) → 2차 병렬: a 만 실패 → 3차 직렬: a 성공.
        fail = {1: {"a", "b", "c"}, 2: {"a"}, 3: set()}[pass_no]
        failed = [x for x in batch if x in fail]
        return [x for x in batch if x not in fail], failed, [{"prq": x, "reason": f"{x}: 실패"} for x in failed]

    done, errors = await _par.run_with_retry(["a", "b", "c", "d"], _pass, events=events, label="상신", item_id=str)
    assert [(m, n, b) for m, n, b in calls] == [("parallel", 1, ["a", "b", "c", "d"]), ("parallel", 2, ["a", "b", "c"]), ("serial", 3, ["a"])]
    assert sorted(done) == ["a", "b", "c", "d"] and errors == []
    msgs = []
    while not events.empty():
        f = events.get_nowait()
        if isinstance(f, dict) and f.get("log"):
            msgs.append((f.get("level"), f["log"]))
    assert any(lv == "warn" and "1차(병렬) 4건 중 3건 실패 → 병렬로 재시도(2차)" in m for lv, m in msgs)
    assert any(lv == "warn" and "2차(병렬) 3건 중 1건 실패 → 직렬로 재시도(3차)" in m for lv, m in msgs)
    assert not any(lv == "error" for lv, _ in msgs)


@pytest.mark.asyncio
async def test_place_orders_transient_failure_recovers_in_serial_pass(monkeypatch):
    # 혼선·타이밍 실패(1회만 실패)는 직렬 재시도에서 해소돼 실패로 보고되지 않는다.
    from app.agents.purchase_order.nodes import place_orders as po_mod

    attempts: dict[str, int] = {}
    boots: list[str] = []

    class _Ctx:
        async def close(self):
            pass

    async def _fake_bootstrap(browser, *, userid, password, base, scale):
        boots.append(userid)
        return _Ctx(), object()

    async def _fake_navigate(page, schema, base, *, emit=None, **kw):
        return None

    async def _fake_process(page, prq, unit, prior, events, today):
        await asyncio.sleep(0)
        attempts[prq] = attempts.get(prq, 0) + 1
        if prq == "PRQ2" and attempts[prq] == 1:
            return {"ok": False, "reason": "PRQ2: 변경거래처 적용 미반영 행 6/6"}
        return {"ok": True, "record": {"prq": prq, "seq": unit.get("seq"), "orders": [f"PUR-{prq}"], "vendors": []}}

    monkeypatch.setattr(po_mod, "_bootstrap_worker_page", _fake_bootstrap)
    monkeypatch.setattr(po_mod, "navigate_schema", _fake_navigate)
    monkeypatch.setattr(po_mod, "_process_prq", _fake_process)
    units = [{"seq": i, "purchaseReason": "r", "dueDate": "2026-12-31"} for i in range(1, 4)]
    state = {
        "events": asyncio.Queue(), "page": object(), "browser": object(), "userid": "u", "password": "x",
        "params": {}, "confirmed_plan": {"units": units},
        "purchase_request_nos": [{"seq": i, "number": f"PRQ{i}"} for i in range(1, 4)],
    }
    out = await po_mod.make_place_orders_node()(state)
    assert "error" not in out
    assert [r["prq"] for r in out["purchase_orders"]] == ["PRQ1", "PRQ2", "PRQ3"]
    assert attempts == {"PRQ1": 1, "PRQ2": 2, "PRQ3": 1} and len(boots) == 2  # 2차는 직렬(부트스트랩 없음).
    msgs = []
    while not state["events"].empty():
        f = state["events"].get_nowait()
        if isinstance(f, dict) and f.get("log"):
            msgs.append(f["log"])
    assert any("1차(병렬) 3건 중 1건 실패 → 직렬로 재시도(2차): PRQ2" in m for m in msgs)
    assert any("직렬 발주(재시도 2차)" in m for m in msgs)


@pytest.mark.asyncio
async def test_self_approve_many_failures_retry_in_parallel(monkeypatch):
    # 다수(3건 이상) 실패면 2차도 병렬 — 세션을 다시 띄운다(부트스트랩 2+2).
    from app.agents.purchase_order.nodes import self_approve as sa_mod

    attempts: dict[str, int] = {}
    boots: list[str] = []

    class _Ctx:
        async def close(self):
            pass

    async def _fake_bootstrap(browser, *, userid, password, base, scale):
        boots.append(userid)
        return _Ctx(), object()

    async def _fake_navigate(page, schema, base, *, emit=None, **kw):
        return None

    async def _fake_plant(page):
        return {"ok": True}

    async def _fake_submit(page, x, events, submit_on):
        await asyncio.sleep(0)
        no = x["number"]
        attempts[no] = attempts.get(no, 0) + 1
        if no in ("PRQ1", "PRQ2", "PRQ3") and attempts[no] == 1:
            return {"ok": False, "reason": f"{no}: 결재창 무반응"}
        return {"ok": True, "record": {"number": no, "submitted": True}}

    monkeypatch.setattr(sa_mod, "_bootstrap_worker_page", _fake_bootstrap)
    monkeypatch.setattr(sa_mod, "navigate_schema", _fake_navigate)
    monkeypatch.setattr(sa_mod.steps_write, "ensure_req_plant", _fake_plant)
    monkeypatch.setattr(sa_mod, "_submit_one", _fake_submit)
    state = {
        "events": asyncio.Queue(), "page": object(), "browser": object(), "userid": "u", "password": "x",
        "params": {}, "purchase_request_nos": [{"seq": i, "number": f"PRQ{i}"} for i in range(1, 6)],
    }
    out = await sa_mod.make_self_approve_node(allow_submit=True)(state)
    assert "error" not in out
    assert [r["number"] for r in out["submitted"]] == ["PRQ1", "PRQ2", "PRQ3", "PRQ4", "PRQ5"]
    assert len(boots) == 4  # 1차 병렬 2 + 2차 병렬(실패 3건 → 세션 3) 2.
    msgs = []
    while not state["events"].empty():
        f = state["events"].get_nowait()
        if isinstance(f, dict) and f.get("log"):
            msgs.append(f["log"])
    assert any("1차(병렬) 5건 중 3건 실패 → 병렬로 재시도(2차)" in m for m in msgs)
    assert any("병렬 상신(재시도 2차)" in m for m in msgs)
    assert any("추가 세션 4개 종료" in m for m in msgs)
