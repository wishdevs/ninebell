"""omnisol/menu_schemas 무결성 — 딥링크·사용자유형·유일성."""

from __future__ import annotations

import pytest

from nbkit.omnisol import menu_schemas as ms


def test_menu_map_nonempty():
    assert len(ms.MENU_MAP) >= 2


def test_every_schema_is_wellformed():
    for key, schema in ms.MENU_MAP.items():
        assert schema.key == key
        assert schema.menu_id, f"{key}: menu_id 누락"
        assert schema.deeplink.startswith("/"), f"{key}: deeplink 은 '/' 로 시작해야 함"
        assert ms.is_valid_user_type(schema.user_type), f"{key}: 잘못된 사용자유형"
        assert schema.grids_expected >= 1
        assert schema.label


def test_menu_ids_are_unique():
    ids = [s.menu_id for s in ms.MENU_MAP.values()]
    assert len(ids) == len(set(ids))


def test_bom_collection_has_detail_wiring():
    bom = ms.BOM_COLLECTION
    assert bom.user_type == ms.USER_TYPE_HR
    assert bom.detail_service_url and bom.detail_service_url.startswith("/api/")
    assert bom.master_id_field == "INVTRX_RSV_NO"


def test_expense_card_is_accounting_write_flow():
    exp = ms.EXPENSE_CARD
    assert exp.user_type == ms.USER_TYPE_ACCT
    assert exp.grids_expected == 3
    assert exp.detail_service_url is None  # 쓰기 플로우(수집 아님)


def test_get_menu_and_deeplink_for():
    assert ms.get_menu("bom-collection") is ms.BOM_COLLECTION
    url = ms.deeplink_for(ms.BOM_COLLECTION, "https://erp.example.com/")
    assert url == "https://erp.example.com/IM/IMIIRM00700_X20616"
    with pytest.raises(KeyError):
        ms.get_menu("does-not-exist")


def test_is_valid_user_type():
    assert ms.is_valid_user_type("인사")
    assert ms.is_valid_user_type("회계")
    assert not ms.is_valid_user_type("관리자")
