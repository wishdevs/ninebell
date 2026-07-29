"""card_collect AI 추천(recommend) + collect_rows 프리셀렉트 통합 테스트(브라우저·네트워크 불필요).

- recommend_selections: 가짜 chat_decide(LLM 디스패처)로 응답을 주입해 검증 로직만 본다
  (범위 밖 no 무시 · 후보에 없는 code 무시 · confidence 0..1 클램프 · 키/후보 없음 → {}).
- collect_rows 통합: 추천을 몽키패치해 프레임 rows 의 budgetUnit/project·Source 프리셀렉트를 본다
  (높은 확신 → 'ai' · 낮은 확신/무추천 → 기본지정 'default' · 없으면 None · 추천 예외 → 기본 폴백).
"""

from __future__ import annotations

import asyncio
import inspect
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
    async def _fake_decide(http, **_kw):
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

    monkeypatch.setattr(recommend, "chat_decide", _fake_decide)
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

    monkeypatch.setattr(recommend, "chat_decide", _boom)
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

    async def _rec(rec_rows, budget_c, project_c, *, http, settings, cost_prefix=None):
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

    async def _rec(rec_rows, budget_c, project_c, *, http, settings, cost_prefix=None):
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

    async def _rec(rec_rows, budget_c, project_c, *, http, settings, cost_prefix=None):
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
    monkeypatch.setattr(recommend, "chat_decide", _boom)

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


# ── 비용구분 필터 — 반대 버킷 제외 + 중립 보존(토큰 절감, 사용자 확정 2026-07-23) ────────────
def test_filter_budget_by_cost_drops_opposite_bucket_keeps_neutral():
    budget = [
        {"code": "a", "bgacctNm": "(판)여비교통비-해외출장"},
        {"code": "b", "bgacctNm": "(제)차량유지비-유류"},  # 반대 버킷 — 제외.
        {"code": "c", "bgacctNm": "지급수수료(구매 )"},  # 접두 없음(중립) — 유지.
        {"code": "d", "bgacctNm": "기부금"},  # 중립 — 유지.
    ]
    kept = [c["code"] for c in recommend._filter_budget_by_cost(budget, "(판)")]
    assert kept == ["a", "c", "d"]
    # 접두 미상이면 필터하지 않는다(원본 유지).
    assert len(recommend._filter_budget_by_cost(budget, None)) == 4


def test_filter_project_by_cost_drops_opposite_bucket_keeps_specific():
    proj = [
        {"code": "500|500", "name": "제조원가"},  # 반대 버킷 — 제외.
        {"code": "800|800", "name": "판매관리비"},  # 일치 버킷 — 유지.
        {"code": "120|A", "name": "특정PJT"},  # 버킷 아님(부서 무관) — 유지.
    ]
    kept = [c["code"] for c in recommend._filter_project_by_cost(proj, "(판)")]
    assert kept == ["800|800", "120|A"]
    assert len(recommend._filter_project_by_cost(proj, None)) == 3


async def test_recommend_context_slims_budget_fields_and_filters_bucket(monkeypatch):
    """LLM 컨텍스트: 예산 후보에서 name·bizplanNm 제외 + 반대 버킷((제)) 제외."""
    seen = {}

    async def _decide(http, *, system, history, context, shot_b64, tools, settings):
        seen["ctx"] = context
        return "submit_recommendations", {"recommendations": []}

    monkeypatch.setattr(recommend, "chat_decide", _decide)
    monkeypatch.setattr(recommend, "llm_ready", lambda s: True)
    budget = [
        {"code": "2006|600|812002600", "name": "인사기획팀", "bizplanNm": "운영비", "bgacctNm": "(판)여비교통비-해외출장"},
        {"code": "2006|500|522002600", "name": "인사기획팀", "bizplanNm": "운영비 (제조)", "bgacctNm": "(제)차량유지비-유류"},
    ]
    await recommend.recommend_selections(
        [{"no": 1, "merchant": "m", "amount": "1원", "vatType": "과세", "note": "n"}],
        budget,
        [{"code": "800|800", "name": "판매관리비", "wbsNm": ""}],
        http=object(),
        settings=object(),
        cost_prefix="(판)",
    )
    bc = seen["ctx"]["budgetCandidates"]
    assert len(bc) == 1 and bc[0]["code"] == "2006|600|812002600"  # (제) 제외.
    assert set(bc[0].keys()) == {"code", "bgacctNm"}  # name·bizplanNm 제거.


