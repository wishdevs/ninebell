"""FE 미러 ↔ BE 원본 패리티 — 프론트가 백엔드 업무규칙을 리터럴로 미러한 4곳의 드리프트 감시.

미러는 미리보기/개입 UX 용이라 계산 권위는 항상 백엔드지만, 값이 갈라지면 사용자가
화면에서 본 것과 실제 저장이 달라진다(실사례: b91ccfc 가 백엔드 불공 계정에
차량유지비-관리·기부금을 추가했는데 FE 미러는 갱신 누락). FE 소스에서 리터럴을 기계적으로
떼어내 백엔드 원본과 대조한다(test_card_note_sanitize 의 마이그레이션↔코드 패리티 선례와
동일한 접근) — ①②③ 은 TSX/TS 정규식 추출, ④ 는 기본값이 JSON 파일이라 json.load 직독이다.

  ① LiveGridCard.tsx 불공제 계정 목록      ↔ app/agents/card_collect/vat.py
  ② fuel-calc.ts DEFAULT_FUEL_CLASSES     ↔ app/services/agent_settings.py
  ③ gyeongjo-pre-run-form.tsx supplyAmount ↔ app/agents/gyeongjo_grant/params.py
  ④ order-patterns.default.json 기본 9그룹 ↔ app/services/agent_settings.py
  ⑤ vendor-options.default.json 거래처 후보 ↔ app/services/agent_settings.py
"""

from __future__ import annotations

import json
import re
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

from app.agents.card_collect.vat import _NONDEDUCTIBLE_ACCTS, _NONDEDUCTIBLE_CONTAINS
from app.agents.gyeongjo_grant.params import supply_amount
from app.services.agent_settings import (
    DEFAULT_FUEL_CLASSES,
    DEFAULT_ORDER_PATTERNS,
    DEFAULT_VENDOR_OPTIONS,
    MAX_GROUP_EXCEPTIONS,
    MAX_GROUP_MODULES,
    MAX_OFFSET_WEEKS,
    MAX_PATTERN_GROUPS,
    ORDER_PATTERNS_KEY,
)

# backend/tests/ → 저장소 루트 → FE 소스. 파일 이동 시 여기만 고치면 된다.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIVE_GRID_CARD = _REPO_ROOT / "src" / "components" / "live" / "LiveGridCard.tsx"
_FUEL_CALC = _REPO_ROOT / "src" / "lib" / "trip" / "fuel-calc.ts"
_GYEONGJO_FORM = _REPO_ROOT / "src" / "components" / "live" / "pre-run" / "gyeongjo-pre-run-form.tsx"
_ORDER_PATTERNS_TS = _REPO_ROOT / "src" / "lib" / "purchase" / "order-patterns.ts"
_ORDER_PATTERNS_JSON = _REPO_ROOT / "src" / "lib" / "purchase" / "order-patterns.default.json"
_VENDOR_OPTIONS_JSON = _REPO_ROOT / "src" / "lib" / "purchase" / "vendor-options.default.json"


def _read(path: Path) -> str:
    assert path.is_file(), f"FE 미러 소스가 없습니다(이동/삭제 시 테스트 경로 갱신 필요): {path}"
    return path.read_text(encoding="utf-8")


# ── ① 불공제 계정 판정(LiveGridCard.tsx ↔ vat.py) ─────────────────────────────
def test_nondeductible_accts_mirror_parity():
    """FE NONDEDUCTIBLE_ACCTS(정확일치 목록)가 백엔드 _NONDEDUCTIBLE_ACCTS 와 동일해야 한다."""
    src = _read(_LIVE_GRID_CARD)
    m = re.search(r"NONDEDUCTIBLE_ACCTS = new Set\(\s*\[(.*?)\]\.map", src, re.DOTALL)
    assert m, "LiveGridCard.tsx 에서 NONDEDUCTIBLE_ACCTS 배열 리터럴을 찾지 못했습니다(형태 변경 시 정규식 갱신)"
    fe = re.findall(r"'([^']+)'", m.group(1))
    assert fe, "NONDEDUCTIBLE_ACCTS 항목 추출 실패"
    assert set(fe) == set(_NONDEDUCTIBLE_ACCTS), (
        "불공제 계정(정확일치) FE/BE 드리프트 — 한쪽만 고치면 화면 미리보기와 실제 저장이 갈라집니다.\n"
        f"  FE(LiveGridCard.tsx): {sorted(fe)}\n  BE(vat.py): {sorted(_NONDEDUCTIBLE_ACCTS)}"
    )


