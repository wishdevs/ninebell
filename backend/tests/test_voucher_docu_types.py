"""전표유형 카탈로그 — 62종 상수·프론트 패리티·기본값 보존(2026-08-20 전체 선택 확장)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.agents.voucher_receivable.params import parse_voucher_params
from app.agents.voucher_receivable.steps import (
    DOCU_TYPE_CATALOG,
    DOCU_TYPE_CHOICES,
    DOCU_TYPE_DEFAULTS,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FORM_TSX = _REPO_ROOT / "src" / "components" / "live" / "pre-run" / "voucher-type-pre-run-form.tsx"
_DIAG_JSON = (
    Path(__file__).resolve().parents[1] / "e2e" / "artifacts" / "voucher_receivable_docu_type_diag.json"
)


def test_catalog_matches_erp_diagnostic_dump():
    """상수는 ERP 실측 덤프(SYSDEF_CD/SYSDEF_NM 62행)와 코드·라벨·순서까지 같아야 한다."""
    rows = json.loads(_DIAG_JSON.read_text(encoding="utf-8"))["rows"]
    measured = tuple((str(r["SYSDEF_CD"]).strip(), str(r["SYSDEF_NM"]).strip()) for r in rows)
    assert DOCU_TYPE_CATALOG == measured
    assert len(DOCU_TYPE_CATALOG) == 62
    assert len(set(DOCU_TYPE_CHOICES)) == 62  # 라벨이 유일해야 계약값으로 쓸 수 있다.


def test_defaults_preserve_pre_merge_behaviour():
    # 폼 미지정 시 빌드 기본값 = 병합 전 두 에이전트 조합(회귀 방지).
    assert DOCU_TYPE_DEFAULTS == ("국내매출", "해외매출", "내수구매")
    assert set(DOCU_TYPE_DEFAULTS) <= set(DOCU_TYPE_CHOICES)


def test_frontend_catalog_parity():
    """프론트 DOCU_TYPE_CATALOG 리터럴 = 백엔드 상수(드리프트 감시 — tax-invoice 패리티 관례)."""
    src = _FORM_TSX.read_text(encoding="utf-8")
    block = src.split("DOCU_TYPE_CATALOG", 1)[1].split("];", 1)[0]
    fe = tuple(re.findall(r"code:\s*'([^']+)',\s*label:\s*'([^']+)'", block))
    assert fe == DOCU_TYPE_CATALOG, "전표유형 카탈로그 FE/BE 드리프트"


def test_frontend_default_selection_parity():
    src = _FORM_TSX.read_text(encoding="utf-8")
    m = re.search(r"DEFAULT_DOCU_TYPES: readonly DocuType\[\] = \[(.*?)\];", src, re.DOTALL)
    assert m, "DEFAULT_DOCU_TYPES 리터럴을 찾지 못했습니다"
    fe_defaults = tuple(re.findall(r"'([^']+)'", m.group(1)))
    assert fe_defaults == DOCU_TYPE_DEFAULTS


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
    assert "지원하지 않는 전표유형" in msg and "62종" in msg
    assert "일반전표역분개" not in msg  # 62종 전량 나열 금지(메시지 가독).
