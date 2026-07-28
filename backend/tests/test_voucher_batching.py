"""배치 결재 계획·실행 계약(외상매출금, 2026-07-27 사용자 규칙) — 브라우저 없이.

규칙: 하위(계정정보) 건수가 단독 200 이상이면 **먼저 단독 결재**, 나머지는 **합계 200 미만**이
되도록 묶어 일괄 결재. 건수를 못 읽은 행은 안전하게 단독 처리.
"""

from __future__ import annotations

import asyncio

import pytest

from app.agents.voucher_receivable.batching import (
    DETAIL_BATCH_LIMIT,
    ApprovalTarget,
    plan_approval_groups,
)
from app.agents.voucher_receivable.nodes import approvals_batch as ab_mod
from app.agents.voucher_receivable.nodes.approvals_batch import make_batch_approvals_node

pytestmark = pytest.mark.asyncio


def _t(idx: int, count: int, docu: str | None = None) -> ApprovalTarget:
    return ApprovalTarget(idx=idx, docu_no=docu or f"FI{idx:010d}", count=count)


# ── 계획(pure) ────────────────────────────────────────────────────────────────
async def test_solo_when_single_voucher_reaches_limit():
    groups = plan_approval_groups([_t(0, 250), _t(1, 3)])
    assert [g.kind for g in groups] == ["solo", "batch"]
    assert groups[0].indexes == [0] and groups[0].total == 250
    assert groups[1].indexes == [1]


async def test_solo_groups_come_first_even_when_found_later():
    # 단독 대상이 뒤쪽 행이어도 **먼저** 결재한다(사용자 규칙: 단독을 먼저 처리).
    groups = plan_approval_groups([_t(0, 5), _t(1, 200), _t(2, 7)])
    assert groups[0].kind == "solo" and groups[0].indexes == [1]
    assert [g.kind for g in groups[1:]] == ["batch"]
    assert groups[1].indexes == [0, 2]


async def test_batches_stay_strictly_under_limit():
    # 합계가 한도에 '닿으면' 안 된다(200이 안 되도록) — 199 까지만 한 묶음.
    targets = [_t(i, 100) for i in range(5)]
    groups = plan_approval_groups(targets)
    assert all(g.total < DETAIL_BATCH_LIMIT for g in groups)
    assert [g.indexes for g in groups] == [[0], [1], [2], [3], [4]]  # 100+100=200 → 불가.


async def test_batches_pack_in_query_order():
    targets = [_t(0, 60), _t(1, 60), _t(2, 60), _t(3, 60)]
    groups = plan_approval_groups(targets)
    # 60*3=180 < 200, 네 번째는 240 이 되므로 새 묶음. 조회 순서를 재정렬하지 않는다.
    assert [g.indexes for g in groups] == [[0, 1, 2], [3]]


async def test_unreadable_count_becomes_solo_not_batched():
    # 미상(-1)을 0으로 취급해 묶으면 그 묶음이 한도를 넘길 수 있다 → 단독으로 뺀다.
    groups = plan_approval_groups([_t(0, -1), _t(1, 5)])
    assert groups[0].kind == "unknown" and groups[0].indexes == [0]
    assert groups[1].kind == "batch" and groups[1].indexes == [1]


async def test_exact_limit_value_is_solo_not_batch():
    groups = plan_approval_groups([_t(0, DETAIL_BATCH_LIMIT)])
    assert [g.kind for g in groups] == ["solo"]


# ── 실행(배치 결재 노드) ───────────────────────────────────────────────────────
def _q() -> asyncio.Queue:
    return asyncio.Queue()


def _drain(q: asyncio.Queue) -> list[dict]:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _logs(frames: list[dict]) -> list[str]:
    return [f["log"] for f in frames if "log" in f]


class _StubPage:
    async def evaluate(self, js_src, arg=None):
        return True

    async def wait_for_timeout(self, ms):
        return None


class _Child:
    def __init__(self) -> None:
        self.closed = False

    async def close(self):
        self.closed = True


