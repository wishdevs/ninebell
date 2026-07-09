"""출장(국내/자차) params 파싱·유류비 계산·설정 스키마 테스트.

- fuel_support_amount: ROUND_HALF_UP 경계 핀(은행가 반올림 배제), 설정 오버라이드, 비양수 오류.
- parse_trip_params: 정규화 dict 스키마, fuel amount 무시 재계산, 검증 오류(한국어).
- agent_settings: trip-domestic 실효값/검증(5개 number).
"""

from __future__ import annotations

import pytest

from app.agents.trip_domestic.params import (
    DEFAULT_FUEL_NOTE,
    DEFAULT_TOLL_NOTE,
    fuel_support_amount,
    parse_trip_params,
)
from app.services.agent_settings import (
    effective_settings,
    settings_schema_dicts,
    validate_settings,
)

def _classes(**km_by_id: int) -> list[dict]:
    """차량종류 목록 헬퍼 — id=km 매핑을 fuel_classes 행 리스트로(label=id, 계산 테스트용)."""
    return [{"id": cid, "label": cid, "kmPerL": km} for cid, km in km_by_id.items()]


def _settings(unit_price: int = 2000, **km_by_id: int) -> dict:
    """실효 설정 형태({fuel_unit_price, fuel_classes[...]}) 빌더."""
    return {"fuel_unit_price": unit_price, "fuel_classes": _classes(**km_by_id)}


# 실효 설정 기본값(스키마 default 와 동치) — 계산 테스트 기준. 차량종류는 동적 목록.
DEFAULT_SETTINGS = _settings(under1000=14, under1600=9, under2000=7, over2000=6)


# ── fuel_support_amount: 반올림 경계 ─────────────────────────────────────────
def test_fuel_amount_rounds_half_up_fraction():
    # 7km ÷ 9(km/L) × 2000 = 1555.555… → 1556.
    assert fuel_support_amount(7, "under1600", DEFAULT_SETTINGS) == 1556


def test_fuel_amount_exact_half_rounds_up_not_bankers():
    # 4 ÷ 8 × 1 = 0.5. ROUND_HALF_UP → 1. 은행가 반올림이면 0 이 되므로 이 케이스가 핀이다.
    settings = _settings(unit_price=1, under2000=8)
    assert fuel_support_amount(4, "under2000", settings) == 1


def test_fuel_amount_half_at_two_point_five_rounds_up():
    # 20 ÷ 8 × 1 = 2.5. ROUND_HALF_UP → 3(은행가는 2). 두 번째 half 경계 핀.
    settings = _settings(unit_price=1, under2000=8)
    assert fuel_support_amount(20, "under2000", settings) == 3


def test_fuel_amount_exact_integer():
    # 3 ÷ 6 × 2000 = 1000.0 정확.
    assert fuel_support_amount(3, "over2000", DEFAULT_SETTINGS) == 1000


def test_fuel_amount_nonterminating_division_half_boundary():
    # (11×153)/6 = 1683/6 = 280.5 → HALF_UP → 281. 나눗셈 먼저였다면 11/6 이 컨텍스트
    # 정밀도로 반올림돼 280.499… → 280(1원 낮음). 곱셈-먼저 순서 회귀 핀.
    settings = _settings(unit_price=153, over2000=6)
    assert fuel_support_amount(11, "over2000", settings) == 281


def test_fuel_amount_respects_setting_override():
    # 연비 14 → 100÷14×2000 = 14285.71 → 14286.
    assert fuel_support_amount(100, "under1000", DEFAULT_SETTINGS) == 14286
    # 연비를 7 로 낮추면 100÷7×2000 = 28571.43 → 28571(설정 오버라이드 반영).
    overridden = fuel_support_amount(100, "under1000", _settings(under1000=7))
    assert overridden == 28571


@pytest.mark.parametrize("car_class", ["under1000", "under1600", "under2000", "over2000"])
def test_fuel_amount_all_car_classes_use_mapped_eff(car_class):
    amount = fuel_support_amount(50, car_class, DEFAULT_SETTINGS)
    assert amount > 0


def test_fuel_amount_zero_efficiency_raises():
    with pytest.raises(ValueError, match="기준연비"):
        fuel_support_amount(10, "under1600", _settings(under1600=0))


def test_fuel_amount_zero_unit_price_raises():
    with pytest.raises(ValueError, match="기준단가"):
        fuel_support_amount(10, "under1600", _settings(unit_price=0, under1600=9))


