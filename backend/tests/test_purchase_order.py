"""구매발주(purchase-order) Phase A — 그래프·픽스처·plannerBom 조립·계획 검증·HITL 왕복.

Phase A 는 **쓰기 없음**(저장 F7·결재 0줄)이 안전 계약이라 규율이 네 겹이다:
  (1) plannerBom 조립은 순수 함수 — 레벨 매핑(2=장비/3=SET/4=부품, 0=루트·1=프로젝트 라벨 스킵)과
      의사 거래처(가공품·판금품) 분류가 공유 계약 shape 대로 나와야 프론트가 그대로 먹는다.
  (2) 계획 제출 검증 — units≥1 · 각 unit purchaseReason·dueDate · 미지정 의사 거래처 없음.
  (3) HitlDecision.plan 왕복 — 모델 필드 + payload dict **동시** 추가(한쪽 누락 = 조용한
      유실, 2026-07-05 grid 회귀 선례)로 제출이 노드 큐까지 도달해야 한다.
  (4) 픽스처 steps 는 그래프 노드 등록 순서와 lockstep(진행 하이라이트 정합).
"""

from __future__ import annotations

import asyncio

import pytest

from app.agents.purchase_order import js as js_mod
from app.agents.purchase_order import planner
from app.agents.purchase_order import steps as steps_mod
from app.agents.purchase_order.graph import PurchaseOrderState, build_purchase_order_graph
from app.agents.purchase_order.nodes import plan as plan_mod
from app.agents.purchase_order.nodes import (
    make_pick_project_node,
    make_plan_node,
    make_read_bom_node,
    make_report_node,
)
from app.live.hitl import _hitl_queues, resolve_hitl, set_hitl_owner
from tests.support.state_contract import assert_keys_declared

AGENT_ID = "purchase-order"

GRAPH_STEP_KEYS = [
    "login",
    "user_type",
    "menu_nav",
    "pick_project",
    "read_bom",
    "plan",
    "confirm_write",
    "save_move",
    "save_units",
    "self_approve",
    "report",
]


def _q() -> asyncio.Queue:
    return asyncio.Queue()


def _frames(q: asyncio.Queue) -> list[dict]:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


class _Page:
    """노드가 만지는 page 는 전부 steps 로 위임되므로 스크린샷 스텁이면 충분하다."""

    async def screenshot(self, **kw):
        return b""


# ── plannerBom 조립(순수 함수) ────────────────────────────────────────────────
def _grid_row(level: int, **fields) -> dict:
    return {"i": 0, "level": level, **fields}


def _sample_rows() -> list[dict]:
    return [
        # levelmap 재실측(2026-08-13): 0=루트(필드 비어 있음) / 1=프로젝트 라벨 행(WBS_NM 이
        # 프로젝트명 — wbs 오염원) / 2=장비 / 3=SET / 4=부품.
        _grid_row(0),
        _grid_row(1, ITEM_CD="2297", ITEM_NM="프로젝트", WBS_NM="CX85-137, 12CH PROCESS"),
        _grid_row(
            2, ITEM_CD="328-22376", ITEM_NM="PROCESS, 12CH_HC", ITEM_SPEC_DC="X1-01",
            UNIT_DC="SYS", WBS_NM="PO-2026-07-4136",
        ),
        _grid_row(3, ITEM_CD="SET-001", ITEM_NM="외주조립-BUFFER", ITEM_SPEC_DC="Assy", UNIT_DC="SET", BOM_QT="1"),
        _grid_row(
            4, ITEM_CD="12P-B00B2-3", ITEM_NM="Buffer Top Plate", ITEM_SPEC_DC="(외주조립)",
            UNIT_DC="EA", BOM_QT="4", RMND_QT="4", UNTPC="173,000", AMT="692,000",
            VEND_NM="가공품", ACCT_NM="원재료", PUR_FG="Y",
        ),
        _grid_row(
            4, ITEM_CD="12P-X01-0", ITEM_NM="Sheet Cover", UNIT_DC="EA", BOM_QT="2",
            RMND_QT="0", UNTPC="9000", AMT="18000", VEND_NM="판금품", PUR_FG="N",
        ),
        _grid_row(3, ITEM_CD="SET-002", ITEM_NM="외주조립-ALIGN", UNIT_DC="SET", BOM_QT="2"),
        _grid_row(
            4, ITEM_CD="A-1", ITEM_NM="Align Base", UNIT_DC="EA", BOM_QT="1",
            RMND_QT="1", UNTPC="5000", AMT="5000", VEND_NM="해룡", PUR_FG="Y",
        ),
    ]


def _shallow_rows() -> list[dict]:
    """발주 완료 BOM 실측(ZJ90-130) — SET(3레벨) 아래 리프가 하나도 없다.
    화면 실측: 17행 = 프로젝트1 + 장비1 + 외주조립 SET 15(하위 부품 0)."""
    return [
        _grid_row(0),
        _grid_row(1, ITEM_CD="2261", ITEM_NM="프로젝트", WBS_NM="ZJ90-130,  8CH BS PROCESS"),
        _grid_row(
            2, ITEM_CD="328-20773", ITEM_NM="PROCESS, 8CH BS", ITEM_SPEC_DC="X8-01.2M4F",
            UNIT_DC="SYS", BOM_QT="1", WBS_NM="PO-2026-06-8668",
        ),
        _grid_row(
            3, ITEM_CD="ZJ90-130-PROCESS-BUFFER", ITEM_NM="Process-Buffer Assy",
            UNIT_DC="SET", BOM_QT="1", RMND_QT="1", VEND_NM="외주조립-BUFFER", PUR_FG="Y",
        ),
        _grid_row(
            3, ITEM_CD="ZJ90-130-PROCESS-ELECTRIC", ITEM_NM="Process-Electric Part",
            UNIT_DC="SET", BOM_QT="1", RMND_QT="1", VEND_NM="외주조립-ELECTRIC", PUR_FG="Y",
        ),
    ]


def test_assemble_drops_modules_without_parts():
    """사용자 확정 2026-08-14: 하위 부품이 없는 SET = 발주 완료분이라 계획서에 노출하지 않는다.
    (2026-08-13 의 '자식 없는 SET 을 자기 자신으로 채우는' 보정은 완료분까지 띄우던 오독.)"""
    bom = planner.assemble_planner_bom(
        _shallow_rows(), {"code": "2261", "name": "ZJ90-130,  8CH BS PROCESS"}
    )
    assert bom["machines"] == []  # 모듈이 다 빠지면 빈 껍데기 장비도 남기지 않는다.
    summary = planner.summarize_bom(bom, 17)
    assert summary["modules"] == 0 and summary["parts"] == 0
    assert bom["project"]["wbs"] == "PO-2026-06-8668"  # 프로젝트 라벨 행 WBS 오염 방지 유지


def test_assemble_keeps_only_modules_that_have_parts():
    """섞인 BOM — 리프가 있는 SET 만 남고, 없는 SET 은 조용히 빠진다."""
    rows = [
        _grid_row(2, ITEM_CD="M-1", ITEM_NM="장비", WBS_NM="PO-1"),
        _grid_row(3, ITEM_CD="SET-DONE", ITEM_NM="발주 완료 SET"),
        _grid_row(3, ITEM_CD="SET-OPEN", ITEM_NM="남은 SET"),
        _grid_row(4, ITEM_CD="P-1", ITEM_NM="부품"),
    ]
    bom = planner.assemble_planner_bom(rows, {"code": "1", "name": "x"})
    assert [m["itemCode"] for m in bom["machines"][0]["modules"]] == ["SET-OPEN"]


