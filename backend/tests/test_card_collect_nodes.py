"""P3-4 card_collect 노드/스텝 순수 로직 테스트(브라우저 불필요).

- steps.compute_period: 승인일 기간 D2 10일 규칙(10일 이전=전월 전체, 이후=당월 1일~오늘).
- nodes.recommend_note / _fmt_won: 적요 추천·금액 포맷 휴리스틱.
- collect_rows 빈 리스트 경로: 0건이면 안내 채팅 + filled=0(조용히 종료 안 함).
"""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

from app.agents.card_collect import nodes as cc_nodes
from app.agents.card_collect import steps
from app.agents.card_collect.nodes import _fmt_won, make_collect_rows_node, recommend_note


@pytest.fixture(autouse=True)
def _stub_recommend(monkeypatch):
    """collect_rows 의 AI 추천을 오프라인 기본값(빈 추천)으로 고정 — 실 Gemini 호출 차단.

    추천 전용 검증은 test_card_collect_recommend.py 에서 별도로 한다. 여기선 기존 그리드
    프레임/제출 로직만 봐야 하므로 추천은 {}(전부 기본지정 폴백 경로) 로 둔다.
    """

    async def _none(*args, **kwargs):
        return {}

    monkeypatch.setattr(cc_nodes, "recommend_selections", _none)


# ── compute_period(D2 10일 규칙) ──────────────────────────────────────────────
def test_compute_period_before_cutoff_is_previous_month():
    # 7월 3일(10일 이전) → 전월(6월) 전체.
    assert steps.compute_period(date(2026, 7, 3)) == ("2026-06-01", "2026-06-30")


def test_compute_period_on_or_after_cutoff_is_current_month_to_today():
    # 7월 15일(10일 이후) → 당월 1일~오늘.
    assert steps.compute_period(date(2026, 7, 15)) == ("2026-07-01", "2026-07-15")


def test_compute_period_january_rolls_to_previous_year():
    # 1월 5일 → 전년 12월 전체(연도 롤백).
    assert steps.compute_period(date(2026, 1, 5)) == ("2025-12-01", "2025-12-31")


# ── 휴리스틱 ──────────────────────────────────────────────────────────────────
def test_recommend_note_matches_keyword():
    assert recommend_note("행복푸드", "10000") == "식대(법인카드)"
    assert recommend_note("공영주차장", "3000") == "주차료(법인카드)"


def test_recommend_note_fallback_uses_merchant():
    assert recommend_note("무명상점", "1000") == "무명상점 사용"
    assert recommend_note("", "1000") == "법인카드 사용"


def test_fmt_won_formats_thousands():
    assert _fmt_won("12000") == "12,000원"
    assert _fmt_won(3500) == "3,500원"
    assert _fmt_won("N/A") == "N/A원"  # 숫자 아님 → 원문 유지


# ── collect_rows 빈 리스트 경로 ────────────────────────────────────────────────
async def test_collect_rows_empty_list_announces_and_returns_zero():
    events: asyncio.Queue = asyncio.Queue()
    node = make_collect_rows_node()
    # rows_list 없음 → gemini/page 미사용 조기 종료.
    out = await node({"events": events, "page": None, "rows_list": []})
    assert out == {"filled": 0}
    # 안내 채팅(cc-empty)이 방출됐는지 — 조용히 끝나지 않는다.
    frames = []
    while not events.empty():
        frames.append(await events.get())
    chat = [f for f in frames if isinstance(f.get("chat"), dict)]
    assert any("0건" in (c["chat"].get("content") or "") for c in chat)


# ── 그리드 HITL 흐름(kind="grid") ──────────────────────────────────────────────
from app.live.hitl import resolve_hitl  # noqa: E402


def _rows(n: int) -> list[dict]:
    """조회 노드가 넘기는 rows_list 형태의 가짜 승인내역 n건."""
    return [
        {
            "i": i,
            "FINPRODUCT_NM": f"하나법인카드-{i}",
            "TRAN_NM": f"가맹점{i}",
            "TRAN_AMT": str((i + 1) * 1000),
            "TRAN_DT": "2026-06-22",
            "TRAN_TM": "00:00:00",
            "APRVL_YN": "승인",
            "VAT_TP": "과세",
        }
        for i in range(n)
    ]


