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

    async def _rq(page, **kw):
        calls.append("run_query")
        return {"ok": True, "rowcount": 999}

    async def _rkey(page, i):
        return None  # 모호(soft) — 키 대조는 전용 스텁(_patch_shifting_grid)에서만 검증한다.

    monkeypatch.setattr(ab_mod.steps, "read_row_key", _rkey)
    monkeypatch.setattr(ab_mod.steps, "uncheck_all_rows", _uncheck)
    monkeypatch.setattr(ab_mod.steps, "check_row", _check)
    monkeypatch.setattr(ab_mod.steps, "checked_row_indexes", _checked_rows)
    monkeypatch.setattr(ab_mod.steps, "open_approval", _open)
    monkeypatch.setattr(ab_mod.steps, "poll_child_ready", _ready)
    monkeypatch.setattr(ab_mod.steps, "read_child_docu_no", _docu)
    monkeypatch.setattr(ab_mod.steps, "close_child", _close)
    monkeypatch.setattr(ab_mod.steps, "settle_parent_after_child_close", _settle)
    monkeypatch.setattr(ab_mod.steps, "run_query", _rq)
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
    # 게이트 닫힘(가상 상신) — 행이 사라지지 않으므로 재조회를 하지 않는다(종전 동작 보존).
    assert "run_query" not in calls


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


async def test_batch_submit_gate_defaults_off_no_archive_path():
    # ⚠ 안전(정적, 정책 전환 2026-08-07): 상신 실클릭은 allow_submit 게이트(기본 False) 뒤
    # steps.click_child_submit 경유뿐 — 노드가 child 를 직접 클릭하거나 보관/F7 을 만지지 않는다.
    import inspect

    assert inspect.signature(make_batch_approvals_node).parameters["allow_submit"].default is False
    src = inspect.getsource(ab_mod)
    assert "click_child_submit" in src  # 게이트 뒤 단일 상신 경로(steps 경유).
    assert "child.mouse" not in src and "child.click" not in src
    for forbidden in ("click_archive", "BTN_SAVE"):
        assert forbidden not in src


async def test_batch_allow_submit_one_click_per_group(monkeypatch):
    calls = _patch_steps(monkeypatch)
    submits: list = []

    async def _submit(child, **kw):
        submits.append(child)
        return {"ok": True}

    monkeypatch.setattr(ab_mod.steps, "click_child_submit", _submit)
    q = _q()
    out = await make_batch_approvals_node(allow_submit=True)(_state(_PLAN, q))
    assert out["processed"] == 3 and len(submits) == 2  # 그룹 2개 → 상신 클릭 2회(묶음 1회=N건).
    assert "전자결재 상신 완료" in out["result"]
    # 그룹 상신 성공 후(마지막 그룹 제외) 재조회로 그리드를 갱신한다.
    assert calls.count("run_query") == 1
    logs = _logs(_drain(q))
    assert any("상신 완료" in m for m in logs)
    assert not any("가상 상신" in m for m in logs)


async def test_batch_allow_submit_debug_mode_forces_virtual(monkeypatch):
    # 디버그 모드(2026-08-10): allow_submit=True 여도 debug_mode 면 상신 미클릭 + 재조회 없음.
    calls = _patch_steps(monkeypatch)
    submits: list = []

    async def _submit(child, **kw):
        submits.append(child)
        return {"ok": True}

    monkeypatch.setattr(ab_mod.steps, "click_child_submit", _submit)
    q = _q()
    st = _state(_PLAN, q)
    st["debug_mode"] = True
    out = await make_batch_approvals_node(allow_submit=True)(st)
    assert out["processed"] == 3 and submits == []
    assert "run_query" not in calls  # 행이 남으므로 재조회 없음(종전 경로 보존).
    assert "실제 상신 없음" in out["result"]
    assert any("디버그 모드" in m for m in _logs(_drain(q)))


