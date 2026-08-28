"""진단 — 프리필과 같은 검색어 제출 시 팝업 소멸 타임라인(읽기·조회조건만)."""
from __future__ import annotations
import asyncio, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.async_api import async_playwright
from app.agents.purchase_order import js, steps
from app.config import get_settings
from app.live.runner import LIVE_VIEWPORT, _ScaledPage
from nbkit.omnisol import js_lib
from nbkit.omnisol.navigator import navigate_menu
from nbkit.patterns.login_flow import ensure_logged_in
from nbkit.patterns.user_type_flow import ensure_user_type

KW = os.environ.get("E2E_KW", "ETRIBE ERP TEST 001")
MODE = os.environ.get("E2E_MODE", "submit")  # submit | type_only | type_then_clear_submit
SNAP_JS = r"""() => ({
  present: !!document.querySelector('#keyword'),
  wins: [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null).map(w=>(w.querySelector('.k-window-title')||{}).innerText),
  mainField: (()=>{const l=[...document.querySelectorAll('label')].find(l=>(l.innerText||'').trim()==='프로젝트'); if(!l) return null; const c=l.closest('tr,div'); const i=c&&c.querySelector('input'); return i?i.value:null;})(),
  bodyChildren: document.body.children.length,
  kwVal: (document.querySelector('#keyword')||{}).value,
})"""
async def main():
    pw = await async_playwright().start(); browser = await pw.chromium.launch(headless=True)
    page = _ScaledPage(await browser.new_page(viewport=LIVE_VIEWPORT), 0.4); base = get_settings().erp_base
    await ensure_logged_in(page, "이트라이브2", "1111", base); await ensure_user_type(page, "SCM")
    await navigate_menu(page, "/PU/PUOPRQ00200_X20616", base, label="tl", grids_required=1); await page.wait_for_timeout(1500)
    box = await page.evaluate(js_lib.PROJECT_PICKER_BOX_JS); await page.mouse.click(box["x"], box["y"])
    await steps._poll(page, js.POPUP_STATE_JS, lambda s: bool(s and s.get("present") and s.get("gridReady")), steps.POPUP_OPEN_CAP_MS)
    await page.wait_for_timeout(1000)
    print("before:", json.dumps(await page.evaluate(SNAP_JS), ensure_ascii=False))
    ok = await steps._type_keyword(page, KW)
    print("typed:", ok, json.dumps(await page.evaluate(SNAP_JS), ensure_ascii=False))
    if MODE == "submit":
        print("submit:", await page.evaluate(js.SUBMIT_KEYWORD_JS))
    elif MODE == "keydown_only":
        print("keydown:", await page.evaluate(r"""()=>{const i=document.querySelector('#keyword');window.jQuery(i).trigger(window.jQuery.Event('keydown',{keyCode:13,which:13}));return true}"""))
    for t in range(0, 3000, 100):
        s = await page.evaluate(SNAP_JS); print(f"t+{t}ms", json.dumps(s, ensure_ascii=False))
        await page.wait_for_timeout(100)
    await browser.close(); await pw.stop()
asyncio.run(main())