def test_deep_bom_keeps_real_leaves_only():
    """깊은 BOM(CX85-137)은 종전 그대로 — SET 자신을 부품으로 넣지 않는다(중복 방지)."""
    bom = planner.assemble_planner_bom(
        _sample_rows(), {"code": "2297", "name": "CX85-137, 12CH PROCESS"}
    )
    modules = bom["machines"][0]["modules"]
    assert [len(m["parts"]) for m in modules] == [2, 1]
    assert all(p["itemCode"] != m["itemCode"] for m in modules for p in m["parts"])


def test_assemble_planner_bom_maps_levels_to_contract_shape():
    bom = planner.assemble_planner_bom(
        _sample_rows(), {"code": "2297", "name": "CX85-137, 12CH PROCESS"}
    )
    # project — wbs 는 그리드 WBS_NM 에서 회수.
    assert bom["project"] == {
        "code": "2297",
        "name": "CX85-137, 12CH PROCESS",
        "wbs": "PO-2026-07-4136",
    }
    # machine(레벨 2) 1개 — 레벨 0(루트)·1(프로젝트 라벨)은 조립 대상이 아니다.
    assert len(bom["machines"]) == 1
    machine = bom["machines"][0]
    assert machine["itemCode"] == "328-22376" and machine["unit"] == "SYS"
    # module(레벨 3 = SET) 2개, parts(레벨 4) 는 각 모듈 아래.
    assert [m["itemCode"] for m in machine["modules"]] == ["SET-001", "SET-002"]
    part = machine["modules"][0]["parts"][0]
    assert part == {
        "itemCode": "12P-B00B2-3",
        "name": "Buffer Top Plate",
        "spec": "(외주조립)",
        "unit": "EA",
        "bomQty": 4,
        "remainQty": 4,
        "unitPrice": 173000,  # '173,000' 표시값 관용 파싱.
        "amount": 692000,
        "vendorClass": "가공품",  # 의사 거래처 분류는 그리드 값 그대로 보존.
        "account": "원재료",
        "purchasable": True,
    }
    # PUR_FG='N' → purchasable False.
    assert machine["modules"][0]["parts"][1]["purchasable"] is False
    assert machine["modules"][1]["parts"][0]["vendorClass"] == "해룡"


def test_assemble_planner_bom_drops_orphan_rows():
    # 계층이 깨진 행(machine 없는 SET, module 없는 부품)은 버린다 — 조립을 죽이지 않는다.
    rows = [
        _grid_row(4, ITEM_CD="orphan-part", ITEM_NM="고아 부품"),
        _grid_row(3, ITEM_CD="orphan-set", ITEM_NM="고아 SET"),
        _grid_row(2, ITEM_CD="M-1", ITEM_NM="장비"),
        _grid_row(3, ITEM_CD="SET-1", ITEM_NM="모듈"),
        _grid_row(4, ITEM_CD="P-1", ITEM_NM="부품"),
    ]
    bom = planner.assemble_planner_bom(rows, {"code": "1", "name": "x"})
    assert len(bom["machines"]) == 1
    assert [m["itemCode"] for m in bom["machines"][0]["modules"]] == ["SET-1"]
    assert [p["itemCode"] for p in bom["machines"][0]["modules"][0]["parts"]] == ["P-1"]


def test_summarize_bom_counts():
    bom = planner.assemble_planner_bom(
        _sample_rows(), {"code": "2297", "name": "CX85-137"}
    )
    s = planner.summarize_bom(bom, total_rows=8)
    assert s == {
        "gridRows": 8,
        "machines": 1,
        "modules": 2,
        "parts": 3,
        "purchasableParts": 2,
    }


# ── 계획 제출 검증 ────────────────────────────────────────────────────────────
def _plan(**over) -> dict:
    base = {
        "project": {"code": "2297", "name": "CX85-137"},
        "wbs": "PO-2026-07-4136",
        "units": [
            {
                "seq": 1,
                "purchaseReason": "CX85-137 · 12CH PROCESS BUFFER",
                "dueDate": "2026-09-01",
                "modules": [{"itemCode": "SET-001", "name": "외주조립-BUFFER", "spec": ""}],
                "vendorGroups": [
                    {"vendorClass": "가공품", "vendor": "해룡", "parts": 3, "amount": 692000,
                     "dueDate": "2026-09-01", "note": ""},
                    {"vendorClass": "해룡", "vendor": None, "parts": 1, "amount": 5000,
                     "dueDate": "2026-08-25", "note": ""},
                ],
            }
        ],
    }
    base.update(over)
    return base


def test_validate_plan_accepts_complete_plan():
    ok, reason = planner.validate_plan(_plan())
    assert ok is True and reason == ""


def test_validate_plan_rejects_empty_units():
    ok, reason = planner.validate_plan(_plan(units=[]))
    assert ok is False and "발주단위가 없습니다" in reason


@pytest.mark.parametrize("field,needle", [("purchaseReason", "구매사유"), ("dueDate", "납기예정일")])
def test_validate_plan_requires_reason_and_due_per_unit(field, needle):
    p = _plan()
    p["units"][0][field] = "  "
    ok, reason = planner.validate_plan(p)
    assert ok is False and needle in reason and "1" in reason


def test_validate_plan_rejects_unresolved_pseudo_vendor():
    # 의사 거래처(가공품·판금품)는 실거래처 확정 필수 — 실거래처 그룹의 vendor None 은 허용.
    p = _plan()
    p["units"][0]["vendorGroups"][0]["vendor"] = ""
    ok, reason = planner.validate_plan(p)
    assert ok is False and "가공품" in reason and "실거래처" in reason


def test_validate_plan_rejects_unresolved_otech_vendor():
    # '주식회사 오텍'은 실거래처명 분류지만 통합 지정으로 교체 가능(2026-08-21) —
    # 지정이 해제된 채(vendor 없음) 제출되면 서버가 거른다. 그 외 실거래처 그룹은 종전대로 허용.
    p = _plan()
    p["units"][0]["vendorGroups"].append(
        {"vendorClass": "주식회사 오텍", "vendor": None, "parts": 2, "amount": 1000,
         "dueDate": "2026-08-25", "note": ""},
    )
    ok, reason = planner.validate_plan(p)
    assert ok is False and "주식회사 오텍" in reason and "실거래처" in reason


def test_validate_plan_rejects_non_dict():
    ok, reason = planner.validate_plan(["not-a-dict"])
    assert ok is False


# ── pick_project 노드(스텝 monkeypatch — 브라우저 없이 적용 사이클) ───────────────
def _patch_pick(monkeypatch, *, apply_ok=True, bom_rows=337, header=None):
    calls: dict = {"apply": [], "lookup": 0, "header": 0}

    async def _header(page):
        calls["header"] += 1
        return header if header is not None else {"ok": True, "repaired": []}

    monkeypatch.setattr(steps_mod, "ensure_fixed_header", _header)

    async def _close(page):
        return None

    async def _apply(page, keyword, pjt_no, **kwargs):
        calls["apply"].append((keyword, pjt_no))
        if not apply_ok:
            return {"ok": False, "reason": "적용 실패(테스트)"}
        return {
            "ok": True,
            "name": "CX85-137, 12CH PROCESS",
            "pjt_no": pjt_no or "2297",
            "field_value": "CX85-137",
        }

    async def _lookup(page):
        calls["lookup"] += 1
        return {"ok": True, "via": "button"}

    async def _wait_bom(page, **kw):
        return bom_rows

    monkeypatch.setattr(steps_mod, "close_popup", _close)
    monkeypatch.setattr(steps_mod, "apply_project", _apply)
    monkeypatch.setattr(steps_mod, "click_lookup", _lookup)
    monkeypatch.setattr(steps_mod, "wait_bom_loaded", _wait_bom)
    return calls


