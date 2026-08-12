"""전자결재 상신 취소(eap-approval-cancel) — 목록·선택·3단계 순회 계약(브라우저 없이).

취소 3단계(결재취소·상신취소·삭제)는 **비가역**이라 규율이 세 겹이다:
  (1) 후보는 상신문서함의 '진행' 문서만,
  (2) HITL(multiselect)로 **사용자가 체크한 건만**,
  (3) 제목이 목록에서 유일하지 않으면 대상을 특정할 수 없어 **아무것도 건드리지 않고 중단**.
그리고 브라우저에 닿는 마지막 방어선으로 `steps.click_doc_button` 이 허용 목록 밖 버튼
(상신·보관)을 거부한다. 이 파일은 그 네 가지를 단위로 고정한다.
"""

from __future__ import annotations

import asyncio

import pytest

from app.agents.eap_cancel import nodes as nodes_mod
from app.agents.eap_cancel import steps as steps_mod
from app.agents.eap_cancel.graph import EapCancelState, build_eap_cancel_graph
from app.agents.eap_cancel.nodes import (
    ambiguous_titles,
    make_cancel_docs_node,
    make_list_docs_node,
)
from tests.support.state_contract import assert_keys_declared

pytestmark = pytest.mark.asyncio

AGENT_ID = "eap-approval-cancel"


def _row(title: str, status: str = "진행", approver: str = "김결재") -> dict:
    return {
        "text": f"기안일: 2026-08-11 {title} {status} ({approver})",
        "title": title,
        "date": "2026-08-11",
        "status": status,
        "approver": approver,
    }


def _q() -> asyncio.Queue:
    return asyncio.Queue()


def _frames(q: asyncio.Queue) -> list[dict]:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


class _Page:
    """노드가 만지는 page 는 전부 steps 로 위임되므로, 스크린샷만 받는 스텁이면 충분하다."""

    async def screenshot(self, **kw):
        return b""


# ── 제목 유일성 가드(순수 판정) ────────────────────────────────────────────────
async def test_ambiguous_titles_flags_duplicates_and_substrings():
    rows = [_row("출장비"), _row("출장비 정산"), _row("경조금-홍길동")]
    # '출장비' 는 '출장비 정산' 행 텍스트에도 포함된다 → 부분일치 클릭으로 특정 불가.
    assert ambiguous_titles(rows, ["출장비"]) == ["출장비"]
    # 자기 행에만 있는 제목은 유일 — 통과.
    assert ambiguous_titles(rows, ["경조금-홍길동", "출장비 정산"]) == []
    # 목록에 아예 없는 제목도 '유일하지 않음'으로 걸린다(0건 ≠ 1건).
    assert ambiguous_titles(rows, ["없는문서"]) == ["없는문서"]


# ── list_docs 노드 ────────────────────────────────────────────────────────────
def _patch_list(monkeypatch, *, rows: list[dict], values: list[str] | None = None,
                hitl_timeout: bool = False, menu_ok: bool = True):
    calls: dict = {"hitl": 0, "menu": []}

    async def _click_menu(page, leaf, group):
        calls["menu"].append(leaf)
        return menu_ok

    async def _wait_rows(page, **kw):
        return list(rows)

    async def _hitl(events, **kw):
        calls["hitl"] += 1
        calls["options"] = kw.get("options")
        calls["prompt"] = kw.get("prompt")
        if hitl_timeout:
            raise TimeoutError
        return {"values": list(values or [])}

    monkeypatch.setattr(steps_mod, "click_menu", _click_menu)
    monkeypatch.setattr(steps_mod, "wait_rows", _wait_rows)
    monkeypatch.setattr(nodes_mod, "wait_hitl", _hitl)
    return calls


async def test_list_docs_offers_only_in_progress_rows(monkeypatch):
    rows = [_row("A"), _row("B", status="종결"), _row("C")]
    calls = _patch_list(monkeypatch, rows=rows, values=["0"])
    out = await make_list_docs_node()({"events": _q(), "page": _Page()})
    assert out["picked"] == ["A"]
    # 종결 문서는 후보에서 빠진다(취소 대상이 아니다).
    assert [o["label"] for o in calls["options"]] == ["A", "C"]
    assert "복구 불가" in calls["prompt"]  # 비가역임을 개입 카드에 명시.
    assert_keys_declared(EapCancelState, out)