def _patch_shifting_grid(monkeypatch, rows: list[str], *, shrink_on_submit: bool):
    """상신 후 행 소멸을 모사하는 스텁 세트 — checked_at_open(오픈 시점 체크 인덱스) 반환."""
    state: dict = {"checked": []}
    checked_at_open: list[list[int]] = []

    async def _uncheck(page):
        state["checked"] = []
        return True

    async def _check(page, i):
        state["checked"].append(i)
        return True

    async def _checked_rows(page):
        return {"ok": True, "rows": list(state["checked"])}

    async def _key(page, i):
        return rows[i] if 0 <= i < len(rows) else None

    async def _open(page, **kw):
        checked_at_open.append(sorted(state["checked"]))
        c = _Child()
        c.docu = [rows[i] for i in state["checked"] if 0 <= i < len(rows)]
        return c

    async def _ready(child, **kw):
        return [{"text": "상신"}]

    async def _docu(child):
        return list(getattr(child, "docu", []))

    async def _close(child):
        return None

    async def _settle(page, child):
        return None

    async def _submit(child, **kw):
        if shrink_on_submit:  # 상신 성공 → 체크된 행들이 리스트에서 사라진다.
            for i in sorted(state["checked"], reverse=True):
                rows.pop(i)
        return {"ok": True}

    async def _rq(page, **kw):
        return {"ok": True, "rowcount": len(rows)}

    for name, fn in [
        ("uncheck_all_rows", _uncheck),
        ("check_row", _check),
        ("checked_row_indexes", _checked_rows),
        ("read_row_key", _key),
        ("open_approval", _open),
        ("poll_child_ready", _ready),
        ("read_child_docu_no", _docu),
        ("close_child", _close),
        ("settle_parent_after_child_close", _settle),
        ("click_child_submit", _submit),
        ("run_query", _rq),
    ]:
        monkeypatch.setattr(ab_mod.steps, name, fn)
    return checked_at_open


_SHIFT_PLAN = [
    {"kind": "solo", "indexes": [0], "docu_nos": ["FI-A"], "total": 250},
    {"kind": "batch", "indexes": [1, 2], "docu_nos": ["FI-B", "FI-C"], "total": 12},
]


async def test_batch_allow_submit_remaps_group_indexes_after_rows_disappear(monkeypatch):
    # 그룹 상신 후 행이 사라진다(2026-08-07 사용자 리포트) — 다음 그룹이 재매핑된 인덱스로
    # 정확한 행을 체크하는지 검증. 재매핑이 없으면 그룹2 가 [1,2]를 체크해 D7/키 대조에 걸린다.
    rows = ["FI-A", "FI-B", "FI-C"]
    checked_at_open = _patch_shifting_grid(monkeypatch, rows, shrink_on_submit=True)
    q = _q()
    out = await make_batch_approvals_node(allow_submit=True)(
        {"events": q, "page": _StubPage(), "master_rowcount": 3, "approval_plan": _SHIFT_PLAN}
    )
    assert "error" not in out and out["processed"] == 3
    # 그룹1 은 원 인덱스 [0], 그룹2 는 행이 1 줄어든 뒤라 [1,2] → [0,1] 로 재매핑돼야 한다.
    assert checked_at_open == [[0], [0, 1]]
    assert rows == []  # 전량 상신되어 리스트가 비었다.
    assert any("인덱스 재매핑" in m for m in _logs(_drain(q)))


async def test_batch_allow_submit_key_mismatch_hard_stops(monkeypatch):
    # 그리드가 기대만큼 줄지 않으면(비정상) 재매핑 위치의 행 키가 예상과 달라진다 —
    # 확정 불일치로 즉시 중단해야 한다(엉뚱한 전표 묶음 상신 방지).
    rows = ["FI-A", "FI-B", "FI-C"]  # ⚠ 상신해도 줄지 않는 그리드.
    _patch_shifting_grid(monkeypatch, rows, shrink_on_submit=False)
    out = await make_batch_approvals_node(allow_submit=True)(
        {"events": _q(), "page": _StubPage(), "master_rowcount": 3, "approval_plan": _SHIFT_PLAN}
    )
    assert "행 재확인 실패" in out["error"]
    assert out["processed"] == 1  # 그룹1(FI-A)까지만 — 그룹2 는 진입 전에 중단.


