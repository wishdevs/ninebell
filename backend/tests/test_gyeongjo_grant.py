"""경조금신청서(gyeongjo-grant) — params(단건·근속<1년 50% 계산)·검증·그래프/등록·픽스처 lockstep.

detail ERP 스텝(피커·setValue·타이핑)은 국내출장 스텝을 재사용하므로 국내출장 테스트로 커버되고,
여기선 경조금 고유분(단건 스키마·50% 반값 원단위 반올림·예산계정명 '복리후생비-경조'·회계일=증빙일·
결의구분 라벨·State 계약·워크플로우 등록·픽스처 steps↔그래프 노드 순서 일치)만 검증한다.
"""

from __future__ import annotations

import asyncio

import pytest

from app.agents.gyeongjo_grant.graph import (
    GYEONGJO_GUBUN_LABEL,
    GyeongjoGrantState,
    build_gyeongjo_grant_graph,
)
from app.agents.gyeongjo_grant.nodes import fill
from app.agents.gyeongjo_grant.nodes.fill import make_fill_rows_node
from app.agents.gyeongjo_grant.nodes.validate import make_validate_params_node
from app.agents.gyeongjo_grant.params import parse_gyeongjo_params, supply_amount
from app.agents.gyeongjo_grant.steps import bgacct_name_for_cost_type
from tests.support.state_contract import assert_keys_declared


def _gj(**over) -> dict:
    return {
        "evidenceDate": "2026-07-13",
        "baseAmount": 200_000,
        "under1Year": False,
        "project": {"code": "800|800", "name": "판매관리비"},
        **over,
    }


# ── supply_amount: 근속<1년 50% 계산(round, 원 단위 반올림) ──────────────────────
def test_supply_amount_full_when_not_under1year():
    assert supply_amount(200_000, False) == 200_000


def test_supply_amount_half_when_under1year():
    assert supply_amount(200_000, True) == 100_000


def test_supply_amount_half_rounds_to_won():
    # 100,003 × 0.5 = 50,001.5 → 원 단위 반올림 = 50,002(이 값은 은행가·사사오입 둘 다 50,002라
    # 우연히 일치 — ROUND_HALF_UP 강제 검증은 아래 경계값 테스트가 담당).
    assert supply_amount(100_003, True) == 50_002


@pytest.mark.parametrize("base_amount,expected", [(100_001, 50_001), (300_001, 150_001)])
def test_supply_amount_half_forces_round_half_up(base_amount, expected):
    # .5 경계에서 ROUND_HALF_UP(사사오입) 강제. 내장 round()(은행가 반올림)면 짝수로 내려가
    # 50,000 / 150,000 이 나온다 → 이 테스트가 실패한다. 즉 이 단언이 round-half-to-even 회귀를 막는다.
    #   100,001 × 0.5 = 50,000.5  → 사사오입 50,001 (은행가 50,000)
    #   300,001 × 0.5 = 150,000.5 → 사사오입 150,001 (은행가 150,000)
    assert supply_amount(base_amount, True) == expected


def test_supply_amount_full_when_under1year_false_at_boundary():
    # under1Year=False 는 경계값이어도 반올림 없이 정액 그대로.
    assert supply_amount(100_001, False) == 100_001


def test_supply_amount_returns_int():
    assert isinstance(supply_amount(200_000, True), int)


# ── parse_gyeongjo_params: 단건 정규화·회계일=증빙일 ──────────────────────────
def test_parse_normalizes_single_row():
    rows, acct = parse_gyeongjo_params({"gyeongjo": _gj()})
    assert acct == "20260713"  # 회계일 = 증빙일(그대로).
    assert len(rows) == 1
    assert rows[0]["invoiceDate"] == "20260713"
    assert rows[0]["amount"] == 200_000
    assert rows[0]["project"] == {"code": "800|800", "name": "판매관리비"}


def test_parse_acct_equals_evidence_date():
    _, acct = parse_gyeongjo_params({"gyeongjo": _gj(evidenceDate="2026-05-01")})
    assert acct == "20260501"


def test_parse_applies_half_when_under1year():
    rows, _ = parse_gyeongjo_params({"gyeongjo": _gj(baseAmount=200_000, under1Year=True)})
    assert rows[0]["amount"] == 100_000  # 반값 확정값이 행 amount 에 실린다.
    assert rows[0]["baseAmount"] == 200_000  # 정액 원본 보존(요약용).


def test_parse_defaults_under1year_false():
    rows, _ = parse_gyeongjo_params({"gyeongjo": {k: v for k, v in _gj().items() if k != "under1Year"}})
    assert rows[0]["amount"] == 200_000  # under1Year 기본 False → 정액 그대로.


def test_parse_preserves_project_extra():
    rows, _ = parse_gyeongjo_params(
        {"gyeongjo": _gj(project={"code": "800|800", "name": "P", "wbsNo": "800"})}
    )
    assert rows[0]["project"]["wbsNo"] == "800"


# ── parse_gyeongjo_params: 검증 오류(한국어) ─────────────────────────────────
def test_parse_missing_gyeongjo_raises():
    with pytest.raises(ValueError, match="경조금 입력"):
        parse_gyeongjo_params({})