async def _next_hitl(events: asyncio.Queue, timeout: float = 2.0) -> dict:
    """events 큐를 소진하며 다음 hitl 프레임(dict)을 돌려준다."""
    while True:
        ev = await asyncio.wait_for(events.get(), timeout=timeout)
        if isinstance(ev.get("hitl"), dict):
            return ev["hitl"]


def _stub_dumps(monkeypatch, *, units=None, projects=None) -> None:
    async def _fake_units(page):
        return list(units or [])

    async def _fake_projects(page, keyword):
        return list(projects or [])

    monkeypatch.setattr(steps, "dump_budget_units", _fake_units)
    monkeypatch.setattr(steps, "dump_projects", _fake_projects)


async def test_grid_frame_emitted_with_rows_budget_units_and_favorites(monkeypatch):
    # 전사 목록 2건 중 '인사기획팀'만 사용자 부서('인사/기획팀')와 정규화 매칭 → mine 그룹.
    _stub_dumps(
        monkeypatch,
        units=[{"code": "2000", "name": "경영 본부"}, {"code": "2101", "name": "인사기획팀"}],
    )

    async def _fake_favs(owner):
        return (
            [{"code": "1000", "name": "영업본부"}],
            [{"code": "P1", "name": "공통"}],
            "인사/기획팀",
        )

    monkeypatch.setattr(cc_nodes, "_load_user_favorites", _fake_favs)

    events: asyncio.Queue = asyncio.Queue()
    state = {"events": events, "page": object(), "rows_list": _rows(2), "owner": None}
    task = asyncio.create_task(make_collect_rows_node()(state))
    frame = await _next_hitl(events)

    assert frame["kind"] == "grid"
    assert len(frame["rows"]) == 2
    assert frame["rows"][0]["merchant"] == "가맹점0"
    assert frame["rows"][0]["time"] == "00:00:00" and frame["rows"][0]["approved"] == "승인"
    assert frame["budgetUnits"]["all"] == [
        {"code": "2000", "name": "경영 본부"},
        {"code": "2101", "name": "인사기획팀"},
    ]
    # 내 부서 그룹 = 소속 '인사/기획팀' ↔ 예산단위명 '인사기획팀' 정규화 매칭.
    assert frame["budgetUnits"]["mine"] == [{"code": "2101", "name": "인사기획팀"}]
    assert frame["budgetUnits"]["favorites"] == [{"code": "1000", "name": "영업본부"}]
    assert frame["projects"]["favorites"] == [{"code": "P1", "name": "공통"}]
    assert frame["projects"]["searchResults"] is None and frame["projects"]["query"] is None

    # 전부 skip 제출로 노드를 정상 종료시킨다.
    resolve_hitl(frame["id"], {"rows": [{"no": 1, "skip": True}, {"no": 2, "skip": True}]})
    assert (await asyncio.wait_for(task, timeout=2)) == {"filled": 0, "pending_nontax": []}


async def test_grid_query_message_reemits_with_search_results(monkeypatch):
    _stub_dumps(
        monkeypatch,
        units=[],
        projects=[
            {"code": "SP1|W1", "name": "SPARES-1", "wbsNo": "W1", "wbsNm": "정비 WBS"}
        ],
    )
    events: asyncio.Queue = asyncio.Queue()
    state = {"events": events, "page": object(), "rows_list": _rows(1), "owner": None}
    task = asyncio.create_task(make_collect_rows_node()(state))
    first = await _next_hitl(events)

    resolve_hitl(first["id"], {"query": "SPARES"})
    second = await _next_hitl(events)
    assert second["id"] == first["id"]  # 같은 decision id 로 재방출
    assert second["projects"]["query"] == "SPARES"
    # 검색 결과는 WBS 필드(wbsNo/wbsNm)를 함께 싣는다(프론트 옵션 라벨·정확 반영용).
    assert second["projects"]["searchResults"] == [
        {"code": "SP1|W1", "name": "SPARES-1", "wbsNo": "W1", "wbsNm": "정비 WBS"}
    ]

    resolve_hitl(second["id"], {"rows": [{"no": 1, "skip": True}]})
    assert (await asyncio.wait_for(task, timeout=2)) == {"filled": 0, "pending_nontax": []}