# ── 사전 선택(실행 전 폼 params) — 유일한 경로. 개입 폴백 없음(사용자 지시 2026-08-14) ──
_PRESELECT = {
    "purchase_order": {
        "project_no": "2297",
        "project_name": "CX85-137, 12CH PROCESS",
        "keyword": "CX85-137",
    }
}


@pytest.mark.asyncio
async def test_pick_project_applies_preselection_without_hitl(monkeypatch):
    # 실행 전 폼이 고른 프로젝트를 개입(hitl 프레임) 없이 바로 적용·조회하고 끝난다.
    calls = _patch_pick(monkeypatch)
    events = _q()
    out = await asyncio.wait_for(
        make_pick_project_node()({"events": events, "page": _Page(), "params": _PRESELECT}),
        timeout=5,
    )
    assert out["project"] == {"code": "2297", "name": "CX85-137, 12CH PROCESS"}
    assert calls["apply"] == [("CX85-137", "2297")]  # 폼이 준 검색어로 적용.
    assert calls["lookup"] == 1
    assert not [f for f in _frames(events) if "hitl" in f]  # 개입 프레임 0.
    assert_keys_declared(PurchaseOrderState, out)


@pytest.mark.asyncio
async def test_pick_project_apply_failure_is_hard_error(monkeypatch):
    # ⚠ 폴백 제거 회귀 방어: 적용 실패는 개입이 아니라 사유를 실은 하드 실패다.
    calls = _patch_pick(monkeypatch, apply_ok=False)
    events = _q()
    out = await asyncio.wait_for(
        make_pick_project_node()({"events": events, "page": _Page(), "params": _PRESELECT}),
        timeout=5,
    )
    assert "적용 실패(테스트)" in out["error"] and "다시 실행" in out["error"]
    assert calls["apply"] == [("CX85-137", "2297")]  # 시도는 했다.
    assert not [f for f in _frames(events) if "hitl" in f]  # 개입 프레임 0.
    assert_keys_declared(PurchaseOrderState, out)


@pytest.mark.asyncio
async def test_pick_project_hard_fails_when_bom_not_loaded(monkeypatch):
    # 적용은 됐는데 BOM 미로드 — 재실행으로도 안 풀릴 수 있는 화면 문제라 즉시 중단.
    _patch_pick(monkeypatch, bom_rows=0)
    events = _q()
    out = await asyncio.wait_for(
        make_pick_project_node()({"events": events, "page": _Page(), "params": _PRESELECT}),
        timeout=5,
    )
    assert "BOM 그리드가 로드되지 않았습니다" in out["error"]
    assert not [f for f in _frames(events) if "hitl" in f]
    assert_keys_declared(PurchaseOrderState, out)


@pytest.mark.asyncio
async def test_pick_project_without_params_is_hard_error(monkeypatch):
    # params 없음(폼 미사용 — API 직접 호출 등) — 개입을 띄우지 않고 즉시 실패한다.
    calls = _patch_pick(monkeypatch)
    events = _q()
    out = await asyncio.wait_for(
        make_pick_project_node()({"events": events, "page": _Page()}), timeout=5
    )
    assert "실행 전 입력에서 프로젝트를 선택" in out["error"]
    assert calls["apply"] == []
    assert not [f for f in _frames(events) if "hitl" in f]
    assert_keys_declared(PurchaseOrderState, out)


@pytest.mark.asyncio
async def test_pick_project_checks_fixed_header_before_lookup(monkeypatch):
    """D3 — 프로젝트 적용 후 조회(F2) 전에 상단 고정값을 반드시 확인한다."""
    calls = _patch_pick(monkeypatch)
    out = await asyncio.wait_for(
        make_pick_project_node()({"events": _q(), "page": _Page(), "params": _PRESELECT}),
        timeout=5,
    )
    assert out["project"]["code"] == "2297"
    assert calls["header"] == 1 and calls["lookup"] == 1


@pytest.mark.asyncio
async def test_pick_project_reports_fixed_header_repair(monkeypatch):
    # 보정이 일어나면 조용히 넘어가지 않고 로그로 드러낸다(비정상 상태였다는 신호).
    _patch_pick(monkeypatch, header={"ok": True, "repaired": ["구매그룹", "구매사유(비움)"]})
    events = _q()
    out = await asyncio.wait_for(
        make_pick_project_node()({"events": events, "page": _Page(), "params": _PRESELECT}),
        timeout=5,
    )
    assert "project" in out
    msgs = [str(f["log"]) for f in _frames(events) if "log" in f]
    assert any("상단 고정값 보정" in m and "구매그룹" in m for m in msgs)


@pytest.mark.asyncio
async def test_pick_project_hard_fails_when_fixed_header_unfixable(monkeypatch):
    # 구매그룹이 틀린 채로 진행하면 잘못된 조직으로 구매요청이 저장될 수 있다 — 하드 실패.
    calls = _patch_pick(monkeypatch, header={"ok": False, "reason": "'구매그룹' 을 맞추지 못했습니다"})
    out = await asyncio.wait_for(
        make_pick_project_node()({"events": _q(), "page": _Page(), "params": _PRESELECT}),
        timeout=5,
    )
    assert "구매그룹" in out["error"]
    assert calls["lookup"] == 0  # 조회까지 가지 않는다.
    assert_keys_declared(PurchaseOrderState, out)


# ── steps.ensure_fixed_header — 확인이 본업, 세팅은 어긋났을 때만 ────────────────
class _HeaderPage:
    """HEADER_STATE_JS/SET_INPUT_JS 만 해석하는 가짜 페이지(폼 상태를 dict 로 들고 있다)."""

    def __init__(self, state: dict, *, resolves_text: bool = True):
        self.state = dict(state)  # {input id: value}
        self.resolves_text = resolves_text
        self.sets: list[tuple[str, str]] = []

    async def evaluate(self, script, arg=None):
        if script is js_mod.HEADER_STATE_JS:
            code_ids, reason_id = arg
            return {
                "fields": {
                    i: {"code": self.state.get(i), "text": self.state.get(f"{i}_text")}
                    for i in code_ids
                },
                "reason": self.state.get(reason_id),
            }
        if script is js_mod.SET_INPUT_JS:
            fid, value = arg
            self.sets.append((fid, value))
            if fid in self.state or self.resolves_text:
                self.state[fid] = value
                return {"ok": True, "after": value}
            return {"ok": False, "reason": "no-field"}
        raise AssertionError(f"예상 못한 스크립트: {script[:40]}")


_HEADER_OK = {
    "i_purgrp_cd": "1000", "i_purgrp_cd_text": "나인벨",
    "i_purorg_cd": "1000", "i_purorg_cd_text": "나인벨",
    "i_rmk_dc": "",
}


