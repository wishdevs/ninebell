"""테스트 문서 정리(cleanup) 워크플로우 — 가드레일·HITL 선택 삭제·잔존 확인 계약(브라우저 없이).

스모크 삭제 가드레일(본인 작성·결의구분 일치·미결)을 프로덕션 그래프로 이식한
app/agents/common/cleanup.py 의 단위 검증. 삭제(F6)는 비가역이라 (1) 3중 가드 전 행 통과,
(2) HITL(multiselect)로 **사용자가 체크한 문서만** 삭제 — 두 겹 규율이 핵심이다
(사용자 지적 2026-08-10: 가드만으론 수작업 미결 문서를 못 거른다).
"""

from __future__ import annotations

import asyncio

import pytest

from app.agents.common import cleanup as cleanup_mod
from app.agents.common.cleanup import (
    DocCleanupState,
    build_doc_cleanup_graph,
    make_cleanup_docs_node,
    row_is_ours,
)
from tests.support.state_contract import assert_keys_declared

pytestmark = pytest.mark.asyncio

_OURS = {
    "ABDOCU_NO": "TRV1",
    "ABDOCU_FG_CD": "53",
    "WRT_EMP_NM": "이트라이브2",
    "DOCU_NO": "",
    "DETAIL_SUM_AMT": "10000",
}


def _q() -> asyncio.Queue:
    return asyncio.Queue()


def _logs(q: asyncio.Queue) -> list[str]:
    out = []
    while not q.empty():
        f = q.get_nowait()
        if "log" in f:
            out.append(f["log"])
    return out