def test_nondeductible_contains_mirror_parity():
    """FE NONDEDUCTIBLE_CONTAINS(부분일치 — 접대비 계열)가 백엔드와 동일해야 한다."""
    src = _read(_LIVE_GRID_CARD)
    m = re.search(r"NONDEDUCTIBLE_CONTAINS = \[(.*?)\];", src, re.DOTALL)
    assert m, "LiveGridCard.tsx 에서 NONDEDUCTIBLE_CONTAINS 리터럴을 찾지 못했습니다"
    fe = re.findall(r"'([^']+)'", m.group(1))
    assert set(fe) == set(_NONDEDUCTIBLE_CONTAINS), (
        f"불공제 부분일치 키워드 FE/BE 드리프트 — FE: {sorted(fe)} / BE: {sorted(_NONDEDUCTIBLE_CONTAINS)}"
    )


# ── ② 차량종류 기본 4종(fuel-calc.ts ↔ agent_settings.py) ────────────────────
def test_default_fuel_classes_mirror_parity():
    """FE DEFAULT_FUEL_CLASSES(id·label·kmPerL)가 백엔드 기본 목록과 순서까지 동일해야 한다."""
    src = _read(_FUEL_CALC)
    m = re.search(r"DEFAULT_FUEL_CLASSES[^=]*=\s*\[(.*?)\n\];", src, re.DOTALL)
    assert m, "fuel-calc.ts 에서 DEFAULT_FUEL_CLASSES 배열 리터럴을 찾지 못했습니다"
    fe_rows = [
        {"id": i, "label": label, "kmPerL": int(km)}
        for i, label, km in re.findall(
            r"\{\s*id:\s*'([^']+)',\s*label:\s*'([^']+)',\s*kmPerL:\s*(\d+)\s*\}", m.group(1)
        )
    ]
    assert fe_rows, "DEFAULT_FUEL_CLASSES 행 추출 실패(행 형태 변경 시 정규식 갱신)"
    # id 는 실행 전 폼 제출값이라 순서·내용 모두 일치해야 한다(리스트 비교).
    assert fe_rows == DEFAULT_FUEL_CLASSES, (
        "기본 차량종류 FE/BE 드리프트 — 폼 미리보기(연비)와 백엔드 확정 계산이 갈라집니다.\n"
        f"  FE(fuel-calc.ts): {fe_rows}\n  BE(agent_settings.py): {DEFAULT_FUEL_CLASSES}"
    )


# ── ③ 경조금 공급가액 라운딩(gyeongjo-pre-run-form.tsx ↔ params.py) ───────────
def _fe_supply_multiplier() -> str:
    """FE supplyAmount 의 half-up 식(`Math.round(baseAmount * X)`)에서 배수 리터럴을 추출한다.

    식 형태 자체(삼항 + Math.round)가 백엔드 ROUND_HALF_UP 과의 동치 근거이므로,
    형태가 바뀌면 추출 실패로 테스트가 깨져 사람이 다시 검증하게 된다.
    """
    src = _read(_GYEONGJO_FORM)
    m = re.search(
        r"return under1Year \? Math\.round\(baseAmount \* ([0-9.]+)\) : baseAmount;", src
    )
    assert m, (
        "gyeongjo-pre-run-form.tsx 의 supplyAmount 식이 예상 형태"
        "(`under1Year ? Math.round(baseAmount * X) : baseAmount`)가 아닙니다 — 백엔드와 동치인지 재검증 필요"
    )
    return m.group(1)


