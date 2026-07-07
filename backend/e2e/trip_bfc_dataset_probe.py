"""BFC_PARTNER 를 detail dataSource 에 직접 setValue — grid.setValue 는 Invalid field index 로
실패하지만, dataSource.setValue(SET_ACCT_DATE 패턴)는 될 수 있다는 가설 검증. 저장 없음.
이트라이브2 partner code=2026032511(catalog 확정)."""
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0,'/Users/wishdev/et-works/dashboard-design/backend')
from playwright.async_api import async_playwright
from app.agents.common import doc_steps
from app.agents.trip_domestic import steps as ts
from app.config import get_settings
from app.live.runner import LIVE_VIEWPORT
from nbkit.browser.actions import js_click
from nbkit.omnisol import js_lib, selectors
from nbkit.omnisol.menu_schemas import EXPENSE_CARD
from nbkit.patterns.login_flow import ensure_logged_in
from nbkit.patterns.menu_navigate_flow import navigate_schema
from nbkit.patterns.user_type_flow import ensure_user_type

# detail 마지막 행 dataSource.setValue(BFC_PARTNER_CD/NM) + 재독. grid.setValue 실패 vs ds.setValue.
SET_BFC_JS = r"""([code, name]) => {
  const out = {};
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
    const ds = g.getDataSource(); const n = ds.getRowCount(); const row = Math.max(0,n-1);
    // 1) grid.setValue 시도.
    try { g.setValue(row,'BFC_PARTNER_CD',code); out.grid_cd='ok'; } catch(e){ out.grid_cd=String(e).slice(0,40); }
    // 2) dataSource.setValue 시도.
    try { ds.setValue(row,'BFC_PARTNER_CD',code); out.ds_cd='ok'; } catch(e){ out.ds_cd=String(e).slice(0,40); }
    try { ds.setValue(row,'BFC_PARTNER_NM',name); out.ds_nm='ok'; } catch(e){ out.ds_nm=String(e).slice(0,40); }
    out.rc = ds.getRowCount();
    const j = ds.getJsonRows(row,row)[0]||{};
    out.readback = { BFC_PARTNER_CD:String(j.BFC_PARTNER_CD==null?'':j.BFC_PARTNER_CD), BFC_PARTNER_NM:String(j.BFC_PARTNER_NM==null?'':j.BFC_PARTNER_NM), PARTNER_NM:String(j.PARTNER_NM==null?'':j.PARTNER_NM) };
    // BFC 키가 실제 dataSource 필드에 존재하는지.
    out.has_bfc_key = Object.keys(j).filter(k=>/BFC/i.test(k));
  } catch(e){ out.err = String(e).slice(0,80); }
  return out;
}"""

async def main():
    pw=await async_playwright().start(); b=await pw.chromium.launch(headless=True)
    page=await b.new_page(viewport=LIVE_VIEWPORT); base=get_settings().erp_base
    try:
        await ensure_logged_in(page,'이트라이브2','1111',base); await ensure_user_type(page,'회계')
        await navigate_schema(page, EXPENSE_CARD, base)
        for _ in range(20):
            if await page.evaluate("(s)=>!!document.querySelector(s)", selectors.GUBUN_SELECT): break
            await page.wait_for_timeout(500)
        await page.evaluate(js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS, {"selector":selectors.GUBUN_SELECT,"text":"출장(국내·자차)"})
        await page.wait_for_timeout(1800); await js_click(page, selectors.BTN_ADD)
        for _ in range(33):
            await page.wait_for_timeout(300)
            if (await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS))>0: break
        await doc_steps.open_evdn_editor(page); await doc_steps.select_evdn_code(page,"10")
        await ts.fill_partner(page,"10512","한국도로공사"); await ts.fill_budget_fixed(page,"인사/기획팀","판관비")
        await ts.fill_project(page,{"code":"1310|1310","name":"포장개선"}); await ts.set_transaction_amount(page,12500)
        await ts.set_row_note(page,"통행료(현금)")
        r = await page.evaluate(SET_BFC_JS, ["2026032511","이트라이브2"])
        print("SET_BFC:", json.dumps(r, ensure_ascii=False))
        # 하단 폼 반영 확인.
        await page.evaluate(ts.js.COUNTER_SCROLL_JS); await page.wait_for_timeout(500)
        cinp = await page.evaluate(ts.js.COUNTER_INPUT_VAL_JS)
        print("COUNTER_INPUT_VAL:", cinp)
    except Exception as e:
        print("ERROR:", repr(e))
    finally:
        await b.close(); await pw.stop()
asyncio.run(main())