async def test_grid_submit_applies_each_non_skip_row_and_records_failures(monkeypatch):
    _stub_dumps(monkeypatch, units=[])
    calls: list[int] = []

    async def _fake_apply(page, events, row, collected):
        calls.append(row)
        if row == 1:  # 2행(no=2, idx=1)만 실패로 만든다.
            return False, "예산단위 무매칭"
        return True, f"예산단위 {collected['예산단위']}"

    monkeypatch.setattr(cc_nodes, "_apply_row_fields", _fake_apply)

    events: asyncio.Queue = asyncio.Queue()
    state = {"events": events, "page": object(), "rows_list": _rows(3), "owner": None}
    task = asyncio.create_task(make_collect_rows_node()(state))
    frame = await _next_hitl(events)

    resolve_hitl(
        frame["id"],
        {
            "rows": [
                {"no": 1, "budgetUnit": {"code": "2000", "name": "경영본부"}, "note": "회식"},
                {"no": 2, "budgetUnit": {"code": "1000", "name": "영업본부"}, "note": "소모품"},
                {"no": 3, "skip": True},
            ]
        },
    )
    out = await asyncio.wait_for(task, timeout=2)
    # 전 행 과세 → 1차에서 처리, 불공 대기 없음. 1행 성공, 2행 실패, 3행 skip.
    assert out == {"filled": 1, "pending_nontax": []}
    assert calls == [0, 1]  # skip 아닌 두 행만, no 순(idx 0,1)

    frames = []
    while not events.empty():
        frames.append(events.get_nowait())
    summary = [f["chat"]["content"] for f in frames if isinstance(f.get("chat"), dict)]
    assert any("1차(법인카드·과세) 반영 1건" in c and "건너뜀 1건 · 실패 1건" in c for c in summary)
    assert any("2행: 예산단위 무매칭" in c for c in summary)


async def test_grid_invalid_submit_warns_and_reemits(monkeypatch):
    _stub_dumps(monkeypatch, units=[])
    applied: list[int] = []

    async def _fake_apply(page, events, row, collected):
        applied.append(row)
        return True, "ok"

    monkeypatch.setattr(cc_nodes, "_apply_row_fields", _fake_apply)

    events: asyncio.Queue = asyncio.Queue()
    state = {"events": events, "page": object(), "rows_list": _rows(1), "owner": None}
    task = asyncio.create_task(make_collect_rows_node()(state))
    first = await _next_hitl(events)

    # 예산단위 없는 비스킵 행 → 서버검증 실패 → 경고 + 프레임 재방출(적용 안 함).
    resolve_hitl(first["id"], {"rows": [{"no": 1, "note": "적요만"}]})
    reemit = await _next_hitl(events)
    assert reemit["id"] == first["id"]
    assert applied == []  # 무효 제출은 반영하지 않는다

    resolve_hitl(reemit["id"], {"rows": [{"no": 1, "skip": True}]})
    assert (await asyncio.wait_for(task, timeout=2)) == {"filled": 0, "pending_nontax": []}


async def test_grid_timeout_returns_error(monkeypatch):
    _stub_dumps(monkeypatch, units=[])
    events: asyncio.Queue = asyncio.Queue()
    state = {"events": events, "page": object(), "rows_list": _rows(1), "owner": None}
    out = await make_collect_rows_node(timeout_s=0.05)(state)
    assert "error" in out and "시간 초과" in out["error"]


# ── 부가세구분 2패스(과세=1차 / 그 외=2차 불공) ────────────────────────────────────
from app.agents.card_collect.nodes import (  # noqa: E402
    _row_key,
    make_apply_pass2_node,
    make_save_node,
    make_save_pass2_node,
    make_switch_evdn_node,
)


def _mixed_rows() -> list[dict]:
    """과세 1건(no=1) + 빈칸 1건(no=2) + 비과세 1건(no=3)."""
    base = _rows(3)
    base[0]["APRVL_NO"] = "A1"
    base[1]["APRVL_NO"] = "A2"
    base[1]["VAT_TP"] = ""
    base[2]["APRVL_NO"] = "A3"
    base[2]["VAT_TP"] = "비과세"
    return base


