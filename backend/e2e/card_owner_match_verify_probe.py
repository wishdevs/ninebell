"""HEADLESS 검증 프로브 — 수정된 CARD_SUB_SELECT_BY_NAME_JS 매칭 실화면 검증.

⚠⚠ 절대 안전 규칙 ⚠⚠
  - '적용' 버튼 클릭 금지 — 체크만 검증하고 폼에 반영하지 않는다.
  - F7(저장)·상신 절대 금지.
  - 검증 후 checkAll(false) 로 원복하고 브라우저를 닫는다(적용 없이 종료 = 서버에 아무 영향 없음).

card_owner_col_probe.py(2026-07-29 실측)로 확정한 진입 경로(login→user_type(회계)→menu_nav→
set_gubun(카드)→add_row→open_evdn→select_evdn(01)→돋보기 클릭→'카드' 서브팝업)를 그대로 재사용해
서브팝업까지 도달한 뒤, **수정된** app.agents.card_collect.js.CARD_SUB_SELECT_BY_NAME_JS 를
"정원호"(그리드 덤프에서 실존 확인된 카드명 "국민법인카드(정원호)-8883"의 오너)와
"존재하지않는이름XYZ"(음성 대조)로 각각 실행해 matched/checked 및 체크된 행의 FINPRODUCT_NM 을 검증.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/card_owner_match_verify_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Page, async_playwright  # noqa: E402

# ── 재사용(신규 작성 아님) — card_owner_col_probe.py(2026-07-29)와 동일 진입 경로 ─────
from app.agents.card_collect import js as cc_js  # noqa: E402  (CARD_SEARCH_BTN_JS, 수정된 CARD_SUB_SELECT_BY_NAME_JS)
from app.agents.common.doc_steps import open_evdn_editor, select_evdn_code  # noqa: E402
from app.config import get_settings  # noqa: E402
from nbkit.browser.actions import js_click  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.omnisol.menu_schemas import EXPENSE_CARD  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
VIEWPORT = {"width": 1440, "height": 900}

POSITIVE_OWNER = "정원호"  # 그리드 덤프(card_owner_col_probe) 에서 실존 확인된 카드명 오너.
NEGATIVE_OWNER = "존재하지않는이름XYZ"

# ── 신규 작성분(이 검증 고유) — 체크된 행의 FINPRODUCT_NM 읽기전용 대조(체크/적용 아님) ──
CARD_SUB_CHECKED_ROWS_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const sub = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];
  if (!sub) return { ok:false, reason:'no-sub' };
  try {
    const g = window.jQuery(sub.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const rows = n > 0 ? ds.getJsonRows(0, n - 1) : [];
    const idx = g.getCheckedRows() || [];
    const names = idx.map(i => (rows[i] || {}).FINPRODUCT_NM || null);
    return { ok:true, n, idx, names };
  } catch (e) { return { ok:false, err:String(e).slice(0, 120) }; }
}"""

CARD_SUB_FULL_DUMP_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const sub = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];
  if (!sub) return { ok:false, reason:'no-sub' };
  try {
    const g = window.jQuery(sub.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const rows = n > 0 ? ds.getJsonRows(0, n - 1) : [];
    return { ok:true, n, rows };
  } catch (e) { return { ok:false, err:String(e).slice(0, 120) }; }
}"""

CARD_SUB_CHECKALL_FALSE_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const sub = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];
  if (!sub) return { ok:false, reason:'no-sub' };
  try {
    const g = window.jQuery(sub.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    g.checkAll(false);
    let checked=-1; try { checked=(g.getCheckedRows()||[]).length; } catch(e){}
    return { ok:true, checked };
  } catch (e) { return { ok:false, err:String(e).slice(0, 120) }; }
}"""


def _dump(name: str, obj) -> Path:
    p = ARTIFACTS / f"card_owner_match_verify_{name}.json"
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
    print(f"[dump] {p}")
    return p


async def _run_case(page: Page, owner: str) -> dict:
    r = await page.evaluate(cc_js.CARD_SUB_SELECT_BY_NAME_JS, owner)
    checked_detail = await page.evaluate(CARD_SUB_CHECKED_ROWS_JS)
    reset = await page.evaluate(CARD_SUB_CHECKALL_FALSE_JS)
    return {
        "owner": owner,
        "raw": r,
        "checked_rows": checked_detail,
        "reset": reset,
    }


