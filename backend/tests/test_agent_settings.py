"""에이전트별 세부설정 테스트 — 선언 스키마·실효값·admin PATCH·런 파라미터 주입.

- effective_settings: 저장값 없음=스키마 기본값, 부분 저장=오버레이(미지 키 무시).
- GET /agents: 스키마 있는 에이전트(corporate-card)만 settings/settingsSchema 포함.
- PATCH /agents/{id}/settings: admin 200(값 반영), user 403, 범위 밖·미지 키·스키마 없음 400,
  없는 에이전트 404.
- POST /runs/collect: 실효 설정이 params 로 평탄화 주입되고 body.params 가 우선한다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.live.registry import register_workflow
from app.main import app as fastapi_app
from app.services.agent_settings import effective_settings


# ── effective_settings(순수 함수) ────────────────────────────────────────────
def test_effective_settings_defaults_when_no_stored():
    assert effective_settings("corporate-card", None) == {"acct_cutoff_day": 9}


def test_effective_settings_overlays_stored_and_ignores_unknown():
    # 저장값이 기본값을 덮고, 스키마에 없는 키(legacy_key)는 무시된다.
    stored = {"acct_cutoff_day": 4, "legacy_key": "x"}
    assert effective_settings("corporate-card", stored) == {"acct_cutoff_day": 4}


def test_effective_settings_empty_for_schemaless_agent():
    assert effective_settings("demo", {"acct_cutoff_day": 4}) == {}


# ── 메뉴 항목(menu_items — voucher-by-type, 2026-08-20 유형별 병합) ─────────────
def test_effective_settings_menu_items_defaults():
    from app.services.agent_settings import DEFAULT_MENU_ITEMS

    eff = effective_settings("voucher-by-type", None)
    # menu_items(관리자 편집) + docu_type_choices(읽기 전용 카탈로그) 두 키.
    assert set(eff.keys()) == {"menu_items", "docu_type_choices"}
    assert eff["menu_items"] == DEFAULT_MENU_ITEMS
    assert [m["id"] for m in eff["menu_items"]] == ["sales-entry", "sales-cancel", "export-cost"]
    assert [m["defaultSelected"] for m in eff["menu_items"]] == [True, True, False]


def test_effective_settings_docu_type_choices_catalog():
    """전표유형 선택지(읽기 전용, 2026-08-20 실측 62종) — {code, label} shape 로 폼이 렌더한다.
    코드 상수(docu_types.DOCU_TYPE_CATALOG)가 유일 소스라 저장값이 있어도 덮이지 않는다."""
    from app.agents.voucher_receivable.docu_types import DOCU_TYPE_CATALOG

    eff = effective_settings("voucher-by-type", None)
    choices = eff["docu_type_choices"]
    assert len(choices) == 62
    assert choices[0] == {"code": "11", "label": "일반"}
    assert choices == [{"code": c, "label": l} for c, l in DOCU_TYPE_CATALOG]
    # 저장값에 같은 키를 심어도 무시된다(읽기 전용 — 코드 상수 승리).
    tampered = effective_settings(
        "voucher-by-type", {"docu_type_choices": [{"code": "99", "label": "위조"}]}
    )
    assert tampered["docu_type_choices"] == choices


def test_validate_settings_rejects_docu_type_choices_write():
    """docu_type_choices 는 저장 불가(미지 키로 거부) — 실측 카탈로그를 DB 로 덮는 경로 차단."""
    from app.services.agent_settings import validate_settings

    with pytest.raises(ValueError):
        validate_settings("voucher-by-type", {"docu_type_choices": [{"code": "11", "label": "일반"}]})


def test_effective_settings_menu_items_stored_overrides():
    stored = {"menu_items": [{"id": "custom", "label": "커스텀메뉴", "defaultSelected": True}]}
    eff = effective_settings("voucher-by-type", stored)
    assert eff["menu_items"] == [{"id": "custom", "label": "커스텀메뉴", "defaultSelected": True}]


def test_effective_settings_menu_items_invalid_stored_falls_back():
    from app.services.agent_settings import DEFAULT_MENU_ITEMS

    # 저장값이 깨졌으면(빈 목록 등) 기본 3종으로 폴백 — 실행 경로가 죽지 않게.
    assert effective_settings("voucher-by-type", {"menu_items": []})["menu_items"] == DEFAULT_MENU_ITEMS


def test_validate_menu_items_normalizes_missing_default_selected():
    from app.services.agent_settings import validate_settings

    out = validate_settings(
        "voucher-by-type", {"menu_items": [{"id": "a", "label": "메뉴A"}]}
    )
    assert out == {"menu_items": [{"id": "a", "label": "메뉴A", "defaultSelected": False}]}


@pytest.mark.parametrize(
    "bad",
    [
        [],  # 최소 1개.
        [{"id": "a", "label": "메뉴"}] * 21,  # 최대 20개.
        [{"id": "a", "label": "메뉴"}, {"id": "a", "label": "메뉴2"}],  # id 중복.
        [{"id": "", "label": "메뉴"}],  # id 필수.
        [{"id": "a", "label": ""}],  # label 필수.
        [{"id": "a", "label": "메뉴", "defaultSelected": 1}],  # bool 아님.
        "매출등록",  # 목록 아님.
    ],
)
def test_validate_menu_items_rejects_bad_input(bad):
    from app.services.agent_settings import validate_settings

    with pytest.raises(ValueError):
        validate_settings("voucher-by-type", {"menu_items": bad})


def test_validate_settings_unknown_key_rejected_for_menu_agent():
    from app.services.agent_settings import validate_settings

    with pytest.raises(ValueError):
        validate_settings("voucher-by-type", {"acct_cutoff_day": 4})


@pytest.mark.asyncio
async def test_get_agent_includes_menu_items_settings(client, make_user, auth_as):
    """GET /agents/voucher-by-type 직렬화에 settings.menu_items(기본 3종) + 빈 스키마가 포함된다
    (스키마를 []로 선언해 settings 포함을 트리거 — 프론트 실행 전 폼의 기본 선택 소스)."""
    uid = await make_user("s-menu-reader", "admin")
    auth_as(uid)
    r = await client.get("/agents/voucher-by-type")
    assert r.status_code == 200
    body = r.json()
    assert body["settingsSchema"] == []
    assert [m["label"] for m in body["settings"]["menu_items"]] == [
        "매출등록",
        "매출취소",
        "수출비용입력[나인벨]",
    ]


@pytest.mark.asyncio
async def test_patch_menu_items_admin_ok_and_reflected(client, make_user, auth_as):
    uid = await make_user("s-menu-admin", "admin")
    auth_as(uid)
    items = [
        {"id": "sales-entry", "label": "매출등록", "defaultSelected": True},
        {"id": "custom", "label": "신규메뉴", "defaultSelected": False},
    ]
    r = await client.patch(
        "/agents/voucher-by-type/settings", json={"settings": {"menu_items": items}}
    )
    assert r.status_code == 200
    assert r.json()["settings"]["menu_items"] == items
    r2 = await client.get("/agents/voucher-by-type")
    assert r2.json()["settings"]["menu_items"] == items


@pytest.mark.asyncio
async def test_patch_menu_items_invalid_400(client, make_user, auth_as):
    uid = await make_user("s-menu-bad", "admin")
    auth_as(uid)
    r = await client.patch(
        "/agents/voucher-by-type/settings", json={"settings": {"menu_items": []}}
    )
    assert r.status_code == 400
    assert "메뉴 항목" in r.json()["detail"]


@pytest.mark.asyncio
async def test_patch_docu_type_choices_rejected_400(client, make_user, auth_as):
    """docu_type_choices 는 읽기 전용 — PATCH 로 저장을 시도하면 미지 키로 400."""
    uid = await make_user("s-dtc-bad", "admin")
    auth_as(uid)
    r = await client.patch(
        "/agents/voucher-by-type/settings",
        json={"settings": {"docu_type_choices": [{"code": "11", "label": "일반"}]}},
    )
    assert r.status_code == 400
    assert "알 수 없는 설정" in r.json()["detail"]


# ── 발주 패턴 v2(order_patterns — purchase-order, 발주그룹 object) ────────────
def _group(**over) -> dict:
    """유효한 발주그룹 1건(필수 필드 전부) + 덮어쓸 값."""
    return {
        "id": "g1",
        "bundle": "EFEM",
        "name": "FRAME",
        "due": {"base": "FRAME", "offsetWeeks": 0},
        "reason": "PJT DESC EFEM FRAME",
        "modules": [{"id": "g1m1", "spec": "EFEM-Frame Assy", "name": "외주조립-F"}],
        "exceptions": [],
        **over,
    }


def _mod(spec: str, mid: str = "m1", name: str = "") -> dict:
    return {"id": mid, "spec": spec, "name": name}


def _exc(kind: str, value: str, xid: str = "x1", **over) -> dict:
    return {"id": xid, "scope": {"kind": kind, "value": value}, **over}


def _patterns(*groups: dict) -> dict:
    """settings 저장 shape — 배열 순서가 발주단위 생성 순서다."""
    return {"groups": list(groups)}


# ① 기본 9그룹.
def test_effective_settings_order_patterns_defaults():
    from app.services.agent_settings import DEFAULT_ORDER_PATTERNS

    eff = effective_settings("purchase-order", None)
    assert eff == {"order_patterns": DEFAULT_ORDER_PATTERNS}
    groups = eff["order_patterns"]["groups"]
    assert len(groups) == 9
    # BUFFER MODULE 은 PROCESS 에만 존재한다(2026-08-21 사용자 확정) — EFEM 은 4그룹.
    assert [g["name"] for g in groups if g["bundle"] == "EFEM"] == ["FRAME", "L Axis", "1공장", "3공장"]
    assert [g["name"] for g in groups if g["bundle"] == "PROCESS"] == [
        "FRAME",
        "L Axis",
        "1공장",
        "3공장",
        "BUFFER MODULE",
    ]
    assert groups[0]["modules"][0]["spec"] == "EFEM-Frame Assy"  # 매칭 1순위 키.


def test_effective_settings_order_patterns_defaults_are_deep_copied():
    """중첩이 깊어 얕은 복사면 호출자가 리터럴을 오염시킨다 — 실효값은 항상 독립 복사본."""
    from app.services.agent_settings import DEFAULT_ORDER_PATTERNS

    eff = effective_settings("purchase-order", None)["order_patterns"]
    eff["groups"][0]["modules"].clear()
    assert DEFAULT_ORDER_PATTERNS["groups"][0]["modules"], "기본값 리터럴이 오염됐습니다"


# ② 저장값 오버라이드 정규화.
def test_effective_settings_order_patterns_stored_overrides():
    stored = {"order_patterns": _patterns(
        {
            "id": "custom",
            "bundle": " EFEM ",
            "name": "커스텀",
            "due": {"base": "1공장", "offsetWeeks": 2},
            "modules": [{"id": "m1", "spec": "  EFEM-Frame Assy  "}],
        }
    )}
    eff = effective_settings("purchase-order", stored)
    assert eff["order_patterns"] == {
        "groups": [
            {
                "id": "custom",
                "bundle": "EFEM",
                "name": "커스텀",
                "due": {"base": "1공장", "offsetWeeks": 2},
                "reason": "",
                "modules": [{"id": "m1", "spec": "EFEM-Frame Assy", "name": ""}],
                "exceptions": [],
            }
        ]
    }


# ③ 관대 리더(읽기 경로).
def test_order_patterns_lenient_drops_only_broken_groups():
    """그룹 단위 관대 — 성립하지 않는 그룹만 버리고 나머지는 살린다."""
    stored = {"order_patterns": _patterns(
        _group(id="ok1"),
        _group(id="bad-due", due={"base": "가공품납기", "offsetWeeks": 0}),  # 그룹 납기는 3기준일만.
        _group(id="no-name", name=""),
        _group(id="no-module", modules=[{"id": "m1"}]),  # 유효 모듈 0.
        _group(id="ok1", name="중복 id"),
        _group(id="ok2", bundle="PROCESS", modules=[_mod("Process-Frame Assy")]),
    )}
    groups = effective_settings("purchase-order", stored)["order_patterns"]["groups"]
    assert [g["id"] for g in groups] == ["ok1", "ok2"]


def test_order_patterns_lenient_drops_only_broken_rows_inside_group():
    """행 단위 관대 — 파손·효과 없음·순환 위반 예외행만 빠지고 그룹은 남는다."""
    stored = {"order_patterns": _patterns(
        _group(
            modules=[_mod("EFEM-Frame Assy", "keep-m"), {"id": "m2", "spec": ""}],
            exceptions=[
                _exc("vendorClass", "판금품", "keep-x", due={"base": "FRAME", "offsetWeeks": 1}),
                _exc("nope", "판금품", note="알 수 없는 대상"),
                _exc("vendorClass", "가공품"),  # due/vendor/note 없음 = 효과 없는 예외.
                _exc("vendor", "와이엔에스", vendor="다른거래처"),  # 순환(거래처 대상 + 고정).
                _exc("vendorClass", "가공품", due={"base": "가공품납기", "offsetWeeks": 1}),  # 순환.
                _exc("exceptClass", "가공품", "keep-x2", note="직배송 가공품"),
            ],
        )
    )}
    groups = effective_settings("purchase-order", stored)["order_patterns"]["groups"]
    assert len(groups) == 1
    assert [m["id"] for m in groups[0]["modules"]] == ["keep-m"]
    assert [x["id"] for x in groups[0]["exceptions"]] == ["keep-x", "keep-x2"]


@pytest.mark.parametrize(
    "broken",
    [
        # v1 플랫 배열 저장분 — shape 자체가 달라 통째로 기본값.
        {"order_patterns": [{"id": "p01", "bundle": "EFEM", "unitNo": 1, "spec": "EFEM-Frame Assy"}]},
        {"order_patterns": {"groups": []}},
        {"order_patterns": {"groups": [{"id": "x"}]}},  # 전 그룹 파손.
        {"order_patterns": {"rows": []}},  # groups 키 없음.
        {"order_patterns": "EFEM"},
    ],
)
def test_order_patterns_lenient_falls_back_to_defaults(broken):
    from app.services.agent_settings import DEFAULT_ORDER_PATTERNS

    # 계획서 경로가 죽지 않도록 남는 그룹이 0이면 기본 9그룹.
    assert effective_settings("purchase-order", broken)["order_patterns"] == DEFAULT_ORDER_PATTERNS


# ④ 엄격 검증(쓰기 경로).
def test_validate_order_patterns_normalizes_optional_fields():
    """선택 필드는 기본값으로 채우되, 예외의 due/vendor/note 는 **부재 자체가 의미**라 키를 넣지 않는다."""
    from app.services.agent_settings import validate_settings

    out = validate_settings(
        "purchase-order",
        {"order_patterns": _patterns(
            {
                "id": "g1",
                "bundle": "EFEM",
                "name": "FRAME",
                "due": {"base": "FRAME", "offsetWeeks": 0},
                "modules": [{"id": "m1", "spec": "EFEM-Frame Assy"}],
                "exceptions": [_exc("vendorClass", "가공품", vendor="한국메카트로닉스")],
            }
        )},
    )
    assert out == {
        "order_patterns": {
            "groups": [
                {
                    "id": "g1",
                    "bundle": "EFEM",
                    "name": "FRAME",
                    "due": {"base": "FRAME", "offsetWeeks": 0},
                    "reason": "",
                    "modules": [{"id": "m1", "spec": "EFEM-Frame Assy", "name": ""}],
                    "exceptions": [
                        {
                            "id": "x1",
                            "scope": {"kind": "vendorClass", "value": "가공품"},
                            "vendor": "한국메카트로닉스",
                        }
                    ],
                }
            ]
        }
    }


def test_validate_order_patterns_allows_same_group_suffix_duplicate():
    """같은 그룹 안 접미 중복은 **허용** — 접두 없는 BOM 규격을 교정 등록하는 길을 막지 않는다."""
    from app.services.agent_settings import validate_settings

    rows = _patterns(_group(modules=[_mod("EFEM-T Axis Assy", "m1"), _mod("T Axis Assy", "m2")]))
    out = validate_settings("purchase-order", {"order_patterns": rows})
    assert [m["spec"] for m in out["order_patterns"]["groups"][0]["modules"]] == [
        "EFEM-T Axis Assy",
        "T Axis Assy",
    ]


def test_validate_order_patterns_allows_same_suffix_across_bundles():
    """발주묶음이 다르면 같은 접미(EFEM/PROCESS 의 'Frame Assy')는 정상 — 매칭이 갈리지 않는다."""
    from app.services.agent_settings import validate_settings

    rows = _patterns(
        _group(id="g1", bundle="EFEM", modules=[_mod("EFEM-Frame Assy")]),
        _group(id="g5", bundle="PROCESS", modules=[_mod("Process-Frame Assy")]),
    )
    assert len(validate_settings("purchase-order", {"order_patterns": rows})["order_patterns"]["groups"]) == 2


@pytest.mark.parametrize(
    "bad",
    [
        {"groups": []},  # 최소 1그룹.
        {"groups": [_group(id=f"g{i}") for i in range(41)]},  # 최대 40그룹.
        {"groups": [_group(id="dup"), _group(id="dup", modules=[_mod("EFEM-L Axis Assy")])]},  # id 중복.
        {"groups": [_group(id="")]},  # 식별자 필수.
        {"groups": [_group(bundle="")]},  # 발주묶음 필수.
        {"groups": [_group(name="")]},  # 그룹명 필수.
        {"groups": [_group(name="가" * 65)]},  # 그룹명 상한.
        {"groups": [_group(reason="가" * 201)]},  # 구매사유 상한.
        {"groups": [_group(due={"base": "가공품납기", "offsetWeeks": 0})]},  # 그룹 납기는 3기준일만.
        {"groups": [_group(due={"base": "FRAME"})]},  # offsetWeeks 누락.
        {"groups": [_group(due={"base": "FRAME", "offsetWeeks": -1})]},  # 음수.
        {"groups": [_group(due={"base": "FRAME", "offsetWeeks": 1.5})]},  # 소수.
        {"groups": [_group(due={"base": "FRAME", "offsetWeeks": True})]},  # bool 배제.
        {"groups": [_group(due={"base": "FRAME", "offsetWeeks": 53})]},  # 52 초과.
        {"groups": [_group(due="FRAME")]},  # 납기가 dict 아님.
        {"groups": [_group(modules=[])]},  # 모듈 0.
        {"groups": [_group(modules=[_mod("EFEM-Frame Assy", "")])]},  # 모듈 식별자 필수.
        {"groups": [_group(modules=[_mod("")])]},  # 규격 필수.
        {"groups": [_group(modules=[_mod("가" * 129)])]},  # 규격 상한.
        {"groups": [_group(modules=[_mod(f"EFEM-{i}", f"m{i}") for i in range(51)])]},  # 최대 50모듈.
        # 같은 발주묶음 안 정확 규격 중복 — 같은 그룹이든 다른 그룹이든 매칭이 비결정이 된다.
        {"groups": [_group(modules=[_mod("EFEM-Frame Assy", "m1"), _mod("EFEM-Frame Assy", "m2")])]},
        {
            "groups": [
                _group(id="g1", modules=[_mod("EFEM-Frame Assy")]),
                _group(id="g2", modules=[_mod("efem-frame assy")]),  # 대소문자 무시.
            ]
        },
        # 타 그룹 간 접미 중복 — 장비명 판별로 내려가는 접미 매칭이 두 그룹에 걸린다.
        {
            "groups": [
                _group(id="g1", modules=[_mod("EFEM-T Axis Assy")]),
                _group(id="g4", modules=[_mod("T Axis Assy")]),
            ]
        },
        {"groups": [_group(exceptions=[_exc("nope", "판금품", note="x")])]},  # 대상 kind 오류.
        {"groups": [_group(exceptions=[_exc("vendorClass", "", note="x")])]},  # 대상 값 필수.
        {"groups": [_group(exceptions=[_exc("vendorClass", "가" * 65, note="x")])]},  # 대상 값 상한.
        {"groups": [_group(exceptions=[_exc("vendorClass", "판금품")])]},  # 효과 없는 예외.
        {"groups": [_group(exceptions=[_exc("vendor", "와이엔에스", vendor="다른곳")])]},  # 순환①.
        {
            "groups": [
                _group(exceptions=[_exc("vendorClass", "가공품", due={"base": "가공품납기", "offsetWeeks": 1})])
            ]
        },  # 순환②.
        {"groups": [_group(exceptions=[_exc("vendorClass", "판금품", due={"base": "없는기준", "offsetWeeks": 0})])]},
        {"groups": [_group(exceptions=[_exc("vendorClass", "판금품", vendor="가" * 65)])]},  # 거래처 상한.
        {"groups": [_group(exceptions=[_exc("vendorClass", "판금품", note="가" * 201)])]},  # 비고 상한.
        {"groups": [_group(exceptions=[_exc("exceptClass", "가공품", f"x{i}", note="n") for i in range(21)])]},
        {"groups": [_group(exceptions="판금품")]},  # 예외가 목록 아님.
        {"groups": ["EFEM"]},  # 그룹이 dict 아님.
        {"groups": {"g1": {}}},  # groups 가 배열 아님.
        {"rows": []},  # groups 키 없음.
        [_group()],  # v1 배열 shape.
        "EFEM",  # dict 아님.
    ],
)
def test_validate_order_patterns_rejects_bad_input(bad):
    from app.services.agent_settings import validate_settings

    with pytest.raises(ValueError):
        validate_settings("purchase-order", {"order_patterns": bad})


@pytest.mark.parametrize(
    "bad, needle",
    [
        ({"groups": [_group(id="a"), _group(id="b", name="")]}, "2번째 그룹의"),
        (
            {"groups": [_group(id="a"), _group(id="b", modules=[_mod("EFEM-L Axis Assy"), _mod("")])]},
            "2번째 그룹의 2번째 모듈",
        ),
        (
            {
                "groups": [
                    _group(id="a"),
                    _group(
                        id="b",
                        modules=[_mod("EFEM-L Axis Assy")],
                        exceptions=[_exc("vendorClass", "판금품", note="n"), _exc("vendorClass", "가공품")],
                    ),
                ]
            },
            "2번째 그룹의 2번째 예외",
        ),
    ],
)
def test_validate_order_patterns_error_carries_coordinates(bad, needle):
    """관리자가 어느 그룹/행을 고쳐야 하는지 메시지만 보고 알 수 있어야 한다."""
    from app.services.agent_settings import validate_settings

    with pytest.raises(ValueError, match=needle):
        validate_settings("purchase-order", {"order_patterns": bad})


# ⑤ strip 은 하되 개행은 보존(구매사유·비고는 여러 줄 입력).
def test_validate_order_patterns_preserves_newlines_in_text():
    from app.services.agent_settings import validate_settings

    out = validate_settings(
        "purchase-order",
        {
            "order_patterns": {
                "groups": [
                    _group(
                        reason="  PJT DESC EFEM FRAME\n2차 발주분  ",
                        exceptions=[_exc("exceptClass", "판금품", note="  직배송 판금품\n담당자 확인  ")],
                    )
                ]
            }
        },
    )
    group = out["order_patterns"]["groups"][0]
    assert group["reason"] == "PJT DESC EFEM FRAME\n2차 발주분"
    assert group["exceptions"][0]["note"] == "직배송 판금품\n담당자 확인"


def test_validate_settings_unknown_key_rejected_for_pattern_agent():
    from app.services.agent_settings import validate_settings

    with pytest.raises(ValueError):
        validate_settings("purchase-order", {"acct_cutoff_day": 4})


# ⑦ GET 직렬화.
@pytest.mark.asyncio
async def test_get_agent_includes_order_patterns_settings(client, make_user, auth_as):
    """GET /agents/purchase-order 직렬화에 settings.order_patterns.groups(기본 9그룹) + 빈 스키마가
    포함된다(스키마를 []로 선언해 settings 포함을 트리거 — 계획서/패턴 관리 화면의 기본값 소스)."""
    uid = await make_user("s-pattern-reader", "admin")
    auth_as(uid)
    r = await client.get("/agents/purchase-order")
    assert r.status_code == 200
    body = r.json()
    assert body["settingsSchema"] == []
    groups = body["settings"]["order_patterns"]["groups"]
    assert [g["id"] for g in groups] == [f"g{i}" for i in range(1, 10)]
    assert groups[0]["modules"][0]["spec"] == "EFEM-Frame Assy"


# ⑥ PATCH 200/400.
@pytest.mark.asyncio
async def test_patch_order_patterns_admin_ok_and_reflected(client, make_user, auth_as):
    uid = await make_user("s-pattern-admin", "admin")
    auth_as(uid)
    payload = _patterns(
        _group(id="g1", modules=[_mod("EFEM-Frame Assy", "g1m1", "외주조립-F")]),
        _group(
            id="g9",
            bundle="PROCESS",
            name="BUFFER MODULE",
            due={"base": "1공장", "offsetWeeks": 0},
            reason="PJT DESC BUFFER MODULE",
            modules=[_mod("Process-Buffer Assy", "g9m1", "외주조립-BUFFER")],
            exceptions=[_exc("vendorClass", "가공품", "g9x1", vendor="한국메카트로닉스")],
        ),
    )
    r = await client.patch(
        "/agents/purchase-order/settings", json={"settings": {"order_patterns": payload}}
    )
    assert r.status_code == 200
    saved = r.json()["settings"]["order_patterns"]
    assert [g["id"] for g in saved["groups"]] == ["g1", "g9"]
    assert saved["groups"][1]["exceptions"][0]["vendor"] == "한국메카트로닉스"
    r2 = await client.get("/agents/purchase-order")
    assert r2.json()["settings"]["order_patterns"] == saved


@pytest.mark.asyncio
async def test_patch_order_patterns_invalid_400(client, make_user, auth_as):
    uid = await make_user("s-pattern-bad", "admin")
    auth_as(uid)
    r = await client.patch(
        "/agents/purchase-order/settings", json={"settings": {"order_patterns": {"groups": []}}}
    )
    assert r.status_code == 400
    assert "발주 그룹" in r.json()["detail"]


# ── GET 직렬화(settings/settingsSchema 포함 여부) ─────────────────────────────
@pytest.mark.asyncio
async def test_get_agents_includes_settings_for_card_chat(client, make_user, auth_as):
    uid = await make_user("s-reader", "admin")
    auth_as(uid)
    r = await client.get("/agents/corporate-card")
    assert r.status_code == 200
    body = r.json()
    assert body["settings"] == {"acct_cutoff_day": 9}  # 저장값 없음 → 스키마 기본값.
    schema = body["settingsSchema"]
    assert [s["key"] for s in schema] == ["acct_cutoff_day"]
    assert schema[0]["label"] == "회계시점 결정일"
    assert schema[0]["type"] == "number"
    assert (schema[0]["default"], schema[0]["min"], schema[0]["max"]) == (9, 1, 28)


@pytest.mark.asyncio
async def test_get_agents_omits_settings_for_schemaless_agent(
    client, make_user, make_agent, auth_as
):
    uid = await make_user("s-reader2", "admin")
    auth_as(uid)
    await make_agent("s-plain", workflow_id="s-wf-plain")
    r = await client.get("/agents/s-plain")
    assert r.status_code == 200
    assert "settings" not in r.json()
    assert "settingsSchema" not in r.json()


# ── PATCH /agents/{id}/settings ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_patch_settings_admin_ok_and_reflected(client, make_user, auth_as):
    uid = await make_user("s-admin", "admin")
    auth_as(uid)
    r = await client.patch(
        "/agents/corporate-card/settings", json={"settings": {"acct_cutoff_day": 4}}
    )
    assert r.status_code == 200
    assert r.json()["settings"] == {"acct_cutoff_day": 4}
    # 재조회에서도 저장값이 유지된다.
    r2 = await client.get("/agents/corporate-card")
    assert r2.json()["settings"] == {"acct_cutoff_day": 4}


@pytest.mark.asyncio
async def test_patch_settings_user_forbidden_403(client, make_user, auth_as):
    uid = await make_user("s-user", "user")
    auth_as(uid)
    r = await client.patch(
        "/agents/corporate-card/settings", json={"settings": {"acct_cutoff_day": 4}}
    )
    assert r.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [0, 29, "4"])
async def test_patch_settings_invalid_value_400(client, make_user, auth_as, bad):
    """범위 밖(0, 29)·타입 위반(문자열)은 400 + 한국어 메시지."""
    uid = await make_user(f"s-bad-{bad}", "admin")
    auth_as(uid)
    r = await client.patch(
        "/agents/corporate-card/settings", json={"settings": {"acct_cutoff_day": bad}}
    )
    assert r.status_code == 400
    assert "회계시점 결정일" in r.json()["detail"]


@pytest.mark.asyncio
async def test_patch_settings_unknown_key_400(client, make_user, auth_as):
    uid = await make_user("s-unk", "admin")
    auth_as(uid)
    r = await client.patch("/agents/corporate-card/settings", json={"settings": {"nope": 1}})
    assert r.status_code == 400
    assert "알 수 없는 설정" in r.json()["detail"]


@pytest.mark.asyncio
async def test_patch_settings_schemaless_agent_400(client, make_user, make_agent, auth_as):
    uid = await make_user("s-nos", "admin")
    auth_as(uid)
    await make_agent("s-noschema", workflow_id="s-wf-nos")
    r = await client.patch(
        "/agents/s-noschema/settings", json={"settings": {"acct_cutoff_day": 4}}
    )
    assert r.status_code == 400
    assert "설정 항목이 없습니다" in r.json()["detail"]


@pytest.mark.asyncio
async def test_patch_settings_missing_agent_404(client, make_user, auth_as):
    uid = await make_user("s-404", "admin")
    auth_as(uid)
    r = await client.patch(
        "/agents/s-ghost/settings", json={"settings": {"acct_cutoff_day": 4}}
    )
    assert r.status_code == 404


# ── 런 파라미터 주입(runs.collect → state['params']) ─────────────────────────
class _CaptureGraph:
    """state['params'] 를 캡처하는 가짜 그래프 — 설정 평탄화 주입 검증용."""

    def __init__(self, sink: list):
        self._sink = sink

    async def ainvoke(self, state: dict) -> dict:
        self._sink.append(dict(state.get("params") or {}))
        await state["events"].put({"step": "s", "status": "done"})
        return {"result": "ok"}


class _FakeBrowser:
    async def new_page(self):
        return None

    async def close(self):
        return None


async def _fake_browser_factory():
    return _FakeBrowser()


@pytest.fixture
def capture_run_params(sm):
    """corporate-card 을 캡처용 가짜 워크플로우로 배선하고 params 캡처 리스트를 돌려준다."""
    captured: list[dict] = []
    register_workflow("settings-wf", lambda: _CaptureGraph(captured))
    fastapi_app.state.browser_factory = _fake_browser_factory

    async def _wire():
        from app.models import Agent

        async with sm() as s:
            a = (await s.execute(select(Agent).where(Agent.id == "corporate-card"))).scalar_one()
            a.workflow_id = "settings-wf"
            await s.commit()

    return _wire, captured


@pytest.mark.asyncio
async def test_run_params_include_effective_settings(
    client, make_user, auth_as, capture_run_params
):
    """설정 미저장 시 스키마 기본값(9)이 params 로 평탄화 주입된다."""
    wire, captured = capture_run_params
    await wire()
    uid = await make_user("s-run", "admin")
    auth_as(uid)
    r = await client.post("/runs/collect", json={"agentId": "settings-wf"})
    assert r.status_code == 200
    assert captured and captured[0]["acct_cutoff_day"] == 9


@pytest.mark.asyncio
async def test_run_params_body_cannot_override_settings(
    client, make_user, auth_as, capture_run_params
):
    """리뷰 HIGH — 저장된 관리자 설정(4)이 승리하고, body.params 의 같은 스키마 키(3)는 무시된다.

    (이전 규약: body.params 우선 → 사용자가 관리자 설정을 덮어 권한상승. 보안 수정으로 서버 권위.)
    """
    wire, captured = capture_run_params
    await wire()
    uid = await make_user("s-run2", "admin")
    auth_as(uid)
    ok = await client.patch(
        "/agents/corporate-card/settings", json={"settings": {"acct_cutoff_day": 4}}
    )
    assert ok.status_code == 200
    r = await client.post(
        "/runs/collect",
        json={"agentId": "settings-wf", "params": {"acct_cutoff_day": 3}},
    )
    assert r.status_code == 200
    assert captured and captured[0]["acct_cutoff_day"] == 4  # 서버 저장값 승리(조작 무시)