@pytest.mark.asyncio
async def test_ensure_fixed_header_touches_nothing_when_already_correct():
    # 정상 경로(ERP 자동 기본값) — 세팅 0회. 멀쩡한 화면을 건드리지 않는다.
    page = _HeaderPage(_HEADER_OK)
    r = await steps_mod.ensure_fixed_header(page)
    assert r == {"ok": True, "repaired": []}
    assert page.sets == []


@pytest.mark.asyncio
async def test_ensure_fixed_header_sets_code_and_text_together():
    """⚠ 코드만 세팅하면 표시가 해석되지 않는다(프로브 실측) — 코드+표시를 함께 쓴다."""
    page = _HeaderPage({**_HEADER_OK, "i_purgrp_cd": "", "i_purgrp_cd_text": ""})
    r = await steps_mod.ensure_fixed_header(page)
    assert r["ok"] and r["repaired"] == ["구매그룹"]
    assert ("i_purgrp_cd", "1000") in page.sets
    assert ("i_purgrp_cd_text", "나인벨") in page.sets
    assert page.state["i_purorg_cd"] == "1000"  # 멀쩡한 쪽은 안 건드린다.


@pytest.mark.asyncio
async def test_ensure_fixed_header_clears_top_purchase_reason():
    # D3 — 상단 구매사유는 비운다(구매사유는 발주단위별로 계획서에서 받는다).
    page = _HeaderPage({**_HEADER_OK, "i_rmk_dc": "이전 세션 잔상"})
    r = await steps_mod.ensure_fixed_header(page)
    assert r["ok"] and r["repaired"] == ["구매사유(비움)"]
    assert page.state["i_rmk_dc"] == ""


@pytest.mark.asyncio
async def test_ensure_fixed_header_fails_when_repair_does_not_stick():
    # 세팅→독립 확인 규율: 세팅 반환값이 아니라 화면 재독으로 판정한다.
    page = _HeaderPage({**_HEADER_OK, "i_purgrp_cd": "", "i_purgrp_cd_text": ""})

    async def _stubborn(script, arg=None):
        if script is js_mod.SET_INPUT_JS:
            return {"ok": True, "after": arg[1]}  # 세팅했다고 보고만 하고 실제론 안 변함
        return await _HeaderPage.evaluate(page, script, arg)

    page.evaluate = _stubborn  # type: ignore[method-assign]
    r = await steps_mod.ensure_fixed_header(page)
    assert not r["ok"] and "구매그룹" in r["reason"]


@pytest.mark.asyncio
async def test_ensure_fixed_header_fails_when_field_missing():
    page = _HeaderPage({k: v for k, v in _HEADER_OK.items() if k != "i_purorg_cd"})
    r = await steps_mod.ensure_fixed_header(page)
    assert not r["ok"] and "구매조직" in r["reason"]


# ── steps.apply_project — 번호 생략 시 단일 결과만 자동 특정(추측 금지) ─────────────
@pytest.mark.asyncio
async def test_apply_project_without_pjt_no_requires_single_result(monkeypatch):
    async def _close(page):
        return None

    monkeypatch.setattr(steps_mod, "close_popup", _close)
    for rows, count_txt in (([], "0건"), ([{"PJT_NO": "1"}, {"PJT_NO": "2"}], "2건")):
        async def _search(page, kw, retries=2, _rows=rows):
            return {"ok": True, "rows": list(_rows)}

        monkeypatch.setattr(steps_mod, "open_and_search_once", _search)
        r = await steps_mod.apply_project(_Page(), "MISC-ESR3", "")
        assert not r.get("ok") and count_txt in r["reason"]


# ── steps.open_and_search_once — 도움창 실측 정정 반영(2026-08-14 프로브 4/4) ──────
# 라이브 사전선택 529ms 2연속 실패의 원인: trusted Enter 가 #keyword 의 <form> 네이티브 제출
# → SPA 소프트리셋으로 팝업 영구 소멸. 수정: untrusted 제출(SUBMIT_KEYWORD_JS) + 도움창 특정
# 준비 판정(POPUP_STATE_JS) + 사전검색 시그니처 변화 수락 + 소멸 연속 2폴 디바운스.
_READY = {"present": True, "gridReady": True}
_NOT_READY = {"present": True, "gridReady": False}
_GONE = {"present": False, "gridReady": False}
# 팝업이 열리면서 자동 사전검색된 기본 1행(메인폼 현재 프로젝트) — 내 검색 결과가 아니다.
_PRESEARCH_GRID = {"ok": True, "rowCount": 1, "rows": [{"PJT_NO": "2013", "PJT_NM": "MISC-ESR3 #2"}]}
# 내 검색이 반영된 결과 1행 — 사전검색 행(2013)과 시그니처가 달라야 '변화'로 수락된다.
_SEARCH_ROW = {
    "PJT_NO": "2297",
    "PJT_NM": "CX85-137, 12CH PROCESS",
    "START_DT": "2026-01-01",
    "END_DT": "2026-12-31",
    "RSPNBER_EMP_NM": "석대현",
    "PJT_ST_NM": "승인",
}
_RESULT_GRID = {"ok": True, "rowCount": 1, "rows": [dict(_SEARCH_ROW)]}


class _PopupPage:
    """open_and_search_once 용 fake page — evaluate 를 JS 상수로 디스패치.

    popup_states/grids 는 각 스크립트 호출마다 순서대로 소진하고 마지막 값을 유지한다
    (열림 대기 폴 → 제출 전 시그니처 → 검색 정착 폴 → 재시도까지 하나의 평면 타임라인).
    """

    def __init__(self, popup_states, grids=None, prefill=""):
        self._popup_states = list(popup_states)
        self.prefill = prefill  # 팝업 오픈 시 #keyword 프리필(메인폼 현재 프로젝트명)
        self._grids = list(grids or [_PRESEARCH_GRID, _RESULT_GRID])
        self.clicks = 0
        self.submits = 0
        self.keyword_sets = 0   # 실타이핑 횟수(주입 시도 수)
        self.popup_polls = 0
        self.typed = ""
        page = self

        class _Mouse:
            async def click(self, x, y, click_count=1):
                if click_count == 1:  # 피커 재클릭 = 재오픈 → #keyword 는 메인폼 프리필로 돌아간다.
                    page.typed = ""
                page.clicks += 1

        class _Keyboard:
            async def type(self, text, delay=0):
                page.keyword_sets += 1
                page.typed = text

        self.mouse = _Mouse()
        self.keyboard = _Keyboard()

    @staticmethod
    def _take(seq):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    async def evaluate(self, script, arg=None):
        from nbkit.omnisol import js_lib

        if script == js_lib.PROJECT_PICKER_BOX_JS:
            return {"x": 1, "y": 1}
        if script == js_mod.POPUP_STATE_JS:
            self.popup_polls += 1
            return self._take(self._popup_states)
        if script == js_mod.KEYWORD_VALUE_JS:
            return self.typed or self.prefill  # 타이핑 전엔 프리필, 후엔 실타이핑 반영값
        if script == js_mod.KEYWORD_BOX_JS:
            return {"x": 2, "y": 2}
        if script == js_mod.SUBMIT_KEYWORD_JS:
            self.submits += 1
            return True
        if script == js_mod.READ_POPUP_GRID_JS:
            return self._take(self._grids)
        raise AssertionError(f"예상 밖 스크립트 평가: {script[:60]}")


def _instant_sleep(monkeypatch):
    from nbkit.omnisol import verify

    async def _nosleep(seconds):
        return None

    monkeypatch.setattr(verify, "DEFAULT_SLEEP", _nosleep)


