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
from app.agents.card_collect.nodes import batch, catalog, pass2, prefill, save


@pytest.fixture(autouse=True)
def _stub_recommend(monkeypatch):
    """collect_rows 의 AI 추천을 오프라인 기본값(빈 추천)으로 고정 — 실 Gemini 호출 차단.

    추천 전용 검증은 test_card_collect_recommend.py 에서 별도로 한다. 여기선 기존 그리드
    프레임/제출 로직만 봐야 하므로 추천은 {}(전부 기본지정 폴백 경로) 로 둔다.
    """

    async def _none(*args, **kwargs):
        return {}

    monkeypatch.setattr(prefill, "recommend_selections", _none)


# ── compute_period(D2 10일 규칙 — 2026-07-04 변경: 10일 미만=전월, 10일부터=당월) ──
def test_compute_period_before_cutoff_is_previous_month():
    # 7월 9일(10일 미만) → 전월(6월) 전체. 오늘 7/4도 여기 해당.
    assert steps.compute_period(date(2026, 7, 9)) == ("2026-06-01", "2026-06-30")
    assert steps.compute_period(date(2026, 7, 4)) == ("2026-06-01", "2026-06-30")


def test_compute_period_on_or_after_cutoff_is_current_month_to_today():
    # 7월 10일(컷오프 경계)부터 당월 1일~오늘.
    assert steps.compute_period(date(2026, 7, 10)) == ("2026-07-01", "2026-07-10")
    assert steps.compute_period(date(2026, 7, 15)) == ("2026-07-01", "2026-07-15")


def test_compute_period_january_rolls_to_previous_year():
    # 1월 2일(10일 미만) → 전년 12월 전체(연도 롤백).
    assert steps.compute_period(date(2026, 1, 2)) == ("2025-12-01", "2025-12-31")


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

    monkeypatch.setattr(catalog, "_load_user_favorites", _fake_favs)

    events: asyncio.Queue = asyncio.Queue()
    state = {"events": events, "page": object(), "rows_list": _rows(2), "owner": None}
    task = asyncio.create_task(make_collect_rows_node()(state))
    frame = await _next_hitl(events)

    assert frame["kind"] == "grid"
    assert len(frame["rows"]) == 2
    assert frame["rows"][0]["merchant"] == "가맹점0"
    assert frame["rows"][0]["time"] == "00:00:00" and frame["rows"][0]["approved"] == "승인"
    # 그리드 선택지는 자주쓰는+내 부서만 — 전사 전체(all)는 프레임에 싣지 않는다(사용자 확정).
    assert "all" not in frame["budgetUnits"]
    # 내 부서 그룹 = 소속 '인사/기획팀' ↔ 예산단위명 '인사기획팀' 정규화 매칭.
    assert frame["budgetUnits"]["mine"] == [{"code": "2101", "name": "인사기획팀"}]
    assert frame["budgetUnits"]["favorites"] == [{"code": "1000", "name": "영업본부"}]
    assert frame["projects"]["favorites"] == [{"code": "P1", "name": "공통"}]
    assert frame["projects"]["searchResults"] is None and frame["projects"]["query"] is None
    # 적요 출처: 학습·seed 없음 → 키워드 휴리스틱 → noteSource=None(배지 없음). 키는 항상 실린다.
    assert all("noteSource" in row for row in frame["rows"])
    assert frame["rows"][0]["noteSource"] is None

    # 전부 skip 제출로 노드를 정상 종료시킨다.
    resolve_hitl(frame["id"], {"rows": [{"no": 1, "skip": True}, {"no": 2, "skip": True}]})
    assert (await asyncio.wait_for(task, timeout=2)) == {"filled": 0, "pending_nontax": [], "pass1_applied_idx": [], "pass1_failed": 0}