def test_parse_nonpositive_amount_raises():
    with pytest.raises(ValueError, match="정액"):
        parse_gyeongjo_params({"gyeongjo": _gj(baseAmount=0)})


def test_parse_missing_project_raises():
    with pytest.raises(ValueError, match="프로젝트"):
        parse_gyeongjo_params({"gyeongjo": _gj(project={"code": ""})})


def test_parse_missing_evidence_date_raises():
    gj = _gj()
    del gj["evidenceDate"]
    with pytest.raises(ValueError, match="증빙일"):
        parse_gyeongjo_params({"gyeongjo": gj})


# ── 예산계정명(D8): base "복리후생비-경조" ────────────────────────────────────
def test_bgacct_name_pankwan():
    assert bgacct_name_for_cost_type("판관비") == "(판)복리후생비-경조"


def test_bgacct_name_jejo():
    assert bgacct_name_for_cost_type("제조원가") == "(제)복리후생비-경조"


def test_bgacct_name_unknown_raises():
    with pytest.raises(ValueError, match="비용구분"):
        bgacct_name_for_cost_type("기타")


# ── validate_params 노드(코루틴 직접 호출) ────────────────────────────────────
@pytest.mark.asyncio
async def test_validate_node_success():
    node = make_validate_params_node()
    params = {"department": "회계팀", "cost_type": "판관비", "gyeongjo": _gj()}
    out = await node({"events": asyncio.Queue(), "params": params})
    assert "error" not in out
    assert out["acct_date_compact"] == "20260713"
    assert out["department"] == "회계팀" and out["cost_type"] == "판관비"
    assert len(out["plan_rows"]) == 1
    # 노드 출력 키가 State 에 전부 선언됐는지(LangGraph silent drop 방지).
    assert_keys_declared(GyeongjoGrantState, out)


@pytest.mark.asyncio
async def test_validate_node_missing_department_errors():
    node = make_validate_params_node()
    params = {"cost_type": "판관비", "gyeongjo": _gj()}
    out = await node({"events": asyncio.Queue(), "params": params})
    assert "부서" in out["error"]


@pytest.mark.asyncio
async def test_validate_node_missing_cost_type_errors():
    node = make_validate_params_node()
    params = {"department": "회계팀", "gyeongjo": _gj()}
    out = await node({"events": asyncio.Queue(), "params": params})
    assert "비용구분" in out["error"]


@pytest.mark.asyncio
async def test_validate_node_invalid_params_short_circuits():
    node = make_validate_params_node()
    params = {"department": "회계팀", "cost_type": "판관비", "gyeongjo": _gj(baseAmount=0)}
    out = await node({"events": asyncio.Queue(), "params": params})
    assert "정액" in out["error"]


# ── 결의구분 라벨 + 그래프 + 등록 ─────────────────────────────────────────────
def test_gubun_label_is_gyeongjo():
    assert GYEONGJO_GUBUN_LABEL == "경조금신청서"


def test_graph_compiles():
    assert build_gyeongjo_grant_graph() is not None


def test_registered_in_workflow_registry():
    import app.agents  # noqa: F401 — import 시 register_workflow 트리거

    from app.live.registry import get_spec

    spec = get_spec("gyeongjo-grant")
    assert spec is not None
    assert spec.needs_browser is True
    assert spec.delay_scale == 0.4
    assert spec.site == "omnisol"


# ── 픽스처 steps ↔ 그래프 노드 순서 lockstep ─────────────────────────────────
def test_fixture_promoted_from_dummy():
    from app.services.agent_fixtures import AGENT_FIXTURES

    fx = next((f for f in AGENT_FIXTURES if f.get("workflow_id") == "gyeongjo-grant"), None)
    assert fx is not None  # family-event 더미에서 승격.
    assert fx["interaction"] == "autonomous"
    assert fx["group_id"] == "resolution"
    assert fx["flow_graph"] is not None
    assert fx.get("handoff_note")  # 상신 수동 안내.
    # steps 의 key 순서는 build_gyeongjo_grant_graph 의 노드 등록 순서와 정확히 일치해야 한다.
    step_keys = [s["key"] for s in fx["steps"]]
    assert step_keys == [
        "validate_params",
        "login",
        "user_type",
        "menu_nav",
        "set_gubun",
        "add_row",
        "set_acct_date",
        "fill_rows",
        "save_doc",
    ]


# ── fill_rows 노드(스텝 monkeypatch — 브라우저 없이 계약·분기 검증) ────────────────
# detail ERP 스텝은 국내출장 재사용이라 trip 테스트가 커버하지만, 경조금 fill 노드 고유 조립
# (단건 채움 순서·거래처 본인검색 분기·적요 '경조금-{본인이름}'·실패 단락·State 계약)은 여기서 강제한다.
class _FakePage:
    """fill_rows 는 모든 detail 조작을 steps/doc_steps 로 위임(스텁)하므로 page.evaluate 는 직접
    호출하지 않는다. screenshot 미구현이라 emit_shot 은 우아하게 생략된다(캡처 실패 → None)."""

    async def evaluate(self, js_src, arg=None):
        return {"ok": True, "after": str(arg)}

    async def wait_for_timeout(self, ms):
        return None


