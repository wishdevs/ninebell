"""전표유형 카탈로그(docu_types) — 실측 덤프 일치·재노출 호환·params 계약(2026-08-20 62종 확장).

프론트 리터럴 패리티는 없다 — 폼은 settings.docu_type_choices(백엔드 직렬화)로 렌더하며,
그 직렬화는 test_agent_settings 의 docu_type_choices 테스트가 커버한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.voucher_receivable import steps
from app.agents.voucher_receivable.docu_types import (
    DOCU_TYPE_CATALOG,
    DOCU_TYPE_CHOICES,
    DOCU_TYPE_DEFAULT,
)
from app.agents.voucher_receivable.params import parse_voucher_params

_DIAG_JSON = (
    Path(__file__).resolve().parents[1]
    / "e2e"
    / "artifacts"
    / "voucher_receivable_docu_type_diag.json"
)


@pytest.mark.skipif(not _DIAG_JSON.exists(), reason="실측 덤프(e2e 아티팩트) 없는 환경")
def test_catalog_matches_erp_diagnostic_dump():
    """상수는 ERP 실측 덤프(SYSDEF_CD/SYSDEF_NM 62행)와 코드·라벨·순서까지 같아야 한다."""
    rows = json.loads(_DIAG_JSON.read_text(encoding="utf-8"))["rows"]
    measured = tuple((str(r["SYSDEF_CD"]).strip(), str(r["SYSDEF_NM"]).strip()) for r in rows)
    assert DOCU_TYPE_CATALOG == measured
    assert len(DOCU_TYPE_CATALOG) == 62
    assert len(set(DOCU_TYPE_CHOICES)) == 62  # 라벨이 유일해야 계약값으로 쓸 수 있다.


def test_steps_reexports_catalog_choices():
    # steps 는 하위호환 재노출만 한다 — 단일 소스는 docu_types 모듈(드리프트 금지).
    assert steps.DOCU_TYPE_CHOICES is DOCU_TYPE_CHOICES
    assert DOCU_TYPE_DEFAULT == ("국내매출", "해외매출", "내수구매")


def test_params_accepts_any_catalog_label():
    plan = parse_voucher_params(
        {"voucher": {"period_from": "2026-08-01", "period_to": "2026-08-31",
                     "docu_types": ["급여", "리스임차", "전자상거래 국내매출"]}}
    )
    assert plan.docu_types == ["급여", "리스임차", "전자상거래 국내매출"]


def test_params_rejects_unknown_label_with_short_message():
    with pytest.raises(ValueError) as err:
        parse_voucher_params(
            {"voucher": {"period_from": "2026-08-01", "period_to": "2026-08-31",
                         "docu_types": ["없는유형"]}}
        )
    msg = str(err.value)
    assert "지원하지 않는 전표유형" in msg
    assert "일반전표역분개" not in msg  # 62종 전량 나열 금지(메시지 가독).