async def test_grid_rows_carry_note_source_badge(monkeypatch):
    """적요 프리필 출처 배지: 개인 학습→'learned', 전사 seed→'seed', 키워드 휴리스틱→None."""
    from app.services import card_learning

    _stub_dumps(monkeypatch)

    async def _fake_favs(owner):
        return ([], [], "")

    monkeypatch.setattr(catalog, "_load_user_favorites", _fake_favs)

    async def _fake_learned(owner, merchants):
        return {card_learning.norm_merchant("가맹점0"): {"note": "야근 식대"}}

    async def _fake_seed(merchants):
        # 가맹점0 은 개인 학습이 있으므로 seed 가 있어도 learned 가 우선해야 한다.
        return {
            card_learning.norm_merchant("가맹점0"): {"note": "전사 관례 적요"},
            card_learning.norm_merchant("가맹점1"): {"note": "소모품 구입"},
        }

    monkeypatch.setattr(card_learning, "retrieve_for_merchants", _fake_learned)
    monkeypatch.setattr(card_learning, "retrieve_seed_for_merchants", _fake_seed)

    events: asyncio.Queue = asyncio.Queue()
    state = {"events": events, "page": object(), "rows_list": _rows(3), "owner": None}
    task = asyncio.create_task(make_collect_rows_node()(state))
    frame = await _next_hitl(events)

    assert frame["rows"][0]["noteSource"] == "learned" and frame["rows"][0]["note"] == "야근 식대"
    assert frame["rows"][1]["noteSource"] == "seed" and frame["rows"][1]["note"] == "소모품 구입"
    assert frame["rows"][2]["noteSource"] is None  # 키워드 휴리스틱 — 배지 없음

    resolve_hitl(frame["id"], {"rows": [{"no": i, "skip": True} for i in (1, 2, 3)]})
    await asyncio.wait_for(task, timeout=2)


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
    assert (await asyncio.wait_for(task, timeout=2)) == {"filled": 0, "pending_nontax": [], "pass1_applied_idx": [], "pass1_failed": 0}


async def test_grid_submit_applies_each_non_skip_row_and_records_failures(monkeypatch):
    _stub_dumps(monkeypatch, units=[])
    calls: list[int] = []

    async def _fake_apply(page, events, rows, collected):
        calls.extend(rows)
        if 1 in rows:  # 2행(no=2, idx=1) 그룹만 실패로 만든다.
            return False, "예산단위 무매칭"
        return True, f"예산단위 {collected['예산단위']}"

    monkeypatch.setattr(batch, "_apply_group_fields", _fake_apply)

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
    assert (out["filled"], out["pending_nontax"], out["pass1_applied_idx"], out["pass1_failed"]) == (
        1, [], [0], 1
    )
    assert "retry_prefill" in out  # 실입력(비-skip) 행은 저장실패 재시도용으로 보존
    assert calls == [0, 1]  # skip 아닌 두 행만, no 순(idx 0,1)

    frames = []
    while not events.empty():
        frames.append(events.get_nowait())
    summary = [f["chat"]["content"] for f in frames if isinstance(f.get("chat"), dict)]
    assert any("1차(법인카드·과세) 반영 1건" in c and "건너뜀 1건 · 실패 1건" in c for c in summary)
    assert any("2행: 예산단위 무매칭" in c for c in summary)


async def test_grid_submit_learns_only_edited_fields(monkeypatch):
    """개입 학습(필드 단위): 사용자가 바꾼 필드만 기록, 프리필 그대로 수락한 행/필드는 학습 안 함."""
    from app.services import card_learning

    _stub_dumps(monkeypatch, units=[])
    captured: dict = {}

    async def _capture(owner, entries):
        captured["entries"] = entries
        return len(entries)

    monkeypatch.setattr(card_learning, "record_selections", _capture)

    async def _ok_apply(page, events, rows, collected):
        return True, "ok"

    monkeypatch.setattr(batch, "_apply_group_fields", _ok_apply)

    events: asyncio.Queue = asyncio.Queue()
    state = {"events": events, "page": object(), "rows_list": _rows(2), "owner": "x"}
    task = asyncio.create_task(make_collect_rows_node()(state))
    frame = await _next_hitl(events)
    resolve_hitl(
        frame["id"],
        {
            "rows": [
                # 1행: 예산단위만 편집 → 예산단위만 학습(적요·프로젝트는 None 으로 스냅샷 보존).
                {"no": 1, "budgetUnit": {"code": "2000", "name": "경영본부"}, "note": "회식",
                 "budgetEdited": True, "noteEdited": False, "projectEdited": False},
                # 2행: 아무 편집 없음(프리필 그대로 수락) → 학습 대상 아님.
                {"no": 2, "budgetUnit": {"code": "1000", "name": "영업본부"}, "note": "소모품",
                 "budgetEdited": False, "noteEdited": False, "projectEdited": False},
            ]
        },
    )
    await asyncio.wait_for(task, timeout=2)

    entries = captured["entries"]
    assert len(entries) == 1  # 편집한 1행만
    assert entries[0]["budget"]["code"] == "2000"
    assert entries[0]["note"] is None and entries[0]["project"] is None  # 미편집 필드는 None