class _Page:
    """MASTER_DUMP JS 만 라우팅하는 스텁 — 나머지 스텝은 monkeypatch."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    async def evaluate(self, js_src, arg=None):
        if "ABDOCU_FG_CD" in js_src:  # MASTER_DUMP_JS
            return {"ok": True, "n": len(self.rows), "rows": list(self.rows)}
        return True

    async def screenshot(self, **kw):
        return b""


def _patch(monkeypatch, *, counts: list[int], hitl_values: list[str] | None = None,
           hitl_timeout: bool = False):
    """run_query 는 순서대로 counts 반환, HITL 은 hitl_values 선택을 응답, 체크/삭제 기록."""
    calls = {"rq": 0, "delete": 0, "uncheck": 0, "checked": [], "hitl": 0}

    async def _rq(page, **kw):
        n = counts[min(calls["rq"], len(counts) - 1)]
        calls["rq"] += 1
        return {"ok": True, "rowcount": n}

    async def _delete(page):
        calls["delete"] += 1

    async def _uncheck(page):
        calls["uncheck"] += 1
        return True

    async def _check(page, idx):
        calls["checked"].append(idx)
        return {"ok": True, "via": ["checkRow"], "checked": [idx]}

    async def _hitl(events, **kw):
        calls["hitl"] += 1
        calls["hitl_options"] = kw.get("options")
        if hitl_timeout:
            raise TimeoutError
        return {"values": list(hitl_values or [])}

    monkeypatch.setattr(cleanup_mod, "run_query", _rq)
    monkeypatch.setattr(cleanup_mod, "_delete_selected", _delete)
    monkeypatch.setattr(cleanup_mod, "uncheck_all_rows", _uncheck)
    monkeypatch.setattr(cleanup_mod, "_check_row", _check)
    monkeypatch.setattr(cleanup_mod, "wait_hitl", _hitl)
    return calls


# ── 3중 가드(row_is_ours) ─────────────────────────────────────────────────────
async def test_row_is_ours_guards_each_condition():
    assert row_is_ours(_OURS, "53", "이트라이브2") is True
    assert row_is_ours({**_OURS, "WRT_EMP_NM": "석대현"}, "53", "이트라이브2") is False  # 타인
    assert row_is_ours({**_OURS, "ABDOCU_FG_CD": "52"}, "53", "이트라이브2") is False  # 다른 구분
    assert row_is_ours({**_OURS, "DOCU_NO": "FI2026080100000001"}, "53", "이트라이브2") is False  # 상신됨


# ── cleanup_docs 노드 ─────────────────────────────────────────────────────────
async def test_cleanup_zero_rows_completes_without_delete(monkeypatch):
    calls = _patch(monkeypatch, counts=[0])
    node = make_cleanup_docs_node("53", "출장(국내·자차)")
    out = await node({"events": _q(), "page": _Page([]), "userid": "이트라이브2"})
    assert out["deleted"] == 0 and "0건" in out["result"]
    assert calls["delete"] == 0 and calls["hitl"] == 0
    assert_keys_declared(DocCleanupState, out)


async def test_cleanup_deletes_only_hitl_selected_rows(monkeypatch):
    # 후보 3건 중 사용자가 2건만 체크 → 그 2건만 체크·삭제, 잔존 1건(기대 일치)로 완료.
    calls = _patch(monkeypatch, counts=[3, 1], hitl_values=["0", "2"])
    rows = [_OURS, {**_OURS, "ABDOCU_NO": "TRV2"}, {**_OURS, "ABDOCU_NO": "TRV3"}]
    q = _q()
    node = make_cleanup_docs_node("53", "출장(국내·자차)")
    out = await node({"events": q, "page": _Page(rows), "userid": "이트라이브2"})
    assert out["deleted"] == 2 and "2건 삭제" in out["result"]
    assert calls["checked"] == [0, 2]  # 선택한 행만 체크.
    assert calls["delete"] == 1 and calls["uncheck"] >= 1
    assert len(calls["hitl_options"]) == 3  # 후보 전체가 개입 카드에 제시된다.
    assert_keys_declared(DocCleanupState, out)


async def test_cleanup_empty_selection_deletes_nothing(monkeypatch):
    calls = _patch(monkeypatch, counts=[2], hitl_values=[])
    rows = [_OURS, {**_OURS, "ABDOCU_NO": "TRV2"}]
    node = make_cleanup_docs_node("53", "출장(국내·자차)")
    out = await node({"events": _q(), "page": _Page(rows), "userid": "이트라이브2"})
    assert out["deleted"] == 0 and "삭제하지 않았습니다" in out["result"]
    assert calls["delete"] == 0 and calls["checked"] == []


async def test_cleanup_hitl_timeout_deletes_nothing(monkeypatch):
    calls = _patch(monkeypatch, counts=[1], hitl_timeout=True)
    node = make_cleanup_docs_node("53", "출장(국내·자차)")
    out = await node({"events": _q(), "page": _Page([_OURS]), "userid": "이트라이브2"})
    assert "시간 초과" in out["error"] and "삭제하지 않았습니다" in out["error"]
    assert calls["delete"] == 0


async def test_cleanup_aborts_when_any_row_not_ours(monkeypatch):
    # ⚠ 핵심 안전: 한 행이라도 가드에 어긋나면 HITL 도 띄우지 않고 중단(아무것도 삭제 안 함).
    calls = _patch(monkeypatch, counts=[2], hitl_values=["0"])
    page = _Page([_OURS, {**_OURS, "ABDOCU_NO": "REAL1", "WRT_EMP_NM": "석대현"}])
    node = make_cleanup_docs_node("53", "출장(국내·자차)")
    out = await node({"events": _q(), "page": page, "userid": "이트라이브2"})
    assert "가드레일 불일치" in out["error"] and "삭제하지 않았습니다" in out["error"]
    assert calls["hitl"] == 0 and calls["delete"] == 0


async def test_cleanup_aborts_when_submitted_doc_present(monkeypatch):
    # 상신된 문서(DOCU_NO 채번)가 섞여 있어도 전체 중단 — 실문서 보호.
    calls = _patch(monkeypatch, counts=[1], hitl_values=["0"])
    page = _Page([{**_OURS, "DOCU_NO": "FI2026080100000001"}])
    node = make_cleanup_docs_node("53", "출장(국내·자차)")
    out = await node({"events": _q(), "page": page, "userid": "이트라이브2"})
    assert "가드레일 불일치" in out["error"] and "상신됨" in out["error"]
    assert calls["delete"] == 0


async def test_cleanup_fails_when_residue_mismatch(monkeypatch):
    # 전량 선택 삭제 후에도 1건 잔존(기대 0) → 하드 실패.
    calls = _patch(monkeypatch, counts=[2, 1], hitl_values=["0", "1"])
    rows = [_OURS, {**_OURS, "ABDOCU_NO": "TRV2"}]
    node = make_cleanup_docs_node("53", "출장(국내·자차)")
    out = await node({"events": _q(), "page": _Page(rows), "userid": "이트라이브2"})
    assert "잔존 1건(기대 0건)" in out["error"]
    assert calls["delete"] == 1


async def test_cleanup_requires_userid(monkeypatch):
    calls = _patch(monkeypatch, counts=[1])
    node = make_cleanup_docs_node("53", "출장(국내·자차)")
    out = await node({"events": _q(), "page": _Page([_OURS]), "userid": ""})
    assert "로그인 계정" in out["error"]
    assert calls["rq"] == 0 and calls["delete"] == 0  # 판정 불가면 조회조차 하지 않는다.


# ── 조립/등록 (결의서 전체 확대 2026-08-10 — 5종 → 2026-08-25 세금계산서 추가 6종) ──
_CLEANUP_IDS = (
    "trip-domestic-cleanup",
    "trip-overseas-cleanup",
    "card-collect-cleanup",
    "gyeongjo-grant-cleanup",
    "hakjagum-grant-cleanup",
    "tax-invoice-cleanup",
)


async def test_cleanup_graph_compiles():
    graph = build_doc_cleanup_graph("출장(국내·자차)", "53")
    assert {"login", "user_type", "menu_nav", "set_gubun", "cleanup_docs"} <= set(
        graph.get_graph().nodes
    )


@pytest.mark.parametrize("cleanup_id", _CLEANUP_IDS)
async def test_cleanup_workflow_registered(cleanup_id):
    import app.agents  # noqa: F401 — register_workflow 트리거.
    from app.live.registry import get_spec

    assert get_spec(cleanup_id) is not None


@pytest.mark.parametrize("cleanup_id", _CLEANUP_IDS)
async def test_cleanup_fixture_hidden_and_wired(cleanup_id):
    # hidden 픽스처 — 목록/상세 비노출 대상에 포함되고, workflow_id 가 레지스트리와 일치한다.
    from app.services.agent_fixtures import AGENT_FIXTURES
    from app.services.agent_visibility import HIDDEN_AGENT_IDS

    fx = next(f for f in AGENT_FIXTURES if f["id"] == cleanup_id)
    assert fx["hidden"] is True
    assert fx["workflow_id"] == cleanup_id
    assert cleanup_id in HIDDEN_AGENT_IDS


async def test_cleanup_check_row_failure_reports_cause(monkeypatch):
    # 행 체크 실패는 원인(err)을 동봉해 하드 중단 — 삭제(F6)는 시도조차 하지 않는다.
    calls = _patch(monkeypatch, counts=[1], hitl_values=["0"])

    async def _check_fail(page, idx):
        return {"ok": False, "err": ["setCurrent:TypeError …"]}

    monkeypatch.setattr(cleanup_mod, "_check_row", _check_fail)
    node = make_cleanup_docs_node("53", "출장(국내·자차)")
    out = await node({"events": _q(), "page": _Page([_OURS]), "userid": "이트라이브2"})
    assert "checkRow" in out["error"] and "setCurrent:TypeError" in out["error"]
    assert calls["delete"] == 0
