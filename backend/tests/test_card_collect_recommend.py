"""card_collect AI 추천(recommend) + collect_rows 프리셀렉트 통합 테스트(브라우저·네트워크 불필요).

- recommend_selections: 가짜 gemini_chat_decide 로 응답을 주입해 검증 로직만 본다
  (범위 밖 no 무시 · 후보에 없는 code 무시 · confidence 0..1 클램프 · 키/후보 없음 → {}).
- collect_rows 통합: 추천을 몽키패치해 프레임 rows 의 budgetUnit/project·Source 프리셀렉트를 본다
  (높은 확신 → 'ai' · 낮은 확신/무추천 → 기본지정 'default' · 없으면 None · 추천 예외 → 기본 폴백).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.agents.card_collect import recommend, steps
from app.agents.card_collect.nodes import catalog, make_collect_rows_node, prefill
from app.config import get_settings
from app.live.hitl import resolve_hitl


@pytest.fixture(autouse=True)
def _force_gemini_key(monkeypatch):
    """collect_rows 의 _prefill 은 gemini_api_key 가 있어야 추천 경로를 탄다 — env 무관하게 강제."""
    monkeypatch.setattr(get_settings(), "gemini_api_key", "test-key")


def _fake_settings() -> SimpleNamespace:
    return SimpleNamespace(
        gemini_api_key="test-key",
        gemini_model="gemini-test",
        gemini_base_url="https://example.invalid/v1beta",
    )


# ── recommend_selections 순수 검증 ─────────────────────────────────────────────
async def test_recommend_selections_validates_range_codes_and_clamp(monkeypatch):
    async def _fake_decide(http, key, model, base, system, history, context, shot, tools):
        return "submit_recommendations", {
            "recommendations": [
                # confidence>1 → 1.0 클램프, 정상 코드.
                {"no": 1, "budgetUnitCode": "B1", "projectCode": "P1", "confidence": 1.7},
                # 범위 밖 no → 무시.
                {"no": 99, "budgetUnitCode": "B1", "confidence": 0.9},
                # 후보에 없는 code → 그 필드 무시(빈 문자열), confidence<0 → 0.0 클램프.
                {"no": 2, "budgetUnitCode": "NOPE", "projectCode": "NOPE", "confidence": -0.5},
            ]
        }

    monkeypatch.setattr(recommend, "gemini_chat_decide", _fake_decide)
    rows = [{"no": 1, "merchant": "a"}, {"no": 2, "merchant": "b"}]
    budget = [{"code": "B1", "name": "예산1"}]
    project = [{"code": "P1", "name": "프로젝트1"}]

    out = await recommend.recommend_selections(
        rows, budget, project, http=object(), settings=_fake_settings()
    )
    assert out[1] == {
        "budgetUnitCode": "B1",
        "projectCode": "P1",
        "confidence": 1.0,
        "vatDeduction": None,
    }
    assert 99 not in out
    assert out[2] == {
        "budgetUnitCode": "",
        "projectCode": "",
        "confidence": 0.0,
        "vatDeduction": None,
    }


async def test_recommend_selections_skips_without_key():
    out = await recommend.recommend_selections(
        [{"no": 1}], [{"code": "B1", "name": "n"}], [], http=object(),
        settings=SimpleNamespace(gemini_api_key="", gemini_model="m", gemini_base_url="b"),
    )
    assert out == {}


async def test_recommend_selections_skips_without_candidates():
    out = await recommend.recommend_selections(
        [{"no": 1}], [], [], http=object(), settings=_fake_settings()
    )
    assert out == {}


async def test_recommend_selections_swallows_gemini_error(monkeypatch):
    async def _boom(*args, **kwargs):
        raise RuntimeError("gemini down")

    monkeypatch.setattr(recommend, "gemini_chat_decide", _boom)
    out = await recommend.recommend_selections(
        [{"no": 1}], [{"code": "B1", "name": "n"}], [], http=object(), settings=_fake_settings()
    )
    assert out == {}


# ── collect_rows 통합(프리셀렉트) ──────────────────────────────────────────────
def _rows(n: int) -> list[dict]:
    return [
        {
            "i": i,
            "FINPRODUCT_NM": f"카드-{i}",
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


def _favs_loader(budget, project, dept):
    async def _load(owner):
        return (list(budget), list(project), dept)

    return _load


async def _drain_and_finish(task: asyncio.Task, frame: dict, n: int) -> dict:
    resolve_hitl(frame["id"], {"rows": [{"no": i + 1, "skip": True} for i in range(n)]})
    return await asyncio.wait_for(task, timeout=2)


async def test_collect_rows_high_confidence_preselects_ai(monkeypatch):
    _stub_dumps(monkeypatch, units=[])
    monkeypatch.setattr(
        catalog,
        "_load_user_favorites",
        _favs_loader([{"code": "2101", "name": "인사기획팀"}], [], None),
    )

    async def _rec(rec_rows, budget_c, project_c, *, http, settings):
        return {1: {"budgetUnitCode": "2101", "projectCode": "", "confidence": 0.9}}

    monkeypatch.setattr(prefill, "recommend_selections", _rec)

    events: asyncio.Queue = asyncio.Queue()
    state = {"events": events, "page": object(), "rows_list": _rows(2), "owner": None}
    task = asyncio.create_task(make_collect_rows_node()(state))
    frame = await _next_hitl(events)

    assert frame["rows"][0]["budgetUnit"] == {
        "code": "2101", "name": "인사기획팀", "bizplanNm": "", "bgacctCd": "", "bgacctNm": "",
    }
    assert frame["rows"][0]["budgetSource"] == "ai"
    # 추천 없고 기본지정도 없는 2행 → 프리셀렉트 없음.
    assert frame["rows"][1]["budgetUnit"] is None and frame["rows"][1]["budgetSource"] is None

    assert (await _drain_and_finish(task, frame, 2)) == {"filled": 0, "pending_nontax": [], "pass1_applied_idx": [], "pass1_failed": 0}


async def test_collect_rows_low_confidence_falls_back_to_default(monkeypatch):
    _stub_dumps(monkeypatch, units=[])
    monkeypatch.setattr(
        catalog,
        "_load_user_favorites",
        _favs_loader(
            [
                {"code": "2101", "name": "인사기획팀"},
                {"code": "9000", "name": "기본예산", "isDefault": True},
            ],
            [],
            None,
        ),
    )

    async def _rec(rec_rows, budget_c, project_c, *, http, settings):
        return {1: {"budgetUnitCode": "2101", "projectCode": "", "confidence": 0.3}}

    monkeypatch.setattr(prefill, "recommend_selections", _rec)

    events: asyncio.Queue = asyncio.Queue()
    state = {"events": events, "page": object(), "rows_list": _rows(1), "owner": None}
    task = asyncio.create_task(make_collect_rows_node()(state))
    frame = await _next_hitl(events)

    # 낮은 확신 → AI 추천(2101) 대신 기본지정(9000) 폴백.
    assert frame["rows"][0]["budgetUnit"]["code"] == "9000"
    assert frame["rows"][0]["budgetSource"] == "default"

    assert (await _drain_and_finish(task, frame, 1)) == {"filled": 0, "pending_nontax": [], "pass1_applied_idx": [], "pass1_failed": 0}


async def test_collect_rows_budget_ai_project_default_independent(monkeypatch):
    """예산단위는 AI, 프로젝트는 기본 — 두 필드가 독립적으로 결정된다."""
    _stub_dumps(monkeypatch, units=[])
    monkeypatch.setattr(
        catalog,
        "_load_user_favorites",
        _favs_loader(
            [{"code": "2101", "name": "인사기획팀"}],
            [{"code": "PP", "name": "기본프로젝트", "wbsNo": "W1", "wbsNm": "WBS1", "isDefault": True}],
            None,
        ),
    )

    async def _rec(rec_rows, budget_c, project_c, *, http, settings):
        # 예산단위만 확신, 프로젝트는 빈 코드 → 프로젝트는 기본지정 폴백.
        return {1: {"budgetUnitCode": "2101", "projectCode": "", "confidence": 0.95}}

    monkeypatch.setattr(prefill, "recommend_selections", _rec)

    events: asyncio.Queue = asyncio.Queue()
    state = {"events": events, "page": object(), "rows_list": _rows(1), "owner": None}
    task = asyncio.create_task(make_collect_rows_node()(state))
    frame = await _next_hitl(events)

    assert frame["rows"][0]["budgetSource"] == "ai"
    assert frame["rows"][0]["budgetUnit"]["code"] == "2101"
    assert frame["rows"][0]["projectSource"] == "default"
    assert frame["rows"][0]["project"] == {
        "code": "PP", "name": "기본프로젝트", "wbsNo": "W1", "wbsNm": "WBS1",
    }

    assert (await _drain_and_finish(task, frame, 1)) == {"filled": 0, "pending_nontax": [], "pass1_applied_idx": [], "pass1_failed": 0}


async def test_collect_rows_recommend_exception_uses_default_fallback(monkeypatch):
    """추천 호출이 내부에서 실패해도(예외) 런은 살고, 전 행이 기본지정으로 프리필된다."""
    _stub_dumps(monkeypatch, units=[])
    monkeypatch.setattr(
        catalog,
        "_load_user_favorites",
        _favs_loader([{"code": "9000", "name": "기본예산", "isDefault": True}], [], None),
    )

    async def _boom(*args, **kwargs):
        raise RuntimeError("gemini down")

    # 실제 recommend_selections 를 태우되 그 안의 gemini 호출만 폭발 → {} 흡수 → 기본 폴백.
    monkeypatch.setattr(recommend, "gemini_chat_decide", _boom)

    events: asyncio.Queue = asyncio.Queue()
    state = {"events": events, "page": object(), "rows_list": _rows(2), "owner": None}
    task = asyncio.create_task(make_collect_rows_node()(state))
    frame = await _next_hitl(events)

    for i in range(2):
        assert frame["rows"][i]["budgetUnit"]["code"] == "9000"
        assert frame["rows"][i]["budgetSource"] == "default"

    assert (await _drain_and_finish(task, frame, 2)) == {"filled": 0, "pending_nontax": [], "pass1_applied_idx": [], "pass1_failed": 0}


async def test_prefill_cost_project_default_fallback():
    """프로젝트 기본: 기본지정 즐겨찾기 없으면 팀 비용구분 프로젝트(500/800)로 폴백."""
    from types import SimpleNamespace

    from app.agents.card_collect.nodes import _prefill_selections

    settings = SimpleNamespace(gemini_api_key="")  # AI 스킵 → 기본 폴백 경로.
    rows_list = [{"i": 0, "TRAN_NM": "가맹점", "TRAN_AMT": "1000", "VAT_TP": "과세"}]
    cost_project = {"code": "800|800", "name": "판매관리비", "wbsNo": "800", "wbsNm": "판매관리비"}
    out = await _prefill_selections(
        asyncio.Queue(), settings, rows_list, {0: "적요"},
        [], [], [],  # 즐겨찾기 없음(기본지정 없음)
        cost_project=cost_project,
    )
    assert out[1]["projectSource"] == "default"
    assert out[1]["project"]["code"] == "800|800" and out[1]["project"]["wbsNo"] == "800"


async def test_prefill_explicit_default_favorite_beats_cost_project():
    """기본지정 즐겨찾기(명시 설정)가 있으면 비용구분 프로젝트보다 우선한다."""
    from types import SimpleNamespace

    from app.agents.card_collect.nodes import _prefill_selections

    settings = SimpleNamespace(gemini_api_key="")
    rows_list = [{"i": 0, "TRAN_NM": "가맹점", "TRAN_AMT": "1000", "VAT_TP": "과세"}]
    favs = [{"code": "P9|W9", "name": "내프로젝트", "wbsNo": "W9", "wbsNm": "", "isDefault": True}]
    out = await _prefill_selections(
        asyncio.Queue(), settings, rows_list, {0: "적요"},
        [], [], favs,
        cost_project={"code": "800|800", "name": "판매관리비", "wbsNo": "800", "wbsNm": ""},
    )
    assert out[1]["project"]["code"] == "P9|W9"  # 명시 기본지정 우선


async def test_learned_note_prefills_grid(monkeypatch):
    """학습된 적요가 있으면 키워드 휴리스틱 대신 그 적요로 그리드 프리필된다."""
    from app.services import card_learning

    async def _learned(owner, merchants):
        return {
            card_learning.norm_merchant("네이버파이낸셜㈜"): {
                "merchant": "네이버파이낸셜㈜",
                "budget": {"code": "b1", "name": "인사기획팀"},
                "project": None,
                "note": "6월 팀 소모품",
                "count": 1,
            }
        }

    monkeypatch.setattr(card_learning, "retrieve_for_merchants", _learned)
    _stub_dumps(monkeypatch, units=[{"code": "b1", "name": "인사기획팀"}])

    events: asyncio.Queue = asyncio.Queue()
    rows = [{"i": 0, "TRAN_NM": "네이버파이낸셜(주)", "TRAN_AMT": "1000", "VAT_TP": "과세",
             "TRAN_DT": "2026-06-01", "TRAN_TM": "00:00:00", "APRVL_YN": "승인",
             "FINPRODUCT_NM": "카드"}]
    state = {"events": events, "page": object(), "rows_list": rows, "owner": None}
    task = asyncio.create_task(make_collect_rows_node()(state))
    frame = await _next_hitl(events)
    assert frame["rows"][0]["note"] == "6월 팀 소모품"  # 학습 적요 프리필(휴리스틱 아님)

    resolve_hitl(frame["id"], {"rows": [{"no": 1, "skip": True}]})
    await asyncio.wait_for(task, timeout=2)