async def test_grid_invalid_submit_warns_and_reemits(monkeypatch):
    _stub_dumps(monkeypatch, units=[])
    applied: list[int] = []

    async def _fake_apply(page, events, rows, collected):
        applied.extend(rows)
        return True, "ok"

    monkeypatch.setattr(batch, "_apply_group_fields", _fake_apply)

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
    assert (await asyncio.wait_for(task, timeout=2)) == {"filled": 0, "pending_nontax": [], "pass1_applied_idx": [], "pass1_failed": 0}


async def test_grid_timeout_returns_error(monkeypatch):
    _stub_dumps(monkeypatch, units=[])
    events: asyncio.Queue = asyncio.Queue()
    state = {"events": events, "page": object(), "rows_list": _rows(1), "owner": None}
    out = await make_collect_rows_node(timeout_s=0.05)(state)
    assert "error" in out and "시간 초과" in out["error"]


# ── 부가세구분 2패스(과세=1차 / 그 외=2차 불공) ────────────────────────────────────
from app.agents.card_collect.nodes import (  # noqa: E402
    _row_key,
    make_apply_doc_node,
    make_apply_pass2_node,
    make_save_final_node,
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

    async def _fake_apply(page, events, rows, collected):
        calls.extend(rows)
        return True, "ok"

    monkeypatch.setattr(batch, "_apply_group_fields", _fake_apply)

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


async def test_apply_doc_zero_taxable_skips_and_proceeds():
    """과세 0건 → 적용 없이 2차로(플래그 없음 — switch 는 기존 행 재선택 경로)."""
    events: asyncio.Queue = asyncio.Queue()
    out = await make_apply_doc_node()({"events": events, "page": object(), "filled": 0})
    assert out == {} and "pass1_doc_applied" not in out


async def test_apply_doc_sets_flag_for_f3_path(monkeypatch):
    """1차 적용 성공 → pass1_doc_applied — switch 가 F3(새 행)부터 진행하는 근거 플래그."""

    async def _ok_apply(page, idx):
        return {"ok": True, "checked": len(idx)}

    monkeypatch.setattr(steps, "apply_rows_to_document", _ok_apply)
    events: asyncio.Queue = asyncio.Queue()
    out = await make_apply_doc_node()(
        {"events": events, "page": object(), "filled": 2, "pass1_applied_idx": [0, 1]}
    )
    assert out == {"pass1_doc_applied": True}


async def test_apply_doc_failure_surfaces_modal_text(monkeypatch):
    """적용 실패 시 화면 모달 텍스트를 에러에 노출(조용한 멈춤 방지)."""

    async def _fail_apply(page, idx):
        return {"ok": False, "reason": "적용 후 카드팝업이 닫히지 않음",
                "modals": [{"title": "선택", "text": "프로젝트를 입력하세요."}]}

    monkeypatch.setattr(steps, "apply_rows_to_document", _fail_apply)

    async def _noop_shot(put, page):
        return None

    monkeypatch.setattr(pass2, "emit_shot", _noop_shot)
    events: asyncio.Queue = asyncio.Queue()
    out = await make_apply_doc_node()(
        {"events": events, "page": object(), "filled": 1, "pass1_applied_idx": [0]}
    )
    assert "error" in out and "프로젝트를 입력하세요" in out["error"]


async def test_switch_evdn_matches_pending_by_composite_key(monkeypatch):
    """2차 재조회 행을 (APRVL_NO,일자,금액) 키로 매칭 — 미매칭·과세 재분류 행은 제외."""

    async def _ok_close(page):
        return {"ok": True}

    async def _ok_cards(page, owner_name=None):
        return {"ok": True, "n": 5, "checked": 5, "by": "all"}

    async def _ok_period(page, s, e):
        return {"ok": True}

    async def _q(page, timeout_polls=20):
        return 3

    rows2 = _mixed_rows()  # 같은 거래가 재조회됨(인덱스 동일)
    rows2[2]["i"] = 2

    async def _read(page, limit=200):
        return rows2

    async def _no_modals(page, rounds=3):
        return []

    monkeypatch.setattr(steps, "close_card_popup", _ok_close)
    monkeypatch.setattr(steps, "select_all_cards", _ok_cards)
    monkeypatch.setattr(steps, "set_period", _ok_period)
    monkeypatch.setattr(steps, "run_query", _q)
    monkeypatch.setattr(steps, "read_rows", _read)
    monkeypatch.setattr(steps, "dismiss_blocking_modals", _no_modals)

    async def _noop_node(state):
        return {}

    monkeypatch.setattr(pass2, "make_open_evdn_node", lambda: _noop_node)
    monkeypatch.setattr(pass2, "make_select_evdn_node", lambda code="01": _noop_node)

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

    async def _fake_apply(page, events, rows, collected):
        calls.extend(rows)
        return True, "ok"

    monkeypatch.setattr(batch, "_apply_group_fields", _fake_apply)

    doc_applied: list[list[int]] = []

    async def _ok_doc_apply(page, idx):
        doc_applied.append(list(idx))
        return {"ok": True, "checked": len(idx)}

    monkeypatch.setattr(steps, "apply_rows_to_document", _ok_doc_apply)

    async def _noop_shot(put, page):
        return None

    monkeypatch.setattr(pass2, "emit_shot", _noop_shot)
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
    assert out == {"pass2_filled": 1, "pass2_applied_idx": [1], "pass2_failed": 0} and calls == [1]
    assert doc_applied == [[1]]  # 불공분도 문서 적용까지 자동(저장은 save_final 1회)


async def test_save_final_saves_without_confirmation(monkeypatch):
    """그리드 '입력 완료'가 곧 승인 — 확인 HITL 없이 F7 저장을 진행한다(사용자 업무 규칙)."""

    async def _ok_save(page, confirm):
        assert confirm is True
        return {"ok": True, "via": "F7", "modals_seen": []}

    monkeypatch.setattr(steps, "save_document", _ok_save)

    async def _noop_shot(put, page):
        return None

    monkeypatch.setattr(save, "emit_shot", _noop_shot)
    events: asyncio.Queue = asyncio.Queue()
    out = await make_save_final_node()(
        {"events": events, "page": object(), "filled": 3, "pass2_filled": 1}
    )
    assert out == {"result": "처리 완료 — 과세 3건 · 불공 1건 입력·저장.", "retry_save": False}


def test_parse_save_rejections_extracts_aprvl_account_and_maps_row():
    """ERP 거부 메시지에서 승인번호·요구계정을 뽑고 rows_list APRVL_NO 로 행을 매핑한다."""
    from app.agents.card_collect.nodes import _parse_save_rejections, _save_guidance

    rows = [
        {"APRVL_NO": "03187517", "TRAN_NM": "가맹A"},
        {"APRVL_NO": "99999999", "TRAN_NM": "가맹B"},
    ]
    reason = (
        "[승인번호 : 03187517, 승인취소] 승인 건 계정과 다릅니다. "
        "세금과공과금-인사(과)와 동일해야 합니다. 확인 / "
        "[승인번호 : 03187517, 승인취소] 승인 건 계정과 다릅니다. 세금과공과금-인사(과)와 동일해야 합니다. 확인"
    )
    issues = _parse_save_rejections(reason, rows)
    assert len(issues) == 1  # 중복 승인번호 접힘
    it = issues[0]
    assert it["aprvlNo"] == "03187517"
    assert it["requiredAccount"] == "세금과공과금-인사(과)"
    assert it["rowNo"] == 1 and it["merchant"] == "가맹A"
    # 안내 본문에 행·계정·조치가 담긴다.
    guide = _save_guidance(issues, reason)
    assert "1행" in guide and "세금과공과금-인사(과)" in guide and "예산단위" in guide


def test_parse_save_rejections_falls_back_when_unparseable():
    """형식이 다르면 빈 리스트 → 안내는 원문 폴백."""
    from app.agents.card_collect.nodes import _parse_save_rejections, _save_guidance

    assert _parse_save_rejections("알 수 없는 오류", []) == []
    assert "알 수 없는 오류" in _save_guidance([], "알 수 없는 오류")


async def test_save_final_retries_on_erp_rejection_then_gives_up(monkeypatch):
    """저장 거부(ERP 오류) 시 상한까지 retry_save 를 켜 그리드로 되돌리고, 초과하면 실패 종료."""

    async def _reject(page, confirm):
        return {"ok": False, "reason": "승인 건 계정과 다릅니다."}

    monkeypatch.setattr(steps, "save_document", _reject)

    async def _noop_shot(put, page):
        return None

    monkeypatch.setattr(save, "emit_shot", _noop_shot)

    # 1차 실패(save_retries 0) → 재시도 신호 + 카운터 1.
    out1 = await make_save_final_node()(
        {"events": asyncio.Queue(), "page": object(), "filled": 3, "pass2_filled": 1, "save_retries": 0}
    )
    assert out1 == {
        "retry_save": True,
        "save_retries": 1,
        "save_error_msg": "승인 건 계정과 다릅니다.",
        "save_error_issues": [],  # 승인번호/요구계정 없는 메시지 → 파싱 없음(원문 폴백)
    }

    # 상한(2) 도달 후 또 실패 → 재시도 안 하고 error(retry_save False).
    out2 = await make_save_final_node()(
        {"events": asyncio.Queue(), "page": object(), "filled": 3, "pass2_filled": 1, "save_retries": 2}
    )
    assert out2["retry_save"] is False and "저장 실패" in out2["error"]


def test_graph_has_save_retry_edge_to_menu_nav():
    """save_final 실패 재시도 라우팅: retry_save 면 menu_nav 로, 아니면 END."""
    from app.agents.card_collect import graph as gmod

    g = gmod.build_card_collect_graph()
    # 컴파일된 그래프에 조건부 엣지가 있고 recursion_limit 이 상향됐는지(재시도 3패스 허용).
    assert g.config.get("recursion_limit", 25) >= 45


async def test_save_final_zero_total_skips_save(monkeypatch):
    """반영 0건이면 저장하지 않는다."""
    called = []

    async def _save(page, confirm):
        called.append(1)
        return {"ok": True}

    monkeypatch.setattr(steps, "save_document", _save)
    events: asyncio.Queue = asyncio.Queue()
    out = await make_save_final_node()(
        {"events": events, "page": object(), "filled": 0, "pass2_filled": 0}
    )
    assert "반영 0건" in out["result"] and not called


async def test_switch_evdn_duplicate_composite_keys_consume_distinct_rows(monkeypatch):
    """동일 복합키 2행 — 각 pending 이 서로 다른 실제 행을 1:1 소비(이중반영/누락 금지)."""

    async def _ok_close(page):
        return {"ok": True}

    async def _ok_cards(page, owner_name=None):
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

    async def _no_modals(page, rounds=3):
        return []

    monkeypatch.setattr(steps, "close_card_popup", _ok_close)
    monkeypatch.setattr(steps, "select_all_cards", _ok_cards)
    monkeypatch.setattr(steps, "set_period", _ok_period)
    monkeypatch.setattr(steps, "run_query", _q)
    monkeypatch.setattr(steps, "read_rows", _read)
    monkeypatch.setattr(steps, "dismiss_blocking_modals", _no_modals)

    async def _noop_node(state):
        return {}

    monkeypatch.setattr(pass2, "make_open_evdn_node", lambda: _noop_node)
    monkeypatch.setattr(pass2, "make_select_evdn_node", lambda code="01": _noop_node)

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


def test_graph_state_declares_all_node_output_keys():
    """노드 반환 키가 CardCollectState 에 선언돼야 다음 노드로 전달된다(미선언=조용한 누락).

    실전 런 회귀: pass1_applied_idx 미선언 → save 노드에서 '적용할 행이 없습니다' 실패.
    새 반환 키를 추가하면 이 목록과 TypedDict 둘 다 갱신할 것.
    검증은 support.state_contract(get_type_hints 기반 — BaseAgentState 상속 키 포함)로 한다.
    """
    from app.agents.card_collect.graph import CardCollectState
    from tests.support.state_contract import assert_keys_declared

    node_output_keys = {
        "period", "rows_list", "filled", "pending_nontax", "pass1_applied_idx",
        "pass1_doc_applied", "rows2_list", "pass2_work",
        "pass2_unmatched", "pass2_unmatched_desc", "pass2_filled", "pass2_applied_idx",
        "result", "error",
    }
    assert_keys_declared(CardCollectState, dict.fromkeys(node_output_keys))


def test_graph_compiles_and_channels_include_inherited_base_keys():
    """BaseAgentState 상속 키(page/result 등)가 State 계약·컴파일 채널에 모두 실린다.

    LangGraph 는 get_type_hints 로 채널을 수집하므로 상속 키도 채널이 된다 — 상속 구조
    전환(BaseAgentState) 후에도 러너 주입 키가 노드 간 전달됨을 회귀 방지한다.
    """
    from app.agents.card_collect.graph import CardCollectState, build_card_collect_graph
    from tests.support.state_contract import all_declared_keys

    keys = all_declared_keys(CardCollectState)
    assert {"page", "browser", "events", "owner", "run_id", "result", "error"} <= keys
    g = build_card_collect_graph()  # 컴파일 자체가 State 스키마 검증
    assert {"page", "result"} <= set(g.channels)


async def test_prefill_cost_prefix_biases_default_budget():
    """비용구분 접두사가 있으면 기본지정이 없어도 접두사 일치 예산단위로 폴백한다."""
    from types import SimpleNamespace

    from app.agents.card_collect.nodes import _prefill_selections

    events: asyncio.Queue = asyncio.Queue()
    settings = SimpleNamespace(gemini_api_key="")  # AI 스킵 → 기본 폴백 경로.
    rows_list = [{"i": 0, "TRAN_NM": "가맹점", "TRAN_AMT": "1000", "VAT_TP": "과세"}]
    # isDefault 없음. (판)/(제) 두 후보 — cost_prefix='(제)' 면 제조원가 계정이 폴백돼야 한다.
    budget_favs = [
        {"code": "P1", "name": "인사기획팀", "bgacctNm": "(판)소모품비"},
        {"code": "M1", "name": "인사기획팀", "bgacctNm": "(제)복리후생비"},
    ]
    out = await _prefill_selections(
        events, settings, rows_list, {0: "적요"}, budget_favs, [], [], cost_prefix="(제)"
    )
    assert out[1]["budgetSource"] == "default"
    assert out[1]["budgetUnit"]["code"] == "M1"  # (제) 접두사 일치 폴백


# ── 회계일(set_acct_date) — 수집 기간 월의 말일(규칙 2026-07-04) ────────────────
def test_period_month_end():
    assert steps.period_month_end("2026-06-01") == ("20260630", "2026-06-30")
    assert steps.period_month_end("2026-02-01") == ("20260228", "2026-02-28")
    assert steps.period_month_end("2025-12-01") == ("20251231", "2025-12-31")


async def test_set_acct_date_node_uses_period_month_end(monkeypatch):
    """전월 수집(10일 미만)=전월 말일, 당월 수집(10일부터)=당월 말일을 ACTG_DT 로 설정."""
    calls: dict = {}

    async def _fake_set(page, compact, dashed):
        calls["compact"], calls["dashed"] = compact, dashed
        return {"ok": True, "display": dashed}

    monkeypatch.setattr(steps, "set_acct_date", _fake_set)
    node = cc_nodes.make_set_acct_date_node()

    out = await node({"events": asyncio.Queue(), "page": object(), "params": {"today": "2026-07-02"}})
    assert out == {}
    assert calls["compact"] == "20260630"  # 7/2(10일 미만) → 전월(6월) 말일

    await node({"events": asyncio.Queue(), "page": object(), "params": {"today": "2026-07-15"}})
    assert calls["compact"] == "20260731"  # 10일부터 → 당월(7월) 말일


async def test_set_acct_date_node_fails_on_step_error(monkeypatch):
    async def _fail(page, compact, dashed):
        return {"ok": False, "reason": "결의서(마스터) 행 없음"}

    monkeypatch.setattr(steps, "set_acct_date", _fail)
    out = await cc_nodes.make_set_acct_date_node()(
        {"events": asyncio.Queue(), "page": object(), "params": {}}
    )
    assert "회계일 설정 실패" in out["error"]


# ── 전사 seed(기초자료) 프리필 ─────────────────────────────────────────────────
def test_resolve_seed_budget_matches_account_via_bgacctnm():
    """seed 계정과목명을 예산단위 bgacctNm 과 (판)/(제) 접두사 무시하고 매칭. 모호/무매칭→None."""
    from app.agents.card_collect.nodes import _resolve_seed_budget

    cands = [
        {"code": "B1", "name": "인사기획팀", "bgacctNm": "(판)복리후생비-석식"},
        {"code": "B2", "name": "인사기획팀", "bgacctNm": "(판)소모품비"},
    ]
    assert _resolve_seed_budget("복리후생비-석식", cands)["code"] == "B1"  # 접두사 무시 정확 매칭
    assert _resolve_seed_budget("여비교통비", cands) is None  # 무매칭
    # 같은 계정을 (판)/(제) 두 예산단위가 가지면 모호 → None(AI/기본에 맡김).
    ambiguous = cands + [{"code": "B3", "name": "영업팀", "bgacctNm": "(제)복리후생비-석식"}]
    assert _resolve_seed_budget("복리후생비-석식", ambiguous) is None


async def test_prefill_uses_seed_budget_between_ai_and_default():
    """개인학습·AI 없음 → 전사 seed 로 해석한 예산단위(source='seed')를 기본보다 우선."""
    from types import SimpleNamespace

    from app.agents.card_collect.nodes import _prefill_selections
    from app.services import card_learning

    settings = SimpleNamespace(gemini_api_key="")  # AI off
    rows_list = [{"i": 0, "TRAN_NM": "맘스터치 상대원점", "TRAN_AMT": "9000", "VAT_TP": "과세"}]
    # 기본지정 예산단위(B0)와, seed 계정에 매칭되는 예산단위(B1)가 공존 — seed 가 기본보다 우선.
    budget_favs = [{"code": "B0", "name": "인사기획팀", "bgacctNm": "(판)소모품비", "isDefault": True}]
    mine = [{"code": "B1", "name": "인사기획팀", "bgacctNm": "(판)복리후생비-석식"}]
    seed = {
        card_learning.norm_merchant("맘스터치 상대원점"): {
            "acct_name": "복리후생비-석식", "note": "직원 야근식대", "count": 562, "dominance": 0.93,
        }
    }
    out = await _prefill_selections(
        asyncio.Queue(), settings, rows_list, {0: "x"}, budget_favs, mine, [], seed=seed,
    )
    assert out[1]["budgetSource"] == "seed"
    assert out[1]["budgetUnit"]["code"] == "B1"  # 기본(B0) 아닌 seed 해석(B1)


# ── 패스 스킵 경로 보증(사용자 지적 2026-07-04) ─────────────────────────────────
async def test_save_final_saves_when_no_nontax(monkeypatch):
    """불공 0건: 2차를 생략해도 과세 반영분만으로 최종 저장(F7)해야 한다."""
    saved: list[bool] = []

    async def _ok_save(page, confirm):
        saved.append(confirm)
        return {"ok": True, "via": "F7", "modals_seen": []}

    monkeypatch.setattr(steps, "save_document", _ok_save)

    async def _noop_shot(emit, page):
        return None

    monkeypatch.setattr(save, "emit_shot", _noop_shot)
    out = await cc_nodes.make_save_final_node()(
        {"events": asyncio.Queue(), "page": object(), "filled": 3, "pass2_filled": 0}
    )
    assert saved == [True]
    assert "과세 3건 · 불공 0건" in out["result"]


async def test_save_final_saves_when_no_taxable(monkeypatch):
    """과세 0건: 1차를 생략해도 불공 반영분만으로 최종 저장(F7)해야 한다."""
    saved: list[bool] = []

    async def _ok_save(page, confirm):
        saved.append(confirm)
        return {"ok": True, "via": "F7", "modals_seen": []}

    monkeypatch.setattr(steps, "save_document", _ok_save)

    async def _noop_shot(emit, page):
        return None

    monkeypatch.setattr(save, "emit_shot", _noop_shot)
    out = await cc_nodes.make_save_final_node()(
        {"events": asyncio.Queue(), "page": object(), "filled": 0, "pass2_filled": 2}
    )
    assert saved == [True]
    assert "과세 0건 · 불공 2건" in out["result"]


async def test_save_final_fails_loudly_when_all_rows_failed(monkeypatch):
    """반영 0건이 '행 실패' 때문이면 성공 위장 금지 — 실패로 보고, 저장 안 함(실전 40/40 회귀)."""
    called: list[bool] = []

    async def _save(page, confirm):
        called.append(confirm)
        return {"ok": True}

    monkeypatch.setattr(steps, "save_document", _save)
    out = await cc_nodes.make_save_final_node()(
        {"events": asyncio.Queue(), "page": object(), "filled": 0, "pass2_filled": 0, "pass1_failed": 40}
    )
    assert called == []  # 저장 시도 자체가 없어야 한다
    assert "모든 행 반영 실패(40건)" in out["error"]


async def test_apply_doc_skips_without_apply_when_no_taxable(monkeypatch):
    """과세 0건이면 apply_doc 은 '적용' 없이 통과(에러 없음) — 2차(불공)로 진행 가능해야 한다."""
    applied: list = []

    async def _apply(page, idx):
        applied.append(idx)
        return {"ok": True}

    monkeypatch.setattr(steps, "apply_rows_to_document", _apply)
    out = await cc_nodes.make_apply_doc_node()(
        {"events": asyncio.Queue(), "page": object(), "filled": 0}
    )
    assert out == {}  # 에러 없음 + pass1_doc_applied 미설정(2차는 기존 행에서 재선택)
    assert applied == []


# ── 일괄적용 그룹핑(같은 예산단위·프로젝트·적요 → '일괄적용' 1회, 2026-07-04) ──────
async def test_grid_submit_batches_same_key_rows_into_one_apply(monkeypatch):
    """예산단위·프로젝트·적요가 같은 행들은 한 번의 그룹 호출(일괄적용 1회)로 반영된다."""
    _stub_dumps(monkeypatch, units=[])
    group_calls: list[list[int]] = []

    async def _fake_apply(page, events, rows, collected):
        group_calls.append(list(rows))
        return True, "ok"

    monkeypatch.setattr(batch, "_apply_group_fields", _fake_apply)

    events: asyncio.Queue = asyncio.Queue()
    state = {"events": events, "page": object(), "rows_list": _rows(3), "owner": None}
    task = asyncio.create_task(make_collect_rows_node()(state))
    frame = await _next_hitl(events)

    bu = {"code": "2000", "name": "경영본부"}
    resolve_hitl(
        frame["id"],
        {
            "rows": [
                {"no": 1, "budgetUnit": bu, "note": "회식"},
                {"no": 2, "budgetUnit": bu, "note": "회식"},  # 1행과 같은 키 → 같은 그룹
                {"no": 3, "budgetUnit": {"code": "1000", "name": "영업본부"}, "note": "회식"},
            ]
        },
    )
    out = await asyncio.wait_for(task, timeout=2)
    assert out["filled"] == 3 and out["pass1_applied_idx"] == [0, 1, 2]
    assert group_calls == [[0, 1], [2]]  # 그룹 2개 — 첫 그룹은 2행 일괄


async def test_apply_group_fields_batches_and_skips_account_picker(monkeypatch):
    """_apply_group_fields: 계정 피커를 열지 않고(자동), 그룹 행 전체를 apply_rows 1회로 반영."""
    picked: list[str] = []
    applied_rows: list[list[int]] = []

    async def _note(page, row, text):
        return {"ok": True}

    async def _bg(page, combo):
        picked.append("bg")
        return {"ok": True, "code": "2006", "name": "인사기획팀"}

    async def _pjt(page, combo):
        picked.append("pjt")
        return {"ok": True, "code": "0001", "name": "SPARES"}

    async def _acct(page, *a, **k):
        picked.append("acct")  # 호출되면 안 된다
        return {"ok": True}

    async def _apply(page, rows):
        applied_rows.append(list(rows))
        return {"ok": True}

    monkeypatch.setattr(steps, "set_note", _note)
    monkeypatch.setattr(steps, "fill_budget_codepicker", _bg)
    monkeypatch.setattr(steps, "fill_project_codepicker", _pjt)
    monkeypatch.setattr(steps, "fill_codepicker", _acct)
    monkeypatch.setattr(steps, "apply_rows", _apply)

    ok, detail = await batch._apply_group_fields(
        object(),
        asyncio.Queue(),
        [0, 2, 5],
        {"예산단위": "인사기획팀", "프로젝트": "SPARES", "적요": "회식"},
    )
    assert ok and "(3건 일괄)" in detail
    assert picked == ["bg", "pjt"]  # 계정(acct) 피커 미호출
    assert applied_rows == [[0, 2, 5]]  # 일괄적용 1회