async def test_list_docs_without_in_progress_rows_completes_without_hitl(monkeypatch):
    calls = _patch_list(monkeypatch, rows=[_row("A", status="종결")])
    out = await make_list_docs_node()({"events": _q(), "page": _Page()})
    assert out["picked"] == [] and "'진행' 상태 문서가 없습니다" in out["result"]
    assert calls["hitl"] == 0
    assert_keys_declared(EapCancelState, out)


async def test_list_docs_empty_selection_cancels_nothing(monkeypatch):
    _patch_list(monkeypatch, rows=[_row("A"), _row("B")], values=[])
    out = await make_list_docs_node()({"events": _q(), "page": _Page()})
    assert out["picked"] == [] and "아무것도 취소하지 않았습니다" in out["result"]


async def test_list_docs_hitl_timeout_cancels_nothing(monkeypatch):
    _patch_list(monkeypatch, rows=[_row("A")], hitl_timeout=True)
    out = await make_list_docs_node()({"events": _q(), "page": _Page()})
    assert "시간 초과" in out["error"] and "아무것도 취소하지 않았습니다" in out["error"]
    assert "picked" not in out


async def test_list_docs_aborts_when_title_not_unique(monkeypatch):
    # ⚠ 핵심 안전: 제목 부분일치로 문서를 여는 구조라, 특정 불가면 하나도 진행하지 않는다.
    rows = [_row("출장비"), _row("출장비 정산")]
    _patch_list(monkeypatch, rows=rows, values=["0"])
    out = await make_list_docs_node()({"events": _q(), "page": _Page()})
    assert "특정할 수 없는" in out["error"] and "아무것도 취소하지 않았습니다" in out["error"]
    assert "picked" not in out


async def test_list_docs_fails_when_list_unreadable(monkeypatch):
    _patch_list(monkeypatch, rows=[])
    out = await make_list_docs_node()({"events": _q(), "page": _Page()})
    assert "목록을 읽지 못했습니다" in out["error"]


# ── cancel_docs 노드 ──────────────────────────────────────────────────────────
def _patch_cancel(monkeypatch, *, fail_on: tuple[str, str] | None = None,
                  residue: set[str] | None = None):
    """cancel_phase 호출을 기록한다. fail_on=(제목, 버튼) 이면 그 단계에서 실패시킨다."""
    calls: dict = {"phases": [], "menu": []}

    async def _cancel_phase(page, title, leaf, group, button):
        calls["phases"].append((title, button))
        if fail_on and (title, button) == fail_on:
            return {"ok": False, "reason": "버튼을 누르지 못했습니다"}
        return {"ok": True}

    async def _click_menu(page, leaf, group):
        calls["menu"].append(leaf)
        return True

    async def _wait_title(page, title, *, present, cap_ms=None):
        # present=False 로 '삭제 후 부재'를 확인한다 — residue 에 있으면 남아 있는 것.
        return not (residue and title in residue) if not present else True

    monkeypatch.setattr(steps_mod, "cancel_phase", _cancel_phase)
    monkeypatch.setattr(steps_mod, "click_menu", _click_menu)
    monkeypatch.setattr(steps_mod, "wait_title", _wait_title)
    return calls


async def test_cancel_docs_runs_three_phases_per_doc_in_order(monkeypatch):
    calls = _patch_cancel(monkeypatch)
    q = _q()
    out = await make_cancel_docs_node()({"events": q, "page": _Page(), "picked": ["A", "B"]})
    assert calls["phases"] == [
        ("A", "결재취소"), ("A", "상신취소"), ("A", "삭제"),
        ("B", "결재취소"), ("B", "상신취소"), ("B", "삭제"),
    ]
    assert out["cancelled"] == ["A", "B"] and "선택 2건 전부" in out["result"]
    progress = [f["progress"] for f in _frames(q) if f.get("step") == "cancel_docs" and "progress" in f]
    assert {"done": 2, "total": 2} in progress
    assert_keys_declared(EapCancelState, out)


async def test_cancel_docs_noop_without_selection(monkeypatch):
    calls = _patch_cancel(monkeypatch)
    out = await make_cancel_docs_node()({"events": _q(), "page": _Page(), "picked": []})
    assert out == {} and calls["phases"] == []