def _patch_fill_all_ok(monkeypatch, calls: list, notes: list):
    """모든 detail 스텝을 ok 로 스텁 — 호출 순서를 calls 에, 적요 텍스트를 notes 에 기록.

    거래처 본인검색(fill_partner_by_search)은 로그인 계정과 **다른** 표시명('홍길동')을 돌려줘,
    적요가 userid 가 아니라 본인검색 결과 이름으로 조립되는지 구분 검증되게 한다.
    """

    def _rec(name, extra=None):
        async def _f(*a, **k):
            calls.append(name)
            return {"ok": True, **(extra or {})}

        return _f

    async def _rec_note(page, text):
        calls.append("set_row_note")
        notes.append(text)
        return {"ok": True}

    monkeypatch.setattr(fill.doc_steps, "open_evdn_editor", _rec("open_evdn", {"shown": {}}))
    monkeypatch.setattr(fill.doc_steps, "select_evdn_code", _rec("select_evdn", {"name": "규정에의한 비용정산", "code": "10"}))
    monkeypatch.setattr(fill.steps, "set_invoice_date", _rec("set_invoice_date"))
    monkeypatch.setattr(fill.steps, "fill_partner_by_search", _rec("fill_partner_by_search", {"name": "홍길동"}))
    monkeypatch.setattr(fill.steps, "fill_budget_fixed", _rec("fill_budget"))
    monkeypatch.setattr(fill.steps, "fill_project", _rec("fill_project"))
    monkeypatch.setattr(fill.steps, "type_amount", _rec("type_amount"))
    monkeypatch.setattr(fill.steps, "set_row_note", _rec_note)
    monkeypatch.setattr(fill.steps, "set_master_total", _rec("set_master_total"))


def _fill_state(**over) -> dict:
    state = {
        "events": asyncio.Queue(),
        "page": _FakePage(),
        "userid": "이트라이브2계정",  # 로그인 계정 id — 표시명(홍길동)과 다름.
        "department": "회계팀",
        "cost_type": "판관비",
        "plan_rows": [
            {
                "invoiceDate": "20260713",
                "amount": 100_000,  # 근속<1년 반값 확정 공급가액.
                "project": {"code": "800|800", "name": "판매관리비"},
                "baseAmount": 200_000,
                "under1Year": True,
            }
        ],
    }
    state.update(over)
    return state


@pytest.mark.asyncio
async def test_fill_rows_single_row_success(monkeypatch):
    calls: list = []
    notes: list = []
    _patch_fill_all_ok(monkeypatch, calls, notes)
    node = make_fill_rows_node()
    out = await node(_fill_state())
    assert out["filled"] == 1 and out["fill_failures"] == []
    assert_keys_declared(GyeongjoGrantState, out)
    # 단건 — 각 스텝 정확히 1회(다행 F3 루프 없음).
    assert calls.count("type_amount") == 1
    assert calls.count("set_invoice_date") == 1
    assert calls.count("set_master_total") == 1
    # 거래처 = 작성자 본인 검색(통행료 fill_partner 아님).
    assert "fill_partner_by_search" in calls
    # 적요 = '경조금-{본인이름}' — userid('이트라이브2계정') 가 아니라 본인검색 표시명('홍길동')으로 조립(D7).
    assert notes == ["경조금-홍길동"]
    # 상대계정거래처는 경조금엔 불필요 — fill 에서 제거됨(2026-07-13 사용자 확정).
    assert "register_counter_partner" not in calls and "delete_blank_row" not in calls


@pytest.mark.asyncio
async def test_fill_rows_field_failure_reports_field_and_short_circuits(monkeypatch):
    calls: list = []
    notes: list = []
    _patch_fill_all_ok(monkeypatch, calls, notes)

    async def _fail_budget(*a, **k):
        return {"ok": False, "reason": "예산단위 조합 무매칭: 회계팀 · (판)복리후생비-경조"}

    monkeypatch.setattr(fill.steps, "fill_budget_fixed", _fail_budget)
    node = make_fill_rows_node()
    out = await node(_fill_state())
    assert "예산단위" in out["error"]
    assert out["fill_failures"] == [
        {"row": 1, "field": "예산단위", "reason": "예산단위 조합 무매칭: 회계팀 · (판)복리후생비-경조"}
    ]
    # 예산단위 실패 → 이후 스텝(프로젝트·금액·적요) 미호출(조기 반환).
    assert "fill_project" not in calls
    assert "type_amount" not in calls
    assert notes == []
    assert_keys_declared(GyeongjoGrantState, out)


@pytest.mark.asyncio
async def test_fill_rows_requires_self_name(monkeypatch):
    calls: list = []
    notes: list = []
    _patch_fill_all_ok(monkeypatch, calls, notes)
    node = make_fill_rows_node()
    out = await node(_fill_state(userid=""))
    assert "본인 이름" in out["error"]
    assert calls == []  # 본인 이름 없으면 어떤 detail 스텝도 호출하지 않는다.
