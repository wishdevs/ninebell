"""BFC_PARTNER_CD setValue 가 저장된 전표에 상대계정으로 persist 되는지 실저장 검증 → 삭제.
⚠ F7 저장 1회 + F6 삭제(가드레일). 상신 금지."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0,'/Users/wishdev/et-works/dashboard-design/backend')
from playwright.async_api import async_playwright
from app.agents.card_collect import steps as card_steps, js as cc_js
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
from e2e.e2e_smoke import BTN_BOX_JS, MASTER_DUMP_JS, MASTER_ROWCOUNT_JS, SELECT_MASTER_JS

SET_BFC = r"""(code) => { try {
  const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
  const ds=g.getDataSource(); const n=ds.getRowCount(); const row=Math.max(0,n-1);
  g.setValue(row,'BFC_PARTNER_CD',code);
  return {ok:true, after:String(ds.getJsonRows(row,row)[0].BFC_PARTNER_CD), rc:ds.getRowCount()};
} catch(e){ return {ok:false, e:String(e).slice(0,80)}; } }"""
READ_BFC = r"""() => { try {
  const ds=window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid.getDataSource();
  const n=ds.getRowCount(); const rows=n>0?ds.getJsonRows(0,n-1):[];
  return rows.map(r=>({BFC:String(r.BFC_PARTNER_CD==null?'':r.BFC_PARTNER_CD), PARTNER:String(r.PARTNER_NM==null?'':r.PARTNER_NM)}));
} catch(e){ return {e:String(e).slice(0,80)}; } }"""

async def qmaster(page):
    box=await page.evaluate(BTN_BOX_JS, selectors.BTN_LOOKUP)
    if box: await page.mouse.click(box["x"],box["y"])
    prev,st,rc=-2,0,-1
    for _ in range(25):
        await page.wait_for_timeout(800); rc=await page.evaluate(MASTER_ROWCOUNT_JS)
        if isinstance(rc,int) and rc>=0 and rc==prev:
            st+=1
            if st>=2: break
        else: st=0
        prev=rc
    return rc

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
        await ts.set_row_note(page,"통행료(현금)"); await ts.set_master_total(page,12500)
        sb=await page.evaluate(SET_BFC,"2026032511")
        print("SET_BFC:", sb, "detail before save:", await page.evaluate(READ_BFC))
        # 저장.
        r=await card_steps.save_document(page, confirm=True)
        print("save:", r.get("ok"), r.get("reason") or r.get("via"))
        await page.wait_for_timeout(800)
        # 재조회 후 저장된 detail BFC 읽기.
        await qmaster(page); await page.wait_for_timeout(500)
        print("detail after save+requery:", await page.evaluate(READ_BFC))
        # 삭제(가드레일: 결의자+fg53+미결).
        dump=await page.evaluate(MASTER_DUMP_JS,0); rows=dump.get("rows") or []
        ours=all(str(x.get("WRT_EMP_NM") or "").strip()=="이트라이브2" and str(x.get("ABDOCU_FG_CD") or "")=="53" and not str(x.get("DOCU_NO") or "").strip() for x in rows)
        print(f"delete guardrail: n={dump.get('n')} all_ours={ours}")
        if dump.get("n",0)>0 and ours:
            await page.evaluate(SELECT_MASTER_JS,0)
            dbox=await page.evaluate(BTN_BOX_JS, selectors.BTN_DELETE)
            if dbox: await page.mouse.click(dbox["x"],dbox["y"])
            for _ in range(8):
                await page.wait_for_timeout(1200); ms=await page.evaluate(cc_js.MODALS_SNAPSHOT_JS)
                if not ms: break
                for lb in ("예","확인","삭제"):
                    btn=await page.evaluate(cc_js.MODAL_BTN_BOX_JS,lb)
                    if btn: await page.mouse.click(btn["x"],btn["y"]); break
            await page.wait_for_timeout(1000); after=await qmaster(page)
            print(f"deleted -> after={after}")
    except Exception as e:
        print("ERROR:", repr(e))
    finally:
        await b.close(); await pw.stop()
asyncio.run(main())