@pytest.mark.asyncio
async def test_search_waits_for_popup_ready_then_accepts_changed_grid(monkeypatch):
    # 창 셸/이물 창 단계(present=False)와 그리드 미초기화(gridReady=False) 동안은 제출하지
    # 않고 기다렸다가, 준비 완료 후 untrusted 제출 → 시그니처 변화 즉시 수락.
    _instant_sleep(monkeypatch)
    page = _PopupPage([_GONE, _GONE, _NOT_READY, _READY])
    out = await steps_mod.open_and_search_once(page, "ZJ90-130")
    assert out["ok"] is True and out["attempt"] == 1
    assert out["rows"][0]["PJT_NO"] == "2297"
    assert page.clicks == 1 and page.keyword_sets == 1 and page.submits == 1


@pytest.mark.asyncio
async def test_search_does_not_accept_stale_presearch_grid_early(monkeypatch):
    # 검색 결과가 사전검색과 시그니처까지 같으면(변화 미관측) 최소 정착(MIN) 후에야 수락 —
    # 자동 사전검색 행을 내 검색 결과로 오독하는 조기 수락 방지.
    _instant_sleep(monkeypatch)
    page = _PopupPage([_READY], grids=[_PRESEARCH_GRID])
    out = await steps_mod.open_and_search_once(page, "ZJ90-130")
    assert out["ok"] is True and out["attempt"] == 1
    # MIN_SEARCH_SETTLE_MS(1200)/POLL_MS(300) → 정착 폴 최소 5회(준비 1회 제외).
    assert page.popup_polls >= 6


@pytest.mark.asyncio
async def test_search_survives_transient_popup_vanish(monkeypatch):
    # 제출 직후 재렌더로 1폴 동안 invisible — 소멸 확정(연속 2폴) 전에 복귀하면 재시도 없이
    # 같은 팝업에서 결과를 수락한다.
    _instant_sleep(monkeypatch)
    page = _PopupPage([_READY, _GONE, _READY])
    out = await steps_mod.open_and_search_once(page, "ZJ90-130")
    assert out["ok"] is True and out["attempt"] == 1
    assert page.clicks == 1 and page.submits == 1


@pytest.mark.asyncio
async def test_search_reopens_after_confirmed_vanish(monkeypatch):
    # 연속 2폴 '없음' = 소멸 확정 → 재오픈 재시도(attempt 2)로 회복한다.
    _instant_sleep(monkeypatch)
    page = _PopupPage(
        [_READY, _GONE, _GONE, _READY],
        grids=[_PRESEARCH_GRID, _PRESEARCH_GRID, _RESULT_GRID],  # 시도별 사전 스냅샷 2회.
    )
    out = await steps_mod.open_and_search_once(page, "ZJ90-130")
    assert out["ok"] is True and out["attempt"] == 2
    assert page.clicks == 2 and page.submits == 2


@pytest.mark.asyncio
async def test_search_uses_presearch_when_prefill_equals_keyword(monkeypatch):
    # 2026-08-28 라이브 실측: 프리필과 같은 검색어를 다시 제출하면 ERP 가 팝업을 스스로 닫아
    # (재시도 상한) 실패했다. 프리필 == 검색어면 타이핑·제출 없이 사전검색 결과를 수락한다.
    _instant_sleep(monkeypatch)
    presearch = {"ok": True, "rowCount": 1, "rows": [{"PJT_NO": "ETRI-001", "PJT_NM": "ETRIBE ERP TEST 001"}]}
    page = _PopupPage([_READY], grids=[presearch], prefill="ETRIBE ERP TEST 001")
    out = await steps_mod.open_and_search_once(page, "ETRIBE ERP TEST 001")
    assert out["ok"] is True and out.get("prefilled") is True
    assert out["rows"][0]["PJT_NO"] == "ETRI-001"
    assert page.keyword_sets == 0 and page.submits == 0 and page.clicks == 1


@pytest.mark.asyncio
async def test_search_prefill_path_waits_for_late_presearch_rows(monkeypatch):
    # ready 시점에 사전검색 응답 미도착(rowCount=0) → 뒤늦게 도착한 행이 정착하면 수락.
    _instant_sleep(monkeypatch)
    empty = {"ok": True, "rowCount": 0, "rows": []}
    presearch = {"ok": True, "rowCount": 1, "rows": [{"PJT_NO": "ETRI-001", "PJT_NM": "ETRIBE ERP TEST 001"}]}
    page = _PopupPage([_READY], grids=[empty, empty, presearch, presearch], prefill="ETRIBE ERP TEST 001")
    out = await steps_mod.open_and_search_once(page, "ETRIBE ERP TEST 001")
    assert out["ok"] is True and out["rows"][0]["PJT_NO"] == "ETRI-001"
    assert page.submits == 0


@pytest.mark.asyncio
async def test_search_still_submits_when_prefill_differs(monkeypatch):
    # 프리필이 다른 프로젝트면 종전 경로(실타이핑 + untrusted 제출) 그대로.
    _instant_sleep(monkeypatch)
    page = _PopupPage([_READY], prefill="MISC-ESR3 #2")
    out = await steps_mod.open_and_search_once(page, "ZJ90-130")
    assert out["ok"] is True and "prefilled" not in out
    assert page.keyword_sets == 1 and page.submits == 1


@pytest.mark.asyncio
async def test_search_never_opens_fails_after_full_wait(monkeypatch):
    # 도움창이 끝내 준비되지 않으면 실패하되, 각 시도에서 열림 상한까지 폴링한다 — 라이브
    # 회귀(즉시 실패·즉시 HITL 폴백) 방어. 검색어 주입·제출도 없어야 한다.
    _instant_sleep(monkeypatch)
    page = _PopupPage([_GONE])
    out = await steps_mod.open_and_search_once(page, "ZJ90-130")
    # 사유 문구는 '소멸'로 단정하지 않는다 — 실패 모드가 미준비·미제출까지 넓어졌다.
    assert out["ok"] is False and "재시도 상한" in out["reason"]
    assert page.keyword_sets == 0 and page.submits == 0 and page.clicks == 2
    # POPUP_OPEN_CAP_MS(5s)/POLL_MS(300ms) ≈ 시도당 17+폴 × 2회 시도.
    assert page.popup_polls >= 30


# ── 실행 전 폼 params 파싱 ────────────────────────────────────────────────────
def test_purchase_order_params_reads_nested_and_flat():
    from app.agents.purchase_order.params import parse_purchase_order_params

    nested = parse_purchase_order_params(_PRESELECT)
    flat = parse_purchase_order_params(_PRESELECT["purchase_order"])
    assert nested.project_no == flat.project_no == "2297"
    assert nested.has_preselection and flat.has_preselection


def test_purchase_order_params_derives_keyword_from_name_comma_prefix():
    # 폼이 keyword 를 안 주면 프로젝트명의 콤마 앞 토큰으로 유도한다(도움창 검증 경로).
    from app.agents.purchase_order.params import parse_purchase_order_params

    p = parse_purchase_order_params(
        {"purchase_order": {"project_no": "2297", "project_name": "CX85-137, 12CH PROCESS"}}
    )
    assert p.keyword == "CX85-137" and p.has_preselection