def test_gyeongjo_supply_multiplier_literal_parity():
    """FE 배수 리터럴이 백엔드 supply_amount 의 Decimal 배수 리터럴과 동일해야 한다."""
    fe_mult = _fe_supply_multiplier()
    be_src = (Path(__file__).resolve().parents[1] / "app" / "agents" / "gyeongjo_grant" / "params.py").read_text(
        encoding="utf-8"
    )
    m = re.search(r'\* Decimal\("([0-9.]+)"\)', be_src)
    assert m, "params.py 에서 supply_amount 배수 리터럴(Decimal(\"X\"))을 찾지 못했습니다"
    assert fe_mult == m.group(1), f"공급가액 배수 드리프트 — FE: {fe_mult} / BE: {m.group(1)}"


@pytest.mark.parametrize(
    "base",
    [1, 2, 3, 99, 100_000, 100_001, 100_003, 99_999_999, 100_000_000],
)
def test_gyeongjo_supply_amount_rounding_parity(base):
    """백엔드 supply_amount(ROUND_HALF_UP)가 FE Math.round(양수 half-up)와 .5 경계 포함 동일해야 한다."""
    fe_mult = Decimal(_fe_supply_multiplier())
    # JS Math.round(x) = floor(x + 0.5) (양수 구간) — Decimal 로 정확히 재현.
    js_round = int(
        (Decimal(base) * fe_mult + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR)
    )
    be = supply_amount(base, True)
    assert be == js_round, f"근속<1년 공급가액 라운딩 드리프트(base={base}) — BE: {be} / FE(JS): {js_round}"
    # 참조 검증: BE 자체도 ROUND_HALF_UP 정의와 일치(테스트 자기 무결성).
    ref = int((Decimal(base) * fe_mult).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    assert be == ref
    # 근속 1년 이상은 양쪽 다 정액 그대로(FE 삼항의 else 분기 = 항등).
    assert supply_amount(base, False) == base


# ── ④ 발주 패턴 기본 9그룹(order-patterns.default.json ↔ agent_settings.py) ───
# v2 부터 기본값의 **단일 소스는 JSON 파일**이다 — FE 는 그 파일을 typed import 하고, BE 는
# 배포 이미지에 src/ 가 없어 같은 값을 파이썬 리터럴로 들고 있다. 그래서 여기서는 TS 리터럴을
# 파싱할 필요가 없다(v1 의 괄호 매칭 파서는 중첩 구조를 감당하지 못해 통째로 폐기했다):
# json.load 로 읽어 백엔드 리터럴과 **재귀 완전 동등** 비교한다.


def _tree_diffs(fe: object, be: object, path: str) -> list[str]:
    """두 구조의 불일치 지점을 경로와 함께 모은다 — 9그룹 통짜 diff 는 읽을 수 없다."""
    if isinstance(fe, dict) and isinstance(be, dict):
        out: list[str] = []
        for key in sorted(set(fe) | set(be), key=str):
            if key not in fe:
                out.append(f"{path}.{key}: FE 없음 / BE={be[key]!r}")
            elif key not in be:
                out.append(f"{path}.{key}: FE={fe[key]!r} / BE 없음")
            else:
                out += _tree_diffs(fe[key], be[key], f"{path}.{key}")
        return out
    if isinstance(fe, list) and isinstance(be, list):
        out = []
        if len(fe) != len(be):
            out.append(f"{path}: 길이 FE={len(fe)} / BE={len(be)}")
        for i, (fe_item, be_item) in enumerate(zip(fe, be)):
            out += _tree_diffs(fe_item, be_item, f"{path}[{i}]")
        return out
    return [] if fe == be else [f"{path}: FE={fe!r} / BE={be!r}"]


def test_default_order_patterns_json_parity():
    """order-patterns.default.json 9그룹이 백엔드 DEFAULT_ORDER_PATTERNS 와 완전히 같아야 한다.

    관리자가 패턴을 한 번도 저장하지 않은 상태에서는 이 기본값이 곧 계획서의 발주단위 편성
    결과이므로, 갈라지면 화면에서 편성된 발주단위와 백엔드가 아는 패턴이 달라진다.
    """
    fe = json.loads(_read(_ORDER_PATTERNS_JSON))
    assert isinstance(fe, dict) and isinstance(fe.get("groups"), list), (
        "order-patterns.default.json 이 {\"groups\": [...]} 형태가 아닙니다"
    )
    fe_ids = [g.get("id") for g in fe["groups"]]
    be_ids = [g["id"] for g in DEFAULT_ORDER_PATTERNS["groups"]]
    assert fe_ids == be_ids, (
        f"기본 발주그룹의 id·순서 드리프트 — FE: {fe_ids} / BE: {be_ids}"
    )
    # 그룹별로 훑어 어느 그룹의 어느 경로가 어긋났는지 바로 드러나게 한다.
    diffs: list[str] = []
    for fe_group, be_group in zip(fe["groups"], DEFAULT_ORDER_PATTERNS["groups"]):
        diffs += _tree_diffs(fe_group, be_group, f"groups[{be_group['id']}]")
    assert not diffs, (
        "기본 발주그룹 FE/BE 드리프트 — 한쪽만 고치면 계획서 편성과 백엔드 기본값이 갈라집니다.\n  "
        + "\n  ".join(diffs)
    )
    # groups 밖의 키(향후 확장)까지 포함한 최종 동등성.
    assert fe == DEFAULT_ORDER_PATTERNS


def _ts_const(src: str, name: str) -> str | int:
    """order-patterns.ts 의 `export const NAME = 'str' | 123;` 리터럴 값을 뽑는다."""
    m = re.search(rf"export const {name} = (?:'([^']*)'|(\d+));", src)
    assert m, f"order-patterns.ts 에서 {name} 선언을 찾지 못했습니다(형태 변경 시 정규식 갱신)"
    return m.group(1) if m.group(1) is not None else int(m.group(2))


def test_order_patterns_constants_parity():
    """settings 키와 한도 4종이 갈라지면 관리자가 저장한 패턴을 백엔드가 거부하거나 잘라먹는다."""
    src = _read(_ORDER_PATTERNS_TS)
    expected: dict[str, str | int] = {
        "ORDER_PATTERNS_KEY": ORDER_PATTERNS_KEY,
        "MAX_PATTERN_GROUPS": MAX_PATTERN_GROUPS,
        "MAX_GROUP_MODULES": MAX_GROUP_MODULES,
        "MAX_GROUP_EXCEPTIONS": MAX_GROUP_EXCEPTIONS,
        "MAX_OFFSET_WEEKS": MAX_OFFSET_WEEKS,
    }
    drift = {
        name: (_ts_const(src, name), be)
        for name, be in expected.items()
        if _ts_const(src, name) != be
    }
    assert not drift, f"발주 패턴 상수 드리프트 — {{이름: (FE, BE)}} = {drift}"


# ── ⑤ 통합 지정 거래처 후보 기본값(vendor-options.default.json ↔ agent_settings.py) ──
def test_vendor_options_defaults_mirror_parity():
    """FE 기본 거래처 후보 JSON 이 백엔드 DEFAULT_VENDOR_OPTIONS 와 재귀 동일해야 한다."""
    fe = json.loads(_read(_VENDOR_OPTIONS_JSON))
    assert fe == DEFAULT_VENDOR_OPTIONS, (
        "거래처 후보 기본값 FE/BE 드리프트 — 계획서 콤보박스와 저장 폴백이 갈라집니다.\n"
        f"  FE(vendor-options.default.json): {fe}\n  BE(agent_settings.py): {DEFAULT_VENDOR_OPTIONS}"
    )