async def test_cancel_docs_aborts_on_phase_failure_and_reports_partial_state(monkeypatch):
    # A 는 결재취소까지만 되고 상신취소에서 실패 → 즉시 중단, B 는 손대지 않는다.
    calls = _patch_cancel(monkeypatch, fail_on=("A", "상신취소"))
    out = await make_cancel_docs_node()({"events": _q(), "page": _Page(), "picked": ["A", "B"]})
    assert calls["phases"] == [("A", "결재취소"), ("A", "상신취소")]
    assert "미결문서함에 있습니다" in out["error"]  # 어디에 남았는지 사유에 적는다.
    assert "나머지 문서는 손대지 않았습니다" in out["error"]
    assert out["cancelled"] == []
    assert_keys_declared(EapCancelState, out)


async def test_cancel_docs_fails_when_doc_survives_deletion(monkeypatch):
    # 삭제 3단계를 다 돌았는데 임시보관에 남아 있으면 성공으로 단정하지 않는다.
    calls = _patch_cancel(monkeypatch, residue={"A"})
    out = await make_cancel_docs_node()({"events": _q(), "page": _Page(), "picked": ["A"]})
    assert len(calls["phases"]) == 3
    assert "임시보관문서에 남아 있습니다" in out["error"] and out["cancelled"] == []


async def test_cancel_docs_keeps_completed_docs_in_error_path(monkeypatch):
    # 앞 문서는 끝났고 뒤 문서에서 실패 → 완료분은 결과에 남긴다(무엇이 사라졌는지 알 수 있게).
    _patch_cancel(monkeypatch, fail_on=("B", "결재취소"))
    out = await make_cancel_docs_node()({"events": _q(), "page": _Page(), "picked": ["A", "B"]})
    assert out["cancelled"] == ["A"] and "앞서 취소 완료: 1건" in out["error"]


# ── 마지막 방어선: 허용 버튼 목록 ──────────────────────────────────────────────
class _Popup:
    def __init__(self) -> None:
        self.clicked: list[str] = []

    def get_by_text(self, text, exact=False):  # noqa: ARG002 — 서명만 맞춘 스텁.
        self.clicked.append(text)
        return self

    def get_by_role(self, role, name=None):  # noqa: ARG002
        self.clicked.append(name)
        return self

    @property
    def first(self):
        return self

    async def click(self, **kw):
        return None


@pytest.mark.parametrize("button", ["상신", "보관", "저장"])
async def test_click_doc_button_refuses_buttons_outside_allowlist(button):
    popup = _Popup()
    r = await steps_mod.click_doc_button(popup, button)
    assert r["ok"] is False and "허용되지 않은 버튼" in r["reason"]
    assert popup.clicked == []  # 브라우저에 아예 닿지 않는다.


async def test_click_doc_button_clicks_allowed_button_then_confirm():
    popup = _Popup()
    r = await steps_mod.click_doc_button(popup, "결재취소")
    assert r["ok"] is True and popup.clicked == ["결재취소", "확인"]


async def test_allowed_buttons_are_exactly_the_cancel_four():
    assert steps_mod.ALLOWED_BUTTONS == {"결재취소", "상신취소", "삭제", "확인"}
    # 3단계가 누르는 버튼이 전부 허용 목록 안에 있어야 한다(표기 불일치 회귀 방지).
    assert {p[3] for p in steps_mod.PHASES} <= steps_mod.ALLOWED_BUTTONS


# ── 조립/등록 ─────────────────────────────────────────────────────────────────
async def test_graph_compiles():
    graph = build_eap_cancel_graph()
    assert {"login", "enter_eap", "list_docs", "cancel_docs"} <= set(graph.get_graph().nodes)


async def test_workflow_registered():
    import app.agents  # noqa: F401 — register_workflow 트리거.
    from app.live.registry import get_spec

    assert get_spec(AGENT_ID) is not None


async def test_fixture_hidden_and_wired():
    from app.services.agent_fixtures import AGENT_FIXTURES
    from app.services.agent_visibility import HIDDEN_AGENT_IDS

    fx = next(f for f in AGENT_FIXTURES if f["id"] == AGENT_ID)
    assert fx["hidden"] is True
    assert fx["workflow_id"] == AGENT_ID
    assert AGENT_ID in HIDDEN_AGENT_IDS