def test_purchase_order_params_sanitizes_hash_keyword():
    """⚠ 회귀(라이브 5연속 실패 2026-08-14): '#' 포함 검색은 도움창 팝업을 죽인다(프로브
    실측 — 'MISC-ESR3 #2' 소멸, 'MISC-ESR3' 4건 생존). 지정/유도 모두 '#' 앞에서 자른다."""
    from app.agents.purchase_order.params import parse_purchase_order_params

    # 폼이 keyword 를 명시해도 정화한다(13:40 라이브 payload 재현).
    p = parse_purchase_order_params(
        {"purchase_order": {"project_no": "2013", "project_name": "MISC-ESR3 #2",
                            "keyword": "MISC-ESR3 #2"}}
    )
    assert p.keyword == "MISC-ESR3" and p.has_preselection
    # 이름 유도 경로도 동일.
    p2 = parse_purchase_order_params(
        {"purchase_order": {"project_no": "2013", "project_name": "MISC-ESR3 #2"}}
    )
    assert p2.keyword == "MISC-ESR3"


def test_purchase_order_params_keyword_only_is_enough():
    # 직접 입력 폼의 번호 생략 경로 — 검색어만으로 사전 선택 성립(단일 결과 자동 특정).
    from app.agents.purchase_order.params import parse_purchase_order_params

    p = parse_purchase_order_params({"purchase_order": {"keyword": "MISC-ESR3"}})
    assert p.has_preselection and p.project_no is None


def test_purchase_order_params_absent_means_no_preselection():
    from app.agents.purchase_order.params import parse_purchase_order_params

    for raw in (None, {}, {"purchase_order": {}}, {"purchase_order": {"project_no": "  "}}):
        assert parse_purchase_order_params(raw).has_preselection is False


# ── read_bom 노드 ─────────────────────────────────────────────────────────────
_STALE_SIG = {"count": 410, "mvY": 56}  # 무필터 시그니처 — 체크박스 프로브 실측(CX85-137).


def _patch_read(monkeypatch, *, rows=None, checkbox_ok=True, bom_rows=8):
    calls: dict = {"checkbox": [], "lookup": 0, "signature": 0}

    async def _set_checkbox(page, label, want):
        calls["checkbox"].append((label, want))
        return {"ok": checkbox_ok, "reason": None if checkbox_ok else "체크박스 미발견"}

    async def _lookup(page):
        calls["lookup"] += 1
        return {"ok": True, "via": "button"}

    async def _signature(page):
        calls["signature"] += 1
        return dict(_STALE_SIG)

    async def _wait_filtered(page, prev, **kw):
        calls["wait_prev"] = prev
        return bom_rows

    async def _read_rows(page, fields):
        calls["fields"] = fields
        return {"ok": True, "count": len(rows or []), "rows": list(rows or [])}

    monkeypatch.setattr(steps_mod, "set_checkbox", _set_checkbox)
    monkeypatch.setattr(steps_mod, "click_lookup", _lookup)
    monkeypatch.setattr(steps_mod, "read_bom_signature", _signature)
    monkeypatch.setattr(steps_mod, "wait_bom_filtered", _wait_filtered)
    monkeypatch.setattr(steps_mod, "read_bom_rows", _read_rows)
    return calls


@pytest.mark.asyncio
async def test_read_bom_unchecks_move_then_reads_and_assembles(monkeypatch):
    calls = _patch_read(monkeypatch, rows=_sample_rows())
    state = {
        "events": _q(),
        "page": _Page(),
        "project": {"code": "2297", "name": "CX85-137, 12CH PROCESS"},
    }
    out = await make_read_bom_node()(state)
    assert calls["checkbox"] == [("이동요청", False)]  # 구매요청만 뷰.
    assert calls["lookup"] == 1
    # stale-grid 레이스 계약: 조회 전 시그니처를 캡처해 필터 대기에 넘긴다.
    assert calls["signature"] == 1
    assert calls["wait_prev"] == _STALE_SIG
    assert calls["fields"] == planner.READ_FIELDS
    assert out["planner_bom"]["project"]["wbs"] == "PO-2026-07-4136"
    assert out["bom_summary"]["parts"] == 3
    assert out["project"]["code"] == "2297"
    assert_keys_declared(PurchaseOrderState, out)


@pytest.mark.asyncio
async def test_read_bom_fails_when_no_set_rows_assembled(monkeypatch):
    # SET 행이 하나도 안 잡히면(레벨 매핑 드리프트) 성공으로 단정하지 않는다.
    _patch_read(monkeypatch, rows=[_grid_row(0, ITEM_CD="x"), _grid_row(2, ITEM_CD="y")])
    out = await make_read_bom_node()(
        {"events": _q(), "page": _Page(), "project": {"code": "1"}}
    )
    assert "조립하지 못했습니다" in out["error"]
    assert not out.get("no_modules")


@pytest.mark.asyncio
async def test_read_bom_ends_cleanly_when_every_set_is_done(monkeypatch):
    """SET 은 읽혔는데 전부 하위 부품이 없다 = 발주 완료 프로젝트. 실패가 아니라 조기 종료다
    (빈 계획서 HITL 로 사용자를 기다리게 하지 않는다)."""
    _patch_read(monkeypatch, rows=_shallow_rows())
    out = await make_read_bom_node()(
        {"events": _q(), "page": _Page(), "project": {"code": "2261"}}
    )
    assert "error" not in out
    assert out["no_modules"] is True
    assert "발주할 모듈이 없습니다" in out["result"]
    assert out["bom_summary"]["modules"] == 0
    assert_keys_declared(PurchaseOrderState, out)


@pytest.mark.asyncio
async def test_read_bom_fails_when_checkbox_unreachable(monkeypatch):
    _patch_read(monkeypatch, checkbox_ok=False)
    out = await make_read_bom_node()(
        {"events": _q(), "page": _Page(), "project": {"code": "1"}}
    )
    assert "체크박스" in out["error"]


# ── wait_bom_filtered — stale-grid 레이스(2026-08-13 스모크 blocker) ───────────
class _SigPage:
    """TREEGRID_MV_SIG_JS 평가마다 시그니처 시퀀스를 재생(마지막 값 반복)."""

    def __init__(self, sigs):
        self.sigs = list(sigs)
        self.calls = 0

    async def evaluate(self, script, arg=None):
        assert "MV_FG" in script  # 시그니처 JS 만 평가돼야 한다.
        self.calls += 1
        return self.sigs[min(self.calls - 1, len(self.sigs) - 1)]


_FRESH_SIG = {"count": 354, "mvY": 0}  # 구매요청만 — 체크박스 프로브 실측(CX85-137).


@pytest.mark.asyncio
async def test_wait_bom_filtered_rejects_stale_grid_until_fresh():
    # 재현: F2 후에도 직전 무필터 410행이 남아 있음(mvY 56) — rows>0 조기 수락 금지.
    page = _SigPage([_STALE_SIG, _STALE_SIG, _STALE_SIG, _FRESH_SIG, _FRESH_SIG])
    assert await steps_mod.wait_bom_filtered(page, dict(_STALE_SIG)) == 354
    assert page.calls >= 5  # stale 3폴 거부 + fresh 연속 2폴 안정 확인.


@pytest.mark.asyncio
async def test_wait_bom_filtered_distinguishes_same_rowcount_by_content():
    # 행수가 우연히 같아도 mvY(내용)로 stale 을 구별한다.
    stale = {"count": 354, "mvY": 56}
    page = _SigPage([stale, _FRESH_SIG, _FRESH_SIG])
    assert await steps_mod.wait_bom_filtered(page, dict(stale)) == 354