# ══════════════════════════════════════════════════════════════════════════════
# 배치 분할(2026-07-27) — 400행을 한 번에 보내면 **출력 토큰 상한**(4096, 사고와 공유)을
# 넘겨 응답이 잘리고 전 행이 추천 없이 진행됐다. 청크로 나누고 실패를 격리한다.
# ══════════════════════════════════════════════════════════════════════════════
def _rows(n: int) -> list[dict]:
    return [{"no": i, "merchant": f"가맹점{i}", "amount": "1,000", "vatType": "과세"} for i in range(1, n + 1)]


_CANDS = ([{"code": "B1", "bgacctNm": "판매비"}], [{"code": "P1", "name": "프로젝트"}])


async def test_recommend_splits_large_input_into_chunks(monkeypatch):
    seen: list[int] = []

    async def _fake_decide(http, *, system, history, context, shot_b64, tools, settings):
        rows = context["rows"]
        seen.append(len(rows))
        return "submit_recommendations", {
            "recommendations": [
                {"no": r["no"], "budgetUnitCode": "B1", "projectCode": "P1", "confidence": 0.9}
                for r in rows
            ]
        }

    monkeypatch.setattr(recommend, "chat_decide", _fake_decide)
    out = await recommend.recommend_selections(
        _rows(400), _CANDS[0], _CANDS[1], http=None, settings=_fake_settings()
    )
    # 400행 → 30행씩 14청크, 각 청크는 상한(30) 이하.
    assert len(seen) == 14 and max(seen) <= recommend.RECOMMEND_CHUNK_SIZE
    assert sum(seen) == 400
    assert len(out) == 400  # 전 행 추천 수신


async def test_recommend_isolates_failing_chunk(monkeypatch):
    """한 청크가 실패해도 나머지 청크의 추천은 살아야 한다(종전엔 전량 손실)."""
    calls = {"n": 0}

    async def _flaky(http, *, system, history, context, shot_b64, tools, settings):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("응답이 잘렸습니다(finish_reason=length)")
        return "submit_recommendations", {
            "recommendations": [
                {"no": r["no"], "budgetUnitCode": "B1", "projectCode": "P1", "confidence": 0.8}
                for r in context["rows"]
            ]
        }

    monkeypatch.setattr(recommend, "chat_decide", _flaky)
    out = await recommend.recommend_selections(
        _rows(90), _CANDS[0], _CANDS[1], http=None, settings=_fake_settings()
    )
    assert 0 < len(out) == 60  # 3청크 중 1개만 실패 → 60행 생존


async def test_recommend_rejects_row_numbers_from_other_chunks(monkeypatch):
    """청크 검증은 **그 청크의 no** 만 허용한다 — 다른 청크 행 번호 오염을 차단."""

    async def _cross(http, *, system, history, context, shot_b64, tools, settings):
        return "submit_recommendations", {
            "recommendations": [
                {"no": 999, "budgetUnitCode": "B1", "projectCode": "P1", "confidence": 0.9}
            ]
        }

    monkeypatch.setattr(recommend, "chat_decide", _cross)
    out = await recommend.recommend_selections(
        _rows(60), _CANDS[0], _CANDS[1], http=None, settings=_fake_settings()
    )
    assert out == {}


async def test_recommend_single_chunk_when_small(monkeypatch):
    """작은 입력은 종전대로 1회 호출(불필요한 분할 없음)."""
    calls = {"n": 0}

    async def _once(http, *, system, history, context, shot_b64, tools, settings):
        calls["n"] += 1
        return "submit_recommendations", {"recommendations": []}

    monkeypatch.setattr(recommend, "chat_decide", _once)
    await recommend.recommend_selections(
        _rows(10), _CANDS[0], _CANDS[1], http=None, settings=_fake_settings()
    )
    assert calls["n"] == 1


