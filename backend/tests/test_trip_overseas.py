"""출장(해외/정산서) — params 정규화·회계일자 파생·검증 오류 + 그래프/등록 테스트.

국내/자차 복사본이라 ERP 스텝(피커·setValue)은 국내 테스트로 커버되고, 여기선 해외 고유분
(유형 없음·공급가액·적요 필수·회계일자 파생·결의구분 라벨·워크플로우 등록)만 검증한다.
"""

from __future__ import annotations

import asyncio

import pytest

from app.agents.trip_overseas.graph import TRIP_GUBUN_LABEL, build_trip_overseas_graph
from app.agents.trip_overseas.nodes.validate import make_validate_params_node
from app.agents.trip_overseas.params import parse_trip_params


def _row(**over) -> dict:
    return {
        "invoiceDate": "2026-04-01",
        "amount": 50000,
        "project": {"code": "800|800", "name": "판매관리비"},
        "note": "해외출장 일비",
        **over,
    }


# ── parse_trip_params: 정규화·파생 ────────────────────────────────────────────
def test_parse_normalizes_row():
    rows, acct = parse_trip_params({"trip": {"rows": [_row()]}}, {})
    assert acct == "20260401"
    assert rows[0] == {
        "invoiceDate": "20260401",
        "amount": 50000,
        "project": {"code": "800|800", "name": "판매관리비"},
        "note": "해외출장 일비",
    }


def test_parse_derives_acct_from_latest_invoice_date():
    rows, acct = parse_trip_params(
        {
            "trip": {
                "rows": [
                    _row(invoiceDate="2026-03-30"),
                    _row(invoiceDate="2026-03-31"),
                    _row(invoiceDate="2026-03-28"),
                ]
            }
        },
        {},
    )
    assert acct == "20260331"  # 마지막 계산서일(출장일)
    assert [r["invoiceDate"] for r in rows] == ["20260330", "20260331", "20260328"]


def test_parse_preserves_project_extra():
    rows, _ = parse_trip_params(
        {"trip": {"rows": [_row(project={"code": "800|800", "name": "P", "wbsNo": "800"})]}}, {}
    )
    assert rows[0]["project"]["wbsNo"] == "800"


# ── parse_trip_params: 검증 오류(한국어) ─────────────────────────────────────
def test_parse_missing_trip_raises():
    with pytest.raises(ValueError, match="출장 입력"):
        parse_trip_params({}, {})


def test_parse_empty_rows_raises():
    with pytest.raises(ValueError, match="입력 행이 없습니다"):
        parse_trip_params({"trip": {"rows": []}}, {})


def test_parse_nonpositive_amount_raises():
    with pytest.raises(ValueError, match="공급가액"):
        parse_trip_params({"trip": {"rows": [_row(amount=0)]}}, {})


def test_parse_missing_project_raises():
    with pytest.raises(ValueError, match="프로젝트가 없습니다"):
        parse_trip_params({"trip": {"rows": [_row(project={"code": ""})]}}, {})


def test_parse_missing_invoice_date_raises():
    row = _row()
    del row["invoiceDate"]
    with pytest.raises(ValueError, match="계산서일"):
        parse_trip_params({"trip": {"rows": [row]}}, {})


def test_parse_missing_note_raises():
    with pytest.raises(ValueError, match="적요"):
        parse_trip_params({"trip": {"rows": [_row(note="")]}}, {})


# ── validate_params 노드 ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_validate_node_success():
    node = make_validate_params_node()
    params = {"department": "회계팀", "cost_type": "판관비", "trip": {"rows": [_row()]}}
    out = await node({"events": asyncio.Queue(), "params": params})
    assert "error" not in out
    assert out["acct_date_compact"] == "20260401"
    assert out["department"] == "회계팀" and out["cost_type"] == "판관비"
    assert len(out["plan_rows"]) == 1


@pytest.mark.asyncio
async def test_validate_node_missing_cost_type_errors():
    node = make_validate_params_node()
    params = {"department": "회계팀", "trip": {"rows": [_row()]}}
    out = await node({"events": asyncio.Queue(), "params": params})
    assert "비용구분" in out["error"]


# ── 결의구분 라벨 + 등록 ──────────────────────────────────────────────────────
def test_gubun_label_is_overseas():
    assert TRIP_GUBUN_LABEL == "출장(해외·정산서)"


def test_graph_compiles():
    assert build_trip_overseas_graph() is not None


def test_registered_in_workflow_registry():
    import app.agents  # noqa: F401 — import 시 register_workflow 트리거

    from app.live.registry import get_spec

    spec = get_spec("trip-overseas")
    assert spec is not None
    assert spec.needs_browser is True
    assert spec.delay_scale == 0.4


def test_fixture_promoted_from_dummy():
    from app.services.agent_fixtures import AGENT_FIXTURES

    fx = next((f for f in AGENT_FIXTURES if f["id"] == "trip-overseas"), None)
    assert fx is not None
    assert fx["workflow_id"] == "trip-overseas"  # 더미(None)에서 승격
    assert fx["interaction"] == "autonomous"
    assert fx["group_id"] == "resolution"
    assert fx["hidden"] is True  # 라이브 프로브 전까지 숨김(카드·국내출장만 노출)
    assert fx["flow_graph"] is not None
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