@pytest.mark.asyncio
async def test_wait_bom_filtered_requires_two_stable_polls():
    # 로드 도중 부분 스냅샷(mvY=0 이지만 행수 증가 중)은 단발 관찰로 수락하지 않는다.
    page = _SigPage([{"count": 120, "mvY": 0}, _FRESH_SIG, _FRESH_SIG])
    assert await steps_mod.wait_bom_filtered(page, dict(_STALE_SIG)) == 354
    assert page.calls >= 3


@pytest.mark.asyncio
async def test_wait_bom_filtered_accepts_unchanged_when_already_clean():
    # 이동요청 리프가 원래 없던 프로젝트 — 시그니처 무변화(prev 도 mvY=0)는 정상 수락.
    clean = {"count": 200, "mvY": 0}
    page = _SigPage([clean, clean])
    assert await steps_mod.wait_bom_filtered(page, dict(clean)) == 200


@pytest.mark.asyncio
async def test_wait_bom_filtered_times_out_on_persistent_stale(monkeypatch):
    # 필터가 끝내 반영되지 않으면 -1(상한 도달) — 오염 데이터로 진행하지 않는다.
    monkeypatch.setattr(steps_mod.latency, "budget_ms", lambda ms: 1)
    page = _SigPage([_STALE_SIG])
    assert await steps_mod.wait_bom_filtered(page, dict(_STALE_SIG)) == -1


# ── 트리그리드 읽기 JS — 인덱스 시프트 회귀 방지(2026-08-13 경계 프로브 실측) ─────
def test_treegrid_read_js_reads_level_and_fields_from_same_index_space():
    """레벨과 필드가 다른 행에서 오면(과거: ds.getLevel + g.getValue 혼용) 모듈이 첫 부품으로
    밀리는 시프트가 재발한다 — 소스 계약 트립와이어: 필드는 반드시 ds 로 읽는다."""
    src = js_mod.TREEGRID_READ_JS
    assert "ds.getLevel(i)" in src and "ds.getValue(i, f)" in src
    assert "g.getValue" not in src  # 그리드(view) 인덱스 혼용 금지 — 한 행 앞선 데이터.
    # ds 인덱스 0 은 숨은 루트, 데이터 행은 1..count — 0-베이스 루프는 마지막 부품을 떨군다.
    assert "let i = 1; i <= count" in src


def test_treegrid_mv_sig_js_uses_ds_index_space():
    src = js_mod.TREEGRID_MV_SIG_JS
    assert "ds.getValue(i, 'MV_FG')" in src
    assert "g.getValue" not in src
    assert "let i = 1; i <= count" in src


# ── set_checkbox — 클릭 유실 재시도(2026-08-13 wbs 프로브 실측) ────────────────
class _CheckboxPage:
    """CHECKBOX_RECT_JS 평가마다 checked 시퀀스를 재생(마지막 값 반복). None = 미발견."""

    def __init__(self, checked_seq):
        self.seq = list(checked_seq)
        self.evals = 0
        self.clicks = 0
        self.mouse = self

    async def evaluate(self, script, arg=None):
        v = self.seq[min(self.evals, len(self.seq) - 1)]
        self.evals += 1
        if v is None:
            return None
        return {"x": 10, "y": 10, "checked": v, "id": "s_move_chk"}

    async def click(self, x, y):
        self.clicks += 1


@pytest.mark.asyncio
async def test_set_checkbox_retries_lost_click_then_succeeds():
    # 재현: F2 직후 첫 클릭이 유실돼 상태가 그대로(True) — 재클릭으로 해제에 도달해야 한다.
    page = _CheckboxPage([True, True, False])
    out = await steps_mod.set_checkbox(page, "이동요청", False)
    assert out["ok"] is True and out.get("unchanged") is None
    assert page.clicks == 2  # 유실 1회 + 성공 1회.


@pytest.mark.asyncio
async def test_set_checkbox_fails_after_retry_cap():
    page = _CheckboxPage([True])  # 끝내 안 바뀜.
    out = await steps_mod.set_checkbox(page, "이동요청", False)
    assert out["ok"] is False and "해제하지 못했습니다" in out["reason"]
    assert page.clicks == steps_mod.CHECKBOX_RETRIES


@pytest.mark.asyncio
async def test_set_checkbox_unchanged_short_circuits_without_click():
    page = _CheckboxPage([False])
    out = await steps_mod.set_checkbox(page, "이동요청", False)
    assert out == {"ok": True, "unchanged": True, "id": "s_move_chk"}
    assert page.clicks == 0


# ── plan 노드(검증 위반 재방출 → 유효 제출 수락) ────────────────────────────────
async def _next_hitl(events: asyncio.Queue, *, tries: int = 200) -> dict:
    """events 큐에서 다음 hitl 프레임을 꺼낸다(로그/스텝 프레임은 통과)."""
    for _ in range(tries):
        ev = await asyncio.wait_for(events.get(), timeout=5)
        if "hitl" in ev:
            return ev["hitl"]
    raise AssertionError("hitl 프레임이 방출되지 않았습니다")


@pytest.mark.asyncio
async def test_plan_node_reemits_on_invalid_then_accepts_valid(monkeypatch):
    events = _q()
    planner_bom = planner.assemble_planner_bom(
        _sample_rows(), {"code": "2297", "name": "CX85-137"}
    )
    state = {
        "events": events,
        "page": _Page(),
        "planner_bom": planner_bom,
        "owner": "owner-1",
        "run_id": "run-1",
        "project": {"code": "2297", "name": "CX85-137", "wbs": "PO-1"},
        "bom_summary": {"modules": 1},
    }
    # 확정 계획서 보관 호출 검증 — 수락된 계획만, 상태의 owner/run_id/project/bom_summary 와 함께.
    recorded: list[dict] = []

    async def _fake_record(owner, **kw):
        recorded.append({"owner": owner, **kw})

    monkeypatch.setattr(plan_mod.purchase_order_plans, "record_plan", _fake_record)
    task = asyncio.create_task(make_plan_node()(state))

    frame = await _next_hitl(events)
    assert frame["kind"] == "planner" and frame["title"] == "발주 계획서 작성"
    assert frame["plannerBom"] == planner_bom  # 데모 픽스처 동일 shape 그대로 싣는다.
    assert "notice" not in frame  # 첫 진입엔 재개입 공지 없음(와이어 계약).

    # 위반 제출(구매사유 없음) → 프레임 재방출(notice 에 사유 — 카드가 렌더하는 계약 키).
    bad = _plan()
    bad["units"][0]["purchaseReason"] = ""
    resolve_hitl(frame["id"], {"plan": bad, "query": None, "value": None})
    frame2 = await _next_hitl(events)
    assert frame2["id"] == frame["id"] and "구매사유" in frame2["notice"]
    assert frame2["plannerBom"] == planner_bom

    # 유효 제출 → 수락.
    good = _plan()
    resolve_hitl(frame["id"], {"plan": good, "query": None, "value": None})
    out = await asyncio.wait_for(task, timeout=5)
    assert out["confirmed_plan"] == good
    assert_keys_declared(PurchaseOrderState, out)
    assert frame["id"] not in _hitl_queues
    # 위반 제출은 보관하지 않고, 수락된 계획 1건만 보관한다.
    assert recorded == [
        {
            "owner": "owner-1",
            "run_id": "run-1",
            "agent_id": "purchase-order",
            "plan": good,
            "project": state["project"],
            "bom_summary": {"modules": 1},
        }
    ]