async def test_grid_submit_partitions_taxable_vs_nontax(monkeypatch):
    """과세 행만 1차 반영, 나머지는 pending_nontax(입력값+복합키) 로 보존된다."""
    _stub_dumps(monkeypatch, units=[])
    calls: list[int] = []

    async def _fake_apply(page, events, row, collected):
        calls.append(row)
        return True, "ok"

    monkeypatch.setattr(cc_nodes, "_apply_row_fields", _fake_apply)

    events: asyncio.Queue = asyncio.Queue()
    rows = _mixed_rows()
    state = {"events": events, "page": object(), "rows_list": rows, "owner": None}
    task = asyncio.create_task(make_collect_rows_node()(state))
    frame = await _next_hitl(events)
    resolve_hitl(
        frame["id"],
        {
            "rows": [
                {"no": 1, "budgetUnit": {"code": "2000", "name": "경영본부"}, "note": "회식"},
                {"no": 2, "budgetUnit": {"code": "2000", "name": "경영본부"}, "note": "소모품"},
                {"no": 3, "budgetUnit": {"code": "1000", "name": "영업본부"}, "note": "주차"},
            ]
        },
    )
    out = await asyncio.wait_for(task, timeout=2)
    assert out["filled"] == 1 and calls == [0]  # 과세(no=1)만 1차 반영
    pend = out["pending_nontax"]
    assert [p["label"] for p in pend] == [2, 3]
    assert pend[0]["key"] == _row_key(rows[1]) and pend[0]["note"] == "소모품"
    assert pend[1]["budgetUnit"]["name"] == "영업본부"


async def test_save_zero_taxable_skips_confirm_and_proceeds():
    """과세 0건 → 확인 없이 저장 생략(2차 진행 허용, save_cancelled 없음)."""
    events: asyncio.Queue = asyncio.Queue()
    out = await make_save_node()({"events": events, "page": object(), "filled": 0})
    assert "저장 생략" in out["result"] and "save_cancelled" not in out


async def test_save_cancel_sets_flag_and_switch_aborts_pass2(monkeypatch):
    """1차 저장 취소 → save_cancelled → switch_evdn 이 2차를 진행하지 않는다."""
    events: asyncio.Queue = asyncio.Queue()
    state = {
        "events": events,
        "page": object(),
        "filled": 2,
        "owner": None,
        "run_id": None,
        "pending_nontax": [{"label": 2, "key": "k", "budgetUnit": {}, "project": None, "note": "n", "merchant": "m"}],
    }
    task = asyncio.create_task(make_save_node()(state))
    hitl = await _next_hitl(events)
    resolve_hitl(hitl["id"], {"value": "cancel"})
    out = await asyncio.wait_for(task, timeout=2)
    assert out.get("save_cancelled") is True

    state.update(out)
    out2 = await make_switch_evdn_node()(state)
    assert out2 == {"pass2_work": []}


async def test_switch_evdn_matches_pending_by_composite_key(monkeypatch):
    """2차 재조회 행을 (APRVL_NO,일자,금액) 키로 매칭 — 미매칭·과세 재분류 행은 제외."""

    async def _ok_close(page):
        return {"ok": True}

    async def _ok_cards(page):
        return {"ok": True, "n": 5, "checked": 5}

    async def _ok_period(page, s, e):
        return {"ok": True}

    async def _q(page, timeout_polls=20):
        return 3

    rows2 = _mixed_rows()  # 같은 거래가 재조회됨(인덱스 동일)
    rows2[2]["i"] = 2

    async def _read(page, limit=200):
        return rows2

    monkeypatch.setattr(steps, "close_card_popup", _ok_close)
    monkeypatch.setattr(steps, "select_all_cards", _ok_cards)
    monkeypatch.setattr(steps, "set_period", _ok_period)
    monkeypatch.setattr(steps, "run_query", _q)
    monkeypatch.setattr(steps, "read_rows", _read)

    async def _noop_node(state):
        return {}

    monkeypatch.setattr(cc_nodes, "make_open_evdn_node", lambda: _noop_node)
    monkeypatch.setattr(cc_nodes, "make_select_evdn_node", lambda code="01": _noop_node)

    events: asyncio.Queue = asyncio.Queue()
    pending = [
        # rows2[1](빈칸) 매칭 성공 / 존재하지 않는 키 1건은 미매칭.
        {"label": 2, "key": _row_key(rows2[1]), "budgetUnit": {"code": "2000", "name": "경영본부"},
         "project": None, "note": "소모품", "merchant": "가맹점1"},
        {"label": 9, "key": "없음|x|y", "budgetUnit": {}, "project": None, "note": "n", "merchant": "유령"},
    ]
    state = {
        "events": events, "page": object(), "owner": None, "run_id": None,
        "pending_nontax": pending, "period": ["2026-06-01", "2026-06-30"],
    }
    out = await make_switch_evdn_node()(state)
    assert out["pass2_unmatched"] == 1
    assert [w["label"] for w in out["pass2_work"]] == [2]
    assert out["pass2_work"][0]["idx"] == rows2[1]["i"]