async def test_batch_allow_submit_skips_key_check_when_keys_misaligned(monkeypatch):
    # 리뷰 확정 버그 회귀(2026-08-07): docu_nos 는 planning 때 못 읽은 키가 필터로 빠진
    # 리스트라 indexes 보다 짧을 수 있다 — 위치 정렬이 어긋난 채 대조하면 **정상 그리드**를
    # "행 재확인 실패"로 오판해 하드 중단한다. 길이 불일치면 키 대조를 생략(soft)해야 한다.
    rows = ["FI-A", "FI-B", "FI-C", "FI-D"]  # 런타임엔 FI-C 도 정상 존재/읽힘.
    plan = [
        {"kind": "solo", "indexes": [0], "docu_nos": ["FI-A"], "total": 250},
        # planning 때 2번 행(FI-C) 키 읽기만 일시 실패 → docu_nos 가 한 칸 짧다.
        {"kind": "batch", "indexes": [1, 2, 3], "docu_nos": ["FI-B", "FI-D"], "total": 12},
    ]
    checked_at_open = _patch_shifting_grid(monkeypatch, rows, shrink_on_submit=True)

    async def _docu_partial(child):
        # D7-2 는 부분 표시(계획 키 일부만 보임)면 soft — 계획 밖 혼입만 하드다. 키 미독 행
        # (FI-C)이 자식창에 보이면 '혼입'으로 잡히는 건 별개의 기존 갭이라 여기선 배제한다.
        return [d for d in getattr(child, "docu", []) if d in ("FI-A", "FI-B", "FI-D")]

    monkeypatch.setattr(ab_mod.steps, "read_child_docu_no", _docu_partial)
    q = _q()
    out = await make_batch_approvals_node(allow_submit=True)(
        {"events": q, "page": _StubPage(), "master_rowcount": 4, "approval_plan": plan}
    )
    # 오판 하드 중단이 없어야 한다 — 그룹2 는 재매핑([1,2,3]→[0,1,2])으로 정확히 체크되고 완주.
    assert "error" not in out
    assert checked_at_open == [[0], [0, 1, 2]]
    logs = _logs(_drain(q))
    assert any("행 키 대조 생략" in m for m in logs)
    assert not any("행 재확인 실패" in m for m in logs)


async def test_batch_allow_submit_failure_hard_stops(monkeypatch):
    calls = _patch_steps(monkeypatch)

    async def _submit(child, **kw):
        return {"ok": False, "reason": "결제창이 닫히지 않았습니다"}

    monkeypatch.setattr(ab_mod.steps, "click_child_submit", _submit)
    out = await make_batch_approvals_node(allow_submit=True)(_state(_PLAN, _q()))
    assert "상신 실패" in out["error"] and out["processed"] == 0
    assert "close_child" in calls  # 실패해도 결제창은 닫는다.


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


# ── count_details 메뉴 필터(2026-08-20 유형별 병합) ────────────────────────────
def _patch_menus(monkeypatch, menus: list[str]):
    async def _read(page, n):
        return {
            "ok": True,
            "rows": [{"idx": i, "menu": m, "docu_no": f"FI-{i}"} for i, m in enumerate(menus)],
        }

    monkeypatch.setattr(cd_mod.steps, "read_master_menus", _read)