def _patch_steps(monkeypatch, *, plan=None, extra=(), hide=(), checked=None, calls=None):
    """steps 를 스텁으로 — 자식창은 **현재 체크된 행에 해당하는 전표**를 보여준다(실물 시맨틱).

    extra: 계획 밖 전표를 자식창에 섞는다(혼입 시나리오).
    hide:  계획된 전표 중 자식창에 안 보이는 것(대량 배치 렌더 편차 시나리오).
    checked: checked_row_indexes 가 돌려줄 행 목록 고정(D7 불일치 시나리오).
    """
    calls = calls if calls is not None else []
    plan = plan if plan is not None else _PLAN
    idx_to_docu = {i: d for g in plan for i, d in zip(g["indexes"], g["docu_nos"])}
    state = {"checked": []}

    async def _uncheck(page):
        state["checked"] = []
        calls.append("uncheck")
        return True

    async def _check(page, idx):
        state["checked"].append(idx)
        calls.append(("check", idx))
        return True

    async def _checked_rows(page):
        return {"ok": True, "rows": checked if checked is not None else list(state["checked"])}

    async def _open(page, **kw):
        calls.append("open_approval")
        c = _Child()
        # 결제창은 그 시점에 체크된 행들의 전표를 표시한다(실측: 다중 체크 → 자식창 1개에 전부).
        c.docu = [
            idx_to_docu[i] for i in state["checked"] if idx_to_docu.get(i) not in hide
        ] + list(extra)
        return c

    async def _ready(child, **kw):
        return [{"text": "상신"}]

    async def _docu(child):
        return list(getattr(child, "docu", []))

    async def _close(child):
        calls.append("close_child")

    async def _settle(page, child):
        return None

    monkeypatch.setattr(ab_mod.steps, "uncheck_all_rows", _uncheck)
    monkeypatch.setattr(ab_mod.steps, "check_row", _check)
    monkeypatch.setattr(ab_mod.steps, "checked_row_indexes", _checked_rows)
    monkeypatch.setattr(ab_mod.steps, "open_approval", _open)
    monkeypatch.setattr(ab_mod.steps, "poll_child_ready", _ready)
    monkeypatch.setattr(ab_mod.steps, "read_child_docu_no", _docu)
    monkeypatch.setattr(ab_mod.steps, "close_child", _close)
    monkeypatch.setattr(ab_mod.steps, "settle_parent_after_child_close", _settle)
    return calls


def _state(plan, q):
    return {"events": q, "page": _StubPage(), "master_rowcount": 3, "approval_plan": plan}


_PLAN = [
    {"kind": "solo", "indexes": [2], "docu_nos": ["FI-C"], "total": 250},
    {"kind": "batch", "indexes": [0, 1], "docu_nos": ["FI-A", "FI-B"], "total": 12},
]


async def test_batch_opens_one_approval_per_group(monkeypatch):
    calls = _patch_steps(monkeypatch)
    q = _q()
    out = await make_batch_approvals_node()(_state(_PLAN, q))
    assert out["processed"] == 3
    assert out["processed_docu_nos"] == ["FI-C", "FI-A", "FI-B"]
    # 그룹당 결재 1회 — 3건을 2회로 처리(건별이면 3회).
    assert calls.count("open_approval") == 2
    # 묶음은 대상 행을 함께 체크한 뒤 한 번 연다.
    assert calls.count(("check", 0)) == 1 and calls.count(("check", 1)) == 1


async def test_batch_unchecks_before_each_group(monkeypatch):
    calls = _patch_steps(monkeypatch)
    await make_batch_approvals_node()(_state(_PLAN, _q()))
    # 직전 묶음 체크가 남아 다른 문서가 함께 올라가지 않도록 매 묶음 전 전체 해제.
    assert calls.count("uncheck") == 2
    assert calls.index("uncheck") < calls.index(("check", 2))


async def test_batch_hard_fails_when_checked_rows_differ_from_plan(monkeypatch):
    _patch_steps(monkeypatch, checked=[0, 1, 2])  # 계획 밖 행까지 체크됨
    q = _q()
    out = await make_batch_approvals_node()(_state(_PLAN, q))
    assert "D7" in out["error"] and out["processed"] == 0


async def test_batch_hard_fails_when_child_shows_unplanned_voucher(monkeypatch):
    # 계획에 없는 전표가 결제창에 있으면 즉시 중단(다른 문서 혼입 — 안전 크리티컬).
    _patch_steps(monkeypatch, extra=["FI-XXX"])
    q = _q()
    out = await make_batch_approvals_node()(_state(_PLAN, q))
    assert "계획 밖" in out["error"]
    assert any("D7 정합성 오류" in m for m in _logs(_drain(q)))