async def test_apply_pass2_applies_matched_work(monkeypatch):
    calls: list[int] = []

    async def _fake_apply(page, events, row, collected):
        calls.append(row)
        return True, "ok"

    monkeypatch.setattr(cc_nodes, "_apply_row_fields", _fake_apply)
    events: asyncio.Queue = asyncio.Queue()
    rows2 = _mixed_rows()
    state = {
        "events": events, "page": object(),
        "rows2_list": rows2,
        "pass2_work": [
            {"idx": 1, "label": 2, "budgetUnit": {"code": "2000", "name": "경영본부"},
             "project": None, "note": "소모품"},
        ],
    }
    out = await make_apply_pass2_node()(state)
    assert out == {"pass2_filled": 1} and calls == [1]


async def test_save_pass2_composes_final_summary_without_pass2():
    """불공 대상 0건이면 확인 없이 전체 요약 result 만 남긴다."""
    events: asyncio.Queue = asyncio.Queue()
    out = await make_save_pass2_node()(
        {"events": events, "page": object(), "filled": 3, "pass2_filled": 0}
    )
    assert "과세 3건" in out["result"] and "불공 대상 없음" in out["result"]


async def test_switch_evdn_duplicate_composite_keys_consume_distinct_rows(monkeypatch):
    """동일 복합키 2행 — 각 pending 이 서로 다른 실제 행을 1:1 소비(이중반영/누락 금지)."""

    async def _ok_close(page):
        return {"ok": True}

    async def _ok_cards(page):
        return {"ok": True}

    async def _ok_period(page, s, e):
        return {"ok": True}

    async def _q(page, timeout_polls=20):
        return 2

    # 같은 승인번호·일자·금액(복합키 충돌) 2행 — 그리드 인덱스만 다름.
    dup = {
        "APRVL_NO": "D1", "TRAN_DT": "2026-06-22", "TRAN_AMT": "1000",
        "TRAN_NM": "중복가맹", "VAT_TP": "", "FINPRODUCT_NM": "카드",
    }
    rows2 = [{**dup, "i": 0}, {**dup, "i": 1}]

    async def _read(page, limit=200):
        return rows2

    monkeypatch.setattr(steps, "close_card_popup", _ok_close)
    monkeypatch.setattr(steps, "select_all_cards", _ok_cards)
    monkeypatch.setattr(steps, "set_period", _ok_period)
    monkeypatch.setattr(steps, "run_query", _q)
    monkeypatch.setattr(steps, "read_rows", _read)

    async def _noop_node(state):
        return {}

    monkeypatch.setattr(cc_nodes, "make_open_evdn_node", lambda: _noop_node)
    monkeypatch.setattr(cc_nodes, "make_select_evdn_node", lambda code="01": _noop_node)

    key = _row_key(rows2[0])
    pending = [
        {"label": 1, "key": key, "budgetUnit": {"code": "1", "name": "a"}, "project": None, "note": "n1", "merchant": "중복가맹"},
        {"label": 2, "key": key, "budgetUnit": {"code": "2", "name": "b"}, "project": None, "note": "n2", "merchant": "중복가맹"},
        {"label": 3, "key": key, "budgetUnit": {"code": "3", "name": "c"}, "project": None, "note": "n3", "merchant": "중복가맹"},
    ]
    events: asyncio.Queue = asyncio.Queue()
    state = {
        "events": events, "page": object(), "owner": None, "run_id": None,
        "pending_nontax": pending, "period": ["2026-06-01", "2026-06-30"],
    }
    out = await cc_nodes.make_switch_evdn_node()(state)
    # 2행뿐이므로 앞선 2건이 서로 다른 idx(0,1)를 소비, 3번째는 매칭 실패.
    assert [w["idx"] for w in out["pass2_work"]] == [0, 1]
    assert out["pass2_unmatched"] == 1