def test_fuel_amount_unknown_car_class_raises():
    with pytest.raises(ValueError, match="차량종류"):
        fuel_support_amount(10, "bogus", DEFAULT_SETTINGS)


# ── parse_trip_params: 정규화 ────────────────────────────────────────────────
def _toll_row(**over):
    return {
        "type": "toll",
        "invoiceDate": "2026-07-03",
        "partnerCode": "P001",
        "partnerName": "한국도로공사",
        "amount": 15400,
        "project": {"code": "PJT|WBS", "name": "출장 프로젝트"},
        **over,
    }


def _fuel_row(**over):
    return {
        "type": "fuel",
        "invoiceDate": "2026-07-03",
        "km": 320,
        "carClass": "under1600",
        "project": {"code": "PJT|WBS", "name": "출장 프로젝트"},
        **over,
    }


def test_parse_normalizes_toll_row():
    rows, acct = parse_trip_params({"trip": {"rows": [_toll_row()]}}, DEFAULT_SETTINGS)
    assert acct == "20260703"
    assert rows[0] == {
        "type": "toll",
        "invoiceDate": "20260703",
        "partnerCode": "P001",
        "partnerName": "한국도로공사",
        "amount": 15400,
        "project": {"code": "PJT|WBS", "name": "출장 프로젝트"},
        "note": DEFAULT_TOLL_NOTE,
        "km": None,
        "carClass": None,
    }


def test_parse_derives_acct_date_from_latest_invoice_date():
    # 회계일자 = 계산서일(증빙일) 최댓값. 여러 행 중 가장 마지막일이 회계일.
    rows, acct = parse_trip_params(
        {
            "trip": {
                "rows": [
                    _toll_row(invoiceDate="2026-07-01"),
                    _fuel_row(invoiceDate="2026-07-05"),
                    _toll_row(invoiceDate="2026-07-03"),
                ]
            }
        },
        DEFAULT_SETTINGS,
    )
    assert acct == "20260705"
    assert [r["invoiceDate"] for r in rows] == ["20260701", "20260705", "20260703"]


def test_parse_computes_fuel_amount_and_blanks_partner():
    rows, _ = parse_trip_params(
        {"trip": {"acctDate": "2026-07-03", "rows": [_fuel_row(km=7, carClass="under1600")]}},
        DEFAULT_SETTINGS,
    )
    row = rows[0]
    assert row["type"] == "fuel"
    assert row["partnerCode"] == "" and row["partnerName"] == ""
    assert row["amount"] == 1556  # 7÷9×2000 반올림.
    assert row["km"] == 7 and row["carClass"] == "under1600"
    assert row["note"] == DEFAULT_FUEL_NOTE


def test_parse_ignores_client_fuel_amount_and_recomputes():
    # 클라이언트가 amount 를 실어 보내도 무시하고 재계산한다.
    rows, _ = parse_trip_params(
        {
            "trip": {
                "acctDate": "2026-07-03",
                "rows": [_fuel_row(km=7, carClass="under1600", amount=999999)],
            }
        },
        DEFAULT_SETTINGS,
    )
    assert rows[0]["amount"] == 1556


def test_parse_preserves_project_extra_keys():
    rows, _ = parse_trip_params(
        {
            "trip": {
                "acctDate": "2026-07-03",
                "rows": [_toll_row(project={"code": "PJT|WBS", "name": "P", "wbsNo": "W1"})],
            }
        },
        DEFAULT_SETTINGS,
    )
    assert rows[0]["project"]["wbsNo"] == "W1"


def test_parse_multiple_rows_mixed():
    rows, _ = parse_trip_params(
        {"trip": {"acctDate": "2026-07-03", "rows": [_toll_row(), _fuel_row()]}},
        DEFAULT_SETTINGS,
    )
    assert [r["type"] for r in rows] == ["toll", "fuel"]


# ── parse_trip_params: 검증 오류(한국어) ─────────────────────────────────────
def test_parse_missing_trip_raises():
    with pytest.raises(ValueError, match="출장 입력"):
        parse_trip_params({}, DEFAULT_SETTINGS)


def test_parse_missing_invoice_date_raises():
    row = _toll_row()
    del row["invoiceDate"]
    with pytest.raises(ValueError, match="계산서일"):
        parse_trip_params({"trip": {"rows": [row]}}, DEFAULT_SETTINGS)