async def test_batch_warns_but_proceeds_when_child_shows_only_some(monkeypatch):
    # 대량 배치는 렌더/스크롤 편차로 일부만 보일 수 있다 — 모호는 하드 실패 근거로 쓰지 않는다.
    _patch_steps(monkeypatch, hide=["FI-B"])
    q = _q()
    out = await make_batch_approvals_node()(_state(_PLAN, q))
    assert "error" not in out and out["processed"] == 3
    assert any("D7 부분 확인(soft)" in m for m in _logs(_drain(q)))


async def test_batch_never_clicks_submit_or_archive():
    # ⚠ 절대 안전(정적): 배치 노드 소스에 상신/보관 클릭 경로가 없어야 한다.
    import inspect

    src = inspect.getsource(ab_mod)
    assert "상신" in src  # 로그 문구로만 등장.
    for forbidden in ("click_submit", "click_archive", "BTN_SAVE"):
        assert forbidden not in src


async def test_batch_zero_rows_completes_without_approval(monkeypatch):
    calls = _patch_steps(monkeypatch)
    q = _q()
    out = await make_batch_approvals_node()(
        {"events": q, "page": _StubPage(), "master_rowcount": 0, "approval_plan": []}
    )
    assert out["processed"] == 0 and "대상 전표가 없어" in out["result"]
    assert "open_approval" not in calls


# ── count_details 노드(건수 파악 → 계획) ──────────────────────────────────────
from app.agents.voucher_receivable.graph import VoucherReceivableState  # noqa: E402
from app.agents.voucher_receivable.nodes import count_details as cd_mod  # noqa: E402
from app.agents.voucher_receivable.nodes.count_details import (  # noqa: E402
    make_count_details_node,
)
from tests.support.state_contract import assert_keys_declared  # noqa: E402


def _patch_counts(monkeypatch, counts: list[int], *, verified=True):
    async def _key(page, idx):
        return f"FI-{idx}"

    async def _detail(page, idx, docu_no=None):
        c = counts[idx]
        return {"ok": True, "count": c, "verified": verified and c >= 0}

    monkeypatch.setattr(cd_mod.steps, "read_row_key", _key)
    monkeypatch.setattr(cd_mod.steps, "read_detail_count", _detail)


async def test_count_details_builds_plan_and_declares_state_keys(monkeypatch):
    _patch_counts(monkeypatch, [250, 5, 7])
    q = _q()
    out = await make_count_details_node(DETAIL_BATCH_LIMIT)(
        {"events": q, "page": _StubPage(), "master_rowcount": 3}
    )
    assert out["detail_counts"] == {"FI-0": 250, "FI-1": 5, "FI-2": 7}
    assert [g["kind"] for g in out["approval_plan"]] == ["solo", "batch"]
    assert out["approval_plan"][1]["indexes"] == [1, 2]
    # ⚠ 미선언 키는 LangGraph 가 조용히 버린다 — State 선언과 lockstep.
    assert_keys_declared(VoucherReceivableState, out)
    assert any("결재 계획" in m for m in _logs(_drain(q)))


async def test_count_details_respects_max_rows(monkeypatch):
    _patch_counts(monkeypatch, [3, 3, 3, 3, 3])
    out = await make_count_details_node(DETAIL_BATCH_LIMIT)(
        {"events": _q(), "page": _StubPage(), "master_rowcount": 5, "max_rows": 2}
    )
    assert sum(len(g["indexes"]) for g in out["approval_plan"]) == 2


async def test_count_details_zero_rows_short_circuits(monkeypatch):
    _patch_counts(monkeypatch, [])
    out = await make_count_details_node(DETAIL_BATCH_LIMIT)(
        {"events": _q(), "page": _StubPage(), "master_rowcount": 0}
    )
    assert out == {"approval_plan": [], "detail_counts": {}}


async def test_count_details_unverified_row_becomes_solo_with_warning(monkeypatch):
    # 소유 확인 실패(스테일 의심) → 건수 미상(-1) → 단독 그룹 + 경고 로그.
    _patch_counts(monkeypatch, [-1, 4])
    q = _q()
    out = await make_count_details_node(DETAIL_BATCH_LIMIT)(
        {"events": q, "page": _StubPage(), "master_rowcount": 2}
    )
    assert out["approval_plan"][0]["kind"] == "unknown"
    assert any("하위 건수 확인 실패" in m for m in _logs(_drain(q)))