async def run() -> None:
    settings = get_settings()
    base = settings.erp_base
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        page: Page = await (await browser.new_context(viewport=VIEWPORT)).new_page()
        try:
            print("[step] login")
            await ensure_logged_in(page, USERID, PASSWORD, base)

            print("[step] user_type 회계")
            await ensure_user_type(page, "회계")

            print("[step] menu_nav (결의서입력)")
            await navigate_schema(page, EXPENSE_CARD, base)

            print("[step] set_gubun 카드")
            for _ in range(50):
                if await page.evaluate("(s) => !!document.querySelector(s)", selectors.GUBUN_SELECT):
                    break
                await page.wait_for_timeout(300)
            r = await page.evaluate(
                js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS,
                {"selector": selectors.GUBUN_SELECT, "text": "카드"},
            )
            print("  gubun result:", r)

            print("[step] add_row (F3)")
            await js_click(page, selectors.BTN_ADD)
            rows = -1
            for _ in range(33):
                await page.wait_for_timeout(300)
                rows = await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)
                if isinstance(rows, int) and rows > 0:
                    break
            print("  detail rows:", rows)
            if not (isinstance(rows, int) and rows > 0):
                raise RuntimeError("add_row 실패 — 입력 행이 생성되지 않았습니다")

            print("[step] open_evdn")
            r = await open_evdn_editor(page)
            if not r.get("ok"):
                raise RuntimeError(f"open_evdn 실패: {r}")

            print("[step] select_evdn(01 법인카드)")
            r = await select_evdn_code(page, "01")
            if not r.get("ok"):
                raise RuntimeError(f"select_evdn 실패: {r}")

            print("[step] 카드번호 돋보기 클릭 → '카드' 서브팝업 오픈")
            box = None
            for _ in range(20):
                box = await page.evaluate(cc_js.CARD_SEARCH_BTN_JS)
                if box:
                    break
                await page.wait_for_timeout(300)
            if not box:
                raise RuntimeError("돋보기 버튼을 찾지 못했습니다(법인카드 팝업 아님?)")
            await page.mouse.click(box["x"], box["y"])
            await page.wait_for_timeout(1200)
            await page.screenshot(path=str(ARTIFACTS / "card_owner_match_verify_sub_popup.png"))

            full_dump = await page.evaluate(CARD_SUB_FULL_DUMP_JS)
            print("[full dump] rows:")
            for row in full_dump.get("rows", []):
                print("  ", row)
            _dump("full_rows", full_dump)

            print(f"[case 1] owner={POSITIVE_OWNER!r} (양성)")
            case1 = await _run_case(page, POSITIVE_OWNER)
            print("  ", case1["raw"], "| checked FINPRODUCT_NM:", case1["checked_rows"].get("names"))
            # ── 게이트(2026-08-13): 관찰 로그가 아니라 하드 실패로 판정한다 — FINPRODUCT_NM
            # 괄호 제한 수정의 실화면 검증. 종전 버그는 KOR_NM='정원호' 공용카드가 함께 걸려
            # matched=2 였다(정답 1장: '국민법인카드(정원호)-8883').
            raw1 = case1["raw"]
            names1 = [str(n) for n in (case1["checked_rows"].get("names") or []) if n]
            assert raw1.get("ok") is True, f"양성 케이스 실행 실패: {raw1}"
            assert raw1.get("matched") == 1, f"matched != 1 (오탐/미탐): {raw1}"
            assert len(names1) == 1 and all(f"({POSITIVE_OWNER})" in n for n in names1), (
                f"매칭 카드명에 '({POSITIVE_OWNER})' 아님: {names1}"
            )

            print(f"[case 2] owner={NEGATIVE_OWNER!r} (음성 대조)")
            case2 = await _run_case(page, NEGATIVE_OWNER)
            print("  ", case2["raw"], "| checked FINPRODUCT_NM:", case2["checked_rows"].get("names"))

            result = {"positive": case1, "negative": case2}
            _dump("result", result)

            print("\n=== RESULT ===")
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {exc}")
            try:
                await page.screenshot(path=str(ARTIFACTS / "card_owner_match_verify_FAIL.png"))
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            # ⚠ '적용' 클릭 없음 — 체크만 검증하고 checkAll(false) 로 원복했으므로 서버에
            # 아무 것도 반영되지 않는다. 저장(F7)도 하지 않았으므로 그대로 브라우저를 닫는다.
            await browser.close()


if __name__ == "__main__":
    asyncio.run(run())
