"""금액 셀(SPPRC_AMT2) 에디터 타겟 진단 — showEditor 후 어떤 input 이 뜨는지 + 컬럼 편집속성."""
import asyncio
import sys

sys.path.insert(0, "/Users/wishdev/et-works/dashboard-design/backend")
from playwright.async_api import async_playwright  # noqa: E402

from app.agents.common import doc_steps  # noqa: E402
from app.agents.trip_domestic import steps as ts  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT  # noqa: E402
from nbkit.browser.actions import js_click  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.omnisol.menu_schemas import EXPENSE_CARD  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

NAME = "이트라이브2"

DUMP_INPUTS = r"""() => {
  const c=s=>String(s==null?'':s).replace(/\s+/g,' ').trim();
  return [...document.querySelectorAll('input')].filter(i=>i.offsetParent!==null).map(i=>{
    const r=i.getBoundingClientRect();
    return {id:i.id||'', name:i.name||'', val:c(i.value), x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width)};
  });
}"""

# SPPRC_AMT2 컬럼 편집 속성 + 그리드 내 위치.
COL_INFO = r"""() => { try {
  const g=window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
  const cols=g.getColumns();
  const info=cols.filter(c=>/SPPRC_AMT2|SPPRC_AMT|TOTAL_AMT|PARTNER_NM/.test(c.fieldName||'')).map(c=>({
    field:c.fieldName, header:(c.header&&c.header.text)||c.header, editable:c.editable, editor:(c.editor&&c.editor.type)||null, visible:c.visible}));
  let cb=null; try{ const n=g.getDataSource().getRowCount(); cb=g.getCellBounds&&g.getCellBounds(n-1,'SPPRC_AMT2'); }catch(e){}
  return {cols:info, spprcBounds:cb};
} catch(e){ return {e:String(e).slice(0,100)}; } }"""


async def main():
    pw = await async_playwright().start()
    b = await pw.chromium.launch(headless=True)
    page = await b.new_page(viewport=LIVE_VIEWPORT)
    base = get_settings().erp_base
    try:
        await ensure_logged_in(page, NAME, "1111", base)
        await ensure_user_type(page, "회계")
        await navigate_schema(page, EXPENSE_CARD, base)
        for _ in range(20):
            if await page.evaluate("(s)=>!!document.querySelector(s)", selectors.GUBUN_SELECT):
                break
            await page.wait_for_timeout(500)
        await page.evaluate(js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS, {"selector": selectors.GUBUN_SELECT, "text": "출장(국내·자차)"})
        await page.wait_for_timeout(1800)
        await js_click(page, selectors.BTN_ADD)
        for _ in range(33):
            await page.wait_for_timeout(300)
            if (await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)) > 0:
                break
        await doc_steps.open_evdn_editor(page)
        await doc_steps.select_evdn_code(page, "10")
        await ts.fill_partner(page, "10512", "한국도로공사")
        await ts.fill_budget_fixed(page, "인사/기획팀", "판관비")
        await ts.fill_project(page, {"code": "1310|1310", "name": "포장개선"})

        print("=== 컬럼 정보 ===")
        print(await page.evaluate(COL_INFO))
        print("\n=== showEditor 전 visible inputs ===")
        for i in await page.evaluate(DUMP_INPUTS):
            print("  ", i)
        print("\n=== OPEN_DETAIL_CELL_EDITOR_JS('SPPRC_AMT2') 실행 ===")
        print("  ", await page.evaluate(js_lib.OPEN_DETAIL_CELL_EDITOR_JS, "SPPRC_AMT2"))
        await page.wait_for_timeout(700)
        print("=== showEditor 후 visible inputs ===")
        for i in await page.evaluate(DUMP_INPUTS):
            print("  ", i)
    except Exception as e:  # noqa: BLE001
        print("ERROR:", repr(e))
    finally:
        await b.close()
        await pw.stop()


asyncio.run(main())