async def test_recommend_respects_concurrency_cap(monkeypatch):
    """동시 실행 상한을 지킨다 — 무제한 병렬은 LLM 레이트리밋·타임아웃을 부른다."""
    live = {"now": 0, "peak": 0}

    async def _slow(http, *, system, history, context, shot_b64, tools, settings):
        live["now"] += 1
        live["peak"] = max(live["peak"], live["now"])
        await asyncio.sleep(0)  # 다른 태스크에 양보
        live["now"] -= 1
        return "submit_recommendations", {"recommendations": []}

    monkeypatch.setattr(recommend, "chat_decide", _slow)
    await recommend.recommend_selections(
        _rows(300), _CANDS[0], _CANDS[1], http=None, settings=_fake_settings()
    )
    assert live["peak"] <= recommend.RECOMMEND_CHUNK_CONCURRENCY


# ══════════════════════════════════════════════════════════════════════════════
# 거래일시 전달(2026-07-27 사용자 리포트)
#   "소풍이라면 10,000원 2026-07-22 18:33:18" 이 '(판)복리후생비-**중식**'으로 추천됐다.
#   그리드에서 TRAN_DT/TRAN_TM 을 읽어두고도 AI 에 보내지 않아 시간대를 알 수 없었다.
# ══════════════════════════════════════════════════════════════════════════════
async def test_recommend_context_includes_transaction_datetime(monkeypatch):
    seen: dict = {}

    async def _capture(http, *, system, history, context, shot_b64, tools, settings):
        seen["rows"] = context["rows"]
        seen["system"] = system
        return "submit_recommendations", {"recommendations": []}

    monkeypatch.setattr(recommend, "chat_decide", _capture)
    rows = [{"no": 1, "merchant": "소풍이라면", "amount": "10,000",
             "vatType": "과세", "date": "2026-07-22", "time": "18:33:18"}]
    await recommend.recommend_selections(
        rows, _CANDS[0], _CANDS[1], http=None, settings=_fake_settings()
    )
    assert seen["rows"][0]["time"] == "18:33:18"
    assert seen["rows"][0]["date"] == "2026-07-22"
    # 시각을 보내는 것만으로는 부족 — 시간대 구분 규칙이 프롬프트에 있어야 한다.
    assert "중식" in seen["system"] and "석식" in seen["system"]


async def test_prefill_builds_rows_with_time_from_grid(monkeypatch):
    """그리드 행(TRAN_DT/TRAN_TM)이 추천 입력의 date/time 으로 전달되는지 — 배선 회귀 방지."""
    from app.agents.card_collect.nodes import prefill as prefill_mod

    captured: dict = {}

    async def _spy(rows, budget_candidates, project_candidates, **kw):
        captured["rows"] = rows
        return {}

    monkeypatch.setattr(prefill_mod, "recommend_selections", _spy)
    src = inspect.getsource(prefill_mod)
    # rec_rows 구성에 TRAN_DT/TRAN_TM 이 실제로 들어가는지(구성 코드 계약).
    assert '"date": r.get("TRAN_DT")' in src
    assert '"time": r.get("TRAN_TM")' in src


async def test_system_prompt_puts_time_above_prior_choice(monkeypatch):
    """⚠ 사고의 실제 경로: priorChoice('중식')를 최우선 채택하라는 지침이 시각을 눌렀다.

    시간대로 나뉘는 계정에서는 **시각이 과거 선택보다 우선**한다는 예외가 명시돼야 한다.
    """
    sys_text = recommend._SYSTEM
    assert "priorChoice" in sys_text
    assert "시간대" in sys_text and "석식" in sys_text
    # 과거 선택 지침보다 **뒤에** 예외가 와야 우선순위가 뒤집히지 않는다.
    assert sys_text.index("priorChoice") < sys_text.index("시간대와 맞지 않으면")


async def test_system_prompt_treats_midnight_as_missing_time():
    """00:00:00 은 자정 결제가 아니라 승인 시각 미전달 — 시각을 근거로 쓰지 말라는 규칙
    (사용자 확정 2026-07-29: 시외버스 승차권 등 00:00 행의 시간대 오판 방지)."""
    sys_text = recommend._SYSTEM
    assert "00:00:00" in sys_text
    assert "전달되지 않은" in sys_text  # 승인 시각 미전달 의미가 명시돼야 한다.
