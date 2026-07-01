"""omnisol/selectors·js_lib 단일소스 상수 존재/무결성."""

from __future__ import annotations

from nbkit.omnisol import js_lib, selectors


def test_core_selectors_present_and_nonempty():
    for name in (
        "LOGIN_USERID",
        "LOGIN_PASSWORD",
        "LOGIN_SUBMIT",
        "AVATAR",
        "GRID",
        "BTN_LOOKUP",
        "BTN_ADD",
        "BTN_SAVE",
        "GUBUN_SELECT",
        "DIALOG",
        "CODEPICKER_BTN",
        "SEARCH_KEY",
    ):
        val = getattr(selectors, name)
        assert isinstance(val, str) and val, f"selectors.{name} 누락/빈값"


def test_viewport_is_verified_size():
    # 캔버스 픽셀 좌표가 이 뷰포트 기준으로 검증됨 — 바뀌면 좌표 재검증 필요.
    assert selectors.VIEWPORT == {"width": 1600, "height": 1000}


def test_grid_selector_is_dews_wrapper():
    assert "dews-ui-grid" in selectors.GRID


def test_core_js_constants_present():
    assert "getRowCount" in js_lib.ROWCOUNT_JS
    assert "getRowCount" in js_lib.ROWCOUNT_BY_INDEX_JS
    assert "getJsonRows" in js_lib.GET_JSON_ROWS_JS
    assert "dews-ui-grid" in js_lib.MENU_CHECK_JS
    assert "user_types" in js_lib.PROFILE_JS
    # 사용자유형 실클릭용 bbox JS 4종.
    for name in ("UT_DROPDOWN_BOX_JS", "UT_OPTION_BOX_JS", "UT_APPLY_BOX_JS", "UT_DISPLAY_JS"):
        assert getattr(js_lib, name)


def test_collect_master_detail_js_is_end_inclusive_and_embeds_url():
    url = "/api/IM/Some_Service/list_dtl"
    js = js_lib.collect_master_detail_js(url)
    assert url in js
    assert "take - 1" in js  # end-inclusive 정규화(off-by-one 회피)
    assert "$.ajax" not in js  # window.jQuery.ajax 사용(전역 $ 미의존)
    assert "window.jQuery.ajax" in js


def test_p3_evidence_and_project_primitives_present():
    # P3(법인카드 대화형)가 조합해 쓸 옴니솔 프리미티브 단일소스.
    for name in (
        "KENDO_SET_DROPDOWN_BY_TEXT_JS",
        "OPEN_EVDN_EDITOR_JS",
        "EVDN_SELECT_BY_CODE_JS",
        "EVDN_APPLY_BOX_JS",
        "PROJECT_PICKER_BOX_JS",
        "PROJECT_READ_JS",
        "PROJECT_SELECT_JS",
    ):
        assert getattr(js_lib, name)
