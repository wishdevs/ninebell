"""CARD_SUB_SELECT_BY_NAME_JS 매칭 규칙 — 실제 JS 문자열을 스텁 DOM 에서 평가해 검증.

2026-08-13 오탐 반증(사용자 신고): 매칭이 카드명 FINPRODUCT_NM 괄호 '(이름)' 에 제한돼야
하는데 KOR_NM(관리사원)·PARTNER_NM(거래처) 등 다른 컬럼의 이름도 걸렸다. 픽스처는 실그리드
덤프(backend/e2e/artifacts/card_owner_match_verify_full_rows.json, 6행) 그대로 — 반증 행
FINPRODUCT_NM='국민법인카드(제조본부)-1884', KOR_NM='정원호' 를 포함한다.

fake page 가 아니라 **진짜 브라우저**(playwright sync + set_content 스텁)로 js.py 의
JS 문자열 자체를 평가한다 — steps 쪽 fake 테스트가 못 잡는 JS 매칭 로직의 회귀를 잡는다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from app.agents.card_collect import js

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "e2e"
    / "artifacts"
    / "card_owner_match_verify_full_rows.json"
)
ROWS = json.loads(FIXTURE.read_text())["rows"]

# '카드' 서브팝업 스텁 — JS 가 요구하는 최소 표면만 흉내낸다:
# .k-window(제목에 '법인카드' 없음) > .dews-ui-grid, window.jQuery(...).data('dewsControl')._grid,
# grid 의 getDataSource().getRowCount()/getJsonRows(a,b)·checkAll(false)·setChecked·getCheckedRows.
STUB_HTML = """
<div class="k-window" style="position:relative">
  <div class="k-window-title">카드</div>
  <div class="dews-ui-grid"></div>
</div>
<script>
window.__rows = __ROWS_JSON__;
window.__checked = new Set();
const grid = {
  getDataSource: () => ({
    getRowCount: () => window.__rows.length,
    getJsonRows: (a, b) => window.__rows.slice(a, b + 1),
  }),
  checkAll: () => window.__checked.clear(),
  setChecked: (i, v) => (v ? window.__checked.add(i) : window.__checked.delete(i)),
  getCheckedRows: () => [...window.__checked],
};
window.jQuery = () => ({ data: () => ({ _grid: grid }) });
</script>
""".replace("__ROWS_JSON__", json.dumps(ROWS, ensure_ascii=False))


@pytest.fixture(scope="module")
def sub_popup_page():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(STUB_HTML)
        yield page
        browser.close()


def _select(page, owners: list[str]) -> dict:
    # JS 가 매 호출 checkAll(false) 로 시작하므로 케이스 간 체크 상태는 독립이다.
    return page.evaluate(js.CARD_SUB_SELECT_BY_NAME_JS, owners)


def test_matches_only_finproduct_nm_paren(sub_popup_page):
    """owners=['정원호'] → 카드명 괄호 '(정원호)' 카드 정확히 1장.

    반증 행(KOR_NM='정원호' 인 공용카드 '국민법인카드(제조본부)-1884')과 개인카드
    PARTNER_NM='정원호' 가 걸리면 안 된다 — 종전 버그는 이 케이스에서 matched=2 였다.
    """
    r = _select(sub_popup_page, ["정원호"])
    assert r["ok"] is True and r["n"] == 6
    assert r["matched"] == 1 and r["checked"] == 1
    assert r["names"] == ["국민법인카드(정원호)-8883"]


def test_partner_nm_paren_does_not_match(sub_popup_page):
    """owners=['하나'] → 0장 — PARTNER_NM '공용카드 거래처(하나)' 의 '(하나)' 오탐 회귀 방지."""
    r = _select(sub_popup_page, ["하나"])
    assert r["ok"] is True
    assert r["matched"] == 0 and r["checked"] == 0 and r["names"] == []


def test_unknown_name_matches_nothing(sub_popup_page):
    """미존재 이름 → 0장 (matched==0 의 폴백/중단 처리는 steps.select_all_cards 테스트 영역)."""
    r = _select(sub_popup_page, ["존재하지않는이름XYZ"])
    assert r["ok"] is True
    assert r["matched"] == 0 and r["checked"] == 0


def test_same_paren_name_on_multiple_cards_all_match(sub_popup_page):
    """같은 괄호 이름이 여러 카드에 있으면 전부 매칭 — 픽스처의 '(경영본부)' 4장."""
    r = _select(sub_popup_page, ["경영본부"])
    assert r["ok"] is True
    assert r["matched"] == 4 and r["checked"] == 4
    assert len(r["names"]) == 4 and all("(경영본부)" in n for n in r["names"])


def test_js_source_no_longer_scans_owner_columns():
    """소스 가드 — 소유자/관리사원/거래처 컬럼 매칭·행 전체 스캔의 재도입을 막는다."""
    for token in ("CARD_OWNR_NM", "KOR_NM", "PARTNER_NM", "inAnyField"):
        assert token not in js.CARD_SUB_SELECT_BY_NAME_JS