async def test_count_details_menu_filter_excludes_rows_from_plan(monkeypatch):
    """필터 밖 메뉴의 행은 행별 순회·targets·approval_plan 에 아예 들어가지 않는다.
    제외 행은 그리드에 남으므로 포함 행의 **원 인덱스**가 계획에 그대로 쓰인다."""
    _patch_counts(monkeypatch, [3, 3, 3, 3])
    _patch_menus(monkeypatch, ["매출등록", "수출비용입력[나인벨]", "매출취소", "매출등록"])
    detail_reads: list[int] = []

    async def _detail(page, idx, docu_no=None):
        detail_reads.append(idx)
        return {"ok": True, "count": 3, "verified": True}

    monkeypatch.setattr(cd_mod.steps, "read_detail_count", _detail)
    q = _q()
    out = await make_count_details_node(DETAIL_BATCH_LIMIT)(
        {
            "events": q,
            "page": _StubPage(),
            "master_rowcount": 4,
            "menu_filters": ["매출등록", "매출취소"],
        }
    )
    assert detail_reads == [0, 2, 3]  # idx 1(수출비용입력)은 행별 순회 자체를 건너뛴다.
    planned = [i for g in out["approval_plan"] for i in g["indexes"]]
    assert sorted(planned) == [0, 2, 3]
    logs = _logs(_drain(q))
    assert any("메뉴 필터(매출등록·매출취소) — 대상 4건 중 1건 제외" in m for m in logs)
    # 진행 총계는 포함 건수(3) 기준.
    assert any("대상 3건의 하위" in m for m in logs)


async def test_count_details_menu_filter_all_excluded_returns_empty_plan(monkeypatch):
    _patch_counts(monkeypatch, [3, 3])
    _patch_menus(monkeypatch, ["수출비용입력[나인벨]", "기타메뉴"])
    q = _q()
    out = await make_count_details_node(DETAIL_BATCH_LIMIT)(
        {"events": q, "page": _StubPage(), "master_rowcount": 2, "menu_filters": ["매출등록"]}
    )
    assert out == {"approval_plan": [], "detail_counts": {}}
    assert any("전 건이 제외" in m for m in _logs(_drain(q)))


async def test_count_details_menu_read_failure_hard_stops(monkeypatch):
    """일괄 메뉴 읽기 실패 = 하드 중단(실패 표면화) — 조용히 무필터로 상신하면 사용자가
    지정한 제약 밖 전표가 상신되는 사고라 error 로 단락한다."""
    _patch_counts(monkeypatch, [3, 3])

    async def _fail(page, n):
        return {"ok": False, "reason": "grid-not-ready"}

    monkeypatch.setattr(cd_mod.steps, "read_master_menus", _fail)
    out = await make_count_details_node(DETAIL_BATCH_LIMIT)(
        {"events": _q(), "page": _StubPage(), "master_rowcount": 2, "menu_filters": ["매출등록"]}
    )
    assert "메뉴 컬럼을 읽지 못해" in out["error"]
    assert_keys_declared(VoucherReceivableState, out)


async def test_count_details_menu_partial_rows_hard_stops(monkeypatch):
    """일괄 읽기가 대상 행수보다 적게 돌아오면(미확정 행 존재) 무필터 오인 방지를 위해 중단."""
    _patch_counts(monkeypatch, [3, 3, 3])
    _patch_menus(monkeypatch, ["매출등록"])  # 3행 대상인데 1행만 읽힘.
    out = await make_count_details_node(DETAIL_BATCH_LIMIT)(
        {"events": _q(), "page": _StubPage(), "master_rowcount": 3, "menu_filters": ["매출등록"]}
    )
    assert "메뉴 컬럼을 읽지 못해" in out["error"]


async def test_count_details_no_menu_filter_reads_all_rows(monkeypatch):
    """menu_filters 미지정(None/[]) = 종전 동작 그대로 — 일괄 메뉴 읽기를 호출하지 않는다."""
    _patch_counts(monkeypatch, [3, 3])
    called: list = []

    async def _read(page, n):
        called.append(n)
        return {"ok": True, "rows": []}

    monkeypatch.setattr(cd_mod.steps, "read_master_menus", _read)
    out = await make_count_details_node(DETAIL_BATCH_LIMIT)(
        {"events": _q(), "page": _StubPage(), "master_rowcount": 2, "menu_filters": []}
    )
    assert called == []
    assert sum(len(g["indexes"]) for g in out["approval_plan"]) == 2