def test_parse_empty_rows_raises():
    with pytest.raises(ValueError, match="입력 행이 없습니다"):
        parse_trip_params({"trip": {"acctDate": "2026-07-03", "rows": []}}, DEFAULT_SETTINGS)


def test_parse_toll_missing_partner_raises():
    with pytest.raises(ValueError, match="통행료 행에 거래처가 없습니다"):
        parse_trip_params(
            {"trip": {"acctDate": "2026-07-03", "rows": [_toll_row(partnerCode="", partnerName="")]}},
            DEFAULT_SETTINGS,
        )


def test_parse_toll_nonpositive_amount_raises():
    with pytest.raises(ValueError, match="통행료 금액"):
        parse_trip_params(
            {"trip": {"acctDate": "2026-07-03", "rows": [_toll_row(amount=0)]}}, DEFAULT_SETTINGS
        )


def test_parse_fuel_bad_car_class_raises():
    with pytest.raises(ValueError, match="차량종류"):
        parse_trip_params(
            {"trip": {"acctDate": "2026-07-03", "rows": [_fuel_row(carClass="truck")]}},
            DEFAULT_SETTINGS,
        )


def test_parse_fuel_nonpositive_km_raises():
    with pytest.raises(ValueError, match="주행거리"):
        parse_trip_params(
            {"trip": {"acctDate": "2026-07-03", "rows": [_fuel_row(km=0)]}}, DEFAULT_SETTINGS
        )


def test_parse_missing_project_raises():
    with pytest.raises(ValueError, match="프로젝트가 없습니다"):
        parse_trip_params(
            {"trip": {"acctDate": "2026-07-03", "rows": [_toll_row(project={"code": ""})]}},
            DEFAULT_SETTINGS,
        )


def test_parse_unknown_row_type_raises():
    with pytest.raises(ValueError, match="행 유형"):
        parse_trip_params(
            {"trip": {"acctDate": "2026-07-03", "rows": [{"type": "meal"}]}}, DEFAULT_SETTINGS
        )


# ── agent_settings: trip-domestic 스키마(스칼라 단가 + 동적 차량종류 목록) ────
def test_trip_settings_effective_defaults():
    eff = effective_settings("trip-domestic", None)
    assert eff["fuel_unit_price"] == 2000
    assert [c["id"] for c in eff["fuel_classes"]] == [
        "under1000",
        "under1600",
        "under2000",
        "over2000",
    ]
    assert eff["fuel_classes"][0]["kmPerL"] == 14


def test_trip_settings_overlay_partial():
    eff = effective_settings("trip-domestic", {"fuel_unit_price": 2500})
    assert eff["fuel_unit_price"] == 2500
    assert len(eff["fuel_classes"]) == 4  # 차량종류는 저장 안 하면 기본 4종.


def test_trip_settings_schema_keys():
    # 스칼라 스키마는 기준단가만(차량종류는 동적 목록으로 별도 처리).
    schema = settings_schema_dicts("trip-domestic")
    assert [s["key"] for s in schema] == ["fuel_unit_price"]
    assert all(s["type"] == "number" for s in schema)


def test_trip_settings_validate_ok():
    assert validate_settings("trip-domestic", {"fuel_unit_price": 2500}) == {"fuel_unit_price": 2500}


def test_trip_settings_validate_fuel_classes_ok():
    v = validate_settings(
        "trip-domestic",
        {"fuel_classes": [{"id": "ev", "label": "전기차", "kmPerL": 6}]},
    )
    assert v["fuel_classes"] == [{"id": "ev", "label": "전기차", "kmPerL": 6}]


def test_trip_settings_validate_fuel_classes_empty_raises():
    with pytest.raises(ValueError, match="최소 1개"):
        validate_settings("trip-domestic", {"fuel_classes": []})


def test_trip_settings_validate_fuel_classes_bad_eff_raises():
    with pytest.raises(ValueError, match="기준연비"):
        validate_settings(
            "trip-domestic", {"fuel_classes": [{"id": "x", "label": "x", "kmPerL": 0}]}
        )


def test_trip_settings_validate_fuel_classes_dup_id_raises():
    with pytest.raises(ValueError, match="중복"):
        validate_settings(
            "trip-domestic",
            {"fuel_classes": [
                {"id": "a", "label": "A", "kmPerL": 9},
                {"id": "a", "label": "B", "kmPerL": 8},
            ]},
        )


def test_trip_settings_validate_unit_price_out_of_range():
    with pytest.raises(ValueError, match="기준단가"):
        validate_settings("trip-domestic", {"fuel_unit_price": 99})