@pytest.mark.asyncio
async def test_plan_node_survives_record_plan_failure(monkeypatch):
    events = _q()
    planner_bom = planner.assemble_planner_bom(
        _sample_rows(), {"code": "2297", "name": "CX85-137"}
    )
    state = {"events": events, "page": _Page(), "planner_bom": planner_bom,
             "owner": "owner-1", "run_id": "run-1"}

    async def _boom(owner, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(plan_mod.purchase_order_plans, "record_plan", _boom)
    task = asyncio.create_task(make_plan_node()(state))
    frame = await _next_hitl(events)
    good = _plan()
    resolve_hitl(frame["id"], {"plan": good, "query": None, "value": None})
    out = await asyncio.wait_for(task, timeout=5)
    assert out["confirmed_plan"] == good  # 보관 실패는 런을 깨지 않는다.


@pytest.mark.asyncio
async def test_plan_node_uses_extended_timeout():
    assert plan_mod.PLAN_TIMEOUT_S == 1800  # 계획 작성 상한(config 기본 600 오버라이드).


@pytest.mark.asyncio
async def test_plan_node_without_bom_short_circuits():
    out = await make_plan_node()({"events": _q(), "page": _Page()})
    assert "BOM" in out["error"]


# ── report 노드 ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_report_returns_plan_project_summary_and_no_write_notice():
    events = _q()
    out = await make_report_node()(
        {
            "events": events,
            "page": _Page(),
            "confirmed_plan": _plan(),
            "project": {"code": "2297", "name": "CX85-137", "wbs": "PO-2026-07-4136"},
            "bom_summary": {"gridRows": 8, "machines": 1, "modules": 2, "parts": 3,
                            "purchasableParts": 2},
        }
    )
    assert set(out["result"]) == {
        "plan", "project", "bomSummary", "moveRequestNo", "purchaseRequests", "submitted",
    }
    assert out["result"]["plan"]["units"][0]["seq"] == 1
    logs = [f["log"] for f in _frames(events) if "log" in f]
    assert any("화면 ③" in m for m in logs)  # handoff 성격 명시(구매발주일괄입력은 수동).
    assert_keys_declared(PurchaseOrderState, out)


# ── HitlDecision.plan 왕복(/runs/hitl → 채널 payload) ─────────────────────────
@pytest.mark.asyncio
async def test_hitl_plan_payload_reaches_channel(client, make_user, auth_as):
    """plan 필드가 Pydantic(PlanIn)을 통과해 payload dict 에 **동시** 실려 큐까지 도달한다 —
    모델에만 있고 payload 에 빠지면 조용히 유실(2026-07-05 grid 회귀 선례)."""
    uid = await make_user("po-planner", "user")
    auth_as(uid)
    q: asyncio.Queue = asyncio.Queue()
    _hitl_queues["dec-po-plan"] = q
    set_hitl_owner("dec-po-plan", str(uid))
    try:
        r = await client.post(
            "/runs/hitl",
            json={"decisionId": "dec-po-plan", "plan": _plan()},
        )
        assert r.json() == {"ok": True}
        payload = q.get_nowait()
        plan = payload["plan"]
        assert plan["project"]["code"] == "2297"
        assert plan["wbs"] == "PO-2026-07-4136"
        unit = plan["units"][0]
        assert unit["purchaseReason"].startswith("CX85-137")
        assert unit["modules"][0]["itemCode"] == "SET-001"
        assert unit["vendorGroups"][0] == {
            "vendorClass": "가공품", "vendor": "해룡", "parts": 3, "amount": 692000,
            "dueDate": "2026-09-01", "note": "",
        }
        # 검증 로직까지 왕복 확인 — 경계 통과분이 그대로 valid.
        ok, reason = planner.validate_plan(plan)
        assert ok is True, reason
    finally:
        _hitl_queues.pop("dec-po-plan", None)


@pytest.mark.asyncio
async def test_hitl_plan_rejects_oversized_units(client, make_user, auth_as):
    uid = await make_user("po-cap", "user")
    auth_as(uid)
    p = _plan()
    p["units"] = [dict(p["units"][0], seq=i + 1) for i in range(51)]  # 상한 50 초과.
    r = await client.post("/runs/hitl", json={"decisionId": "dec-po-cap", "plan": p})
    assert r.status_code == 422


# ── 조립/등록/픽스처 lockstep ─────────────────────────────────────────────────
def test_graph_compiles_with_expected_nodes():
    graph = build_purchase_order_graph()
    assert set(GRAPH_STEP_KEYS) <= set(graph.get_graph().nodes)


def test_registered_in_workflow_registry():
    import app.agents  # noqa: F401 — import 시 register_workflow 트리거.
    from app.live.registry import get_spec

    spec = get_spec(AGENT_ID)
    assert spec is not None
    assert spec.needs_browser is True
    assert spec.delay_scale == 0.4


def test_fixture_promoted_from_placeholder():
    from app.services.agent_fixtures import AGENT_FIXTURES

    fx = next((f for f in AGENT_FIXTURES if f["id"] == AGENT_ID), None)
    assert fx is not None
    assert fx["workflow_id"] == AGENT_ID
    assert fx["group_id"] == "purchase"
    assert fx.get("hidden") is False  # placeholder 시절과 동일 — 노출 유지.
    assert fx["description"]
    assert fx["flow_graph"] is not None
    assert "저장" in fx["handoff_note"]  # 쓰기 없음(Phase A) 안내.
    # steps 의 key 순서는 build_purchase_order_graph 노드 등록 순서와 정확히 일치해야 한다.
    assert [s["key"] for s in fx["steps"]] == GRAPH_STEP_KEYS
    # HITL = plan(계획서) + 비가역 동사 직전 확인 2종(저장·상신, 2026-08-28 쓰기 개방).
    marked = [s["key"] for s in fx["steps"] if s.get("intervention")]
    assert marked == ["plan", "confirm_write", "self_approve"]


def test_read_fields_cover_all_candidates():
    # TREEGRID_READ_JS 로 읽는 필드가 후보 전체를 덮는다 — 후보 갱신 시 자동 추종.
    for cands in planner.FIELD_CANDIDATES.values():
        for f in cands:
            assert f in planner.READ_FIELDS


# ── 계획서 제출 경계(PlanIn) 상한 — 2026-08-28 라이브 422 회귀 ──────────────────────
# CC04-155 처럼 장비 전체 모듈을 발주단위 하나로 묶으면 modules 가 100 을 넘고, 최종 구매사유
# (프로젝트명 접두 + 입력 ≤200)·비고(구매사유 + [비고]) 가 200 을 넘어 제출이 422 로 튕겼다.
def test_plan_in_accepts_large_unit_and_long_reason_note():
    from app.routers.runs import PlanIn

    reason = "ETRIBE ERP TEST 001 " + "모듈명 " * 60  # > 200자
    plan = _plan()
    unit = dict(plan["units"][0])
    unit["purchaseReason"] = reason
    unit["modules"] = [{"itemCode": f"SET-{i:03d}", "name": "외주조립", "spec": "S"} for i in range(300)]
    unit["vendorGroups"] = [{**g, "note": reason + " [직배송]"} for g in unit["vendorGroups"]]
    plan["units"] = [unit]
    parsed = PlanIn.model_validate(plan)
    assert len(parsed.units[0].modules) == 300
    assert parsed.units[0].purchaseReason == reason
    assert parsed.units[0].vendorGroups[0].note.endswith("[직배송]")
