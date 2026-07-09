"""상대계정거래처 = 내역코드 input 직접 타이핑 + Enter 로 이름 해석 시도(피커 '적용' 우회).

피커 '적용'은 빈 행을 추가하고 이름 미반영(2026-07-09 실측). 위젯 내역코드 텍스트박스에 코드를
직접 타이핑 후 Enter 하면(코드피커 change 핸들러) 내역명이 해석되나 + 행 추가 없나 확인. 저장 없음.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "/Users/wishdev/et-works/dashboard-design/backend")
from playwright.async_api import async_playwright  # noqa: E402

from app.agents.common import doc_steps  # noqa: E402
from app.agents.trip_domestic import js as tj, steps as ts  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT  # noqa: E402
from nbkit.browser.actions import js_click, mouse_click  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.omnisol.menu_schemas import EXPENSE_CARD  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

NAME = "이트라이브2"
CODE = "2026032511"

READ_ALL = r"""() => { try {
  const g=window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
  const n=g.getDataSource().getRowCount(); const out=[];
  for(let i=0;i<n;i++){ const r=g.getDataSource().getJsonRows(i,i)[0]||{};
    out.push({i, PARTNER:String(r.PARTNER_NM||''), AMT:String(r.SPPRC_AMT2||''), BFC_CD:String(r.BFC_PARTNER_CD||''), BFC_NM:String(r.BFC_PARTNER_NM==null?'':r.BFC_PARTNER_NM)}); }
  return {n, rows:out};
} catch(e){ return {e:String(e).slice(0,90)}; } }"""

# 상대계정거래처 행의 내역코드 <input> 좌표.
CODE_INPUT_JS = r"""() => {
  const c=s=>String(s==null?'':s).replace(/\s+/g,' ').trim();
  const lbl=[...document.querySelectorAll('label,span,div,td,th')].find(e=>e.offsetParent!==null && c(e.innerText)==='상대계정거래처');
  if(!lbl) return null;
  const lr=lbl.getBoundingClientRect();
  const inp=[...document.querySelectorAll('input')].filter(i=>i.offsetParent!==null && Math.abs(i.getBoundingClientRect().top-lr.top)<24 && i.getBoundingClientRect().left>lr.left)
    .sort((a,b)=>a.getBoundingClientRect().left-b.getBoundingClientRect().left)[0];
  if(!inp) return null;
  const r=inp.getBoundingClientRect();
  return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2), id:inp.id||'', val:inp.value||''};
}"""

# 상대계정거래처 행의 내역명(라벨 오른쪽 마지막 input 값) 재독.
NM_JS = r"""() => {
  const c=s=>String(s==null?'':s).replace(/\s+/g,' ').trim();
  const lbl=[...document.querySelectorAll('label,span,div,td,th')].find(e=>e.offsetParent!==null && c(e.innerText)==='상대계정거래처');
  if(!lbl) return null;
  const lr=lbl.getBoundingClientRect();
  return [...document.querySelectorAll('input')].filter(i=>i.offsetParent!==null && Math.abs(i.getBoundingClientRect().top-lr.top)<24 && i.getBoundingClientRect().left>lr.left).map(i=>c(i.value)).filter(Boolean);
}"""


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
        await ts.set_transaction_amount(page, 12500)
        await ts.set_row_note(page, "통행료(현금)")
        print("BEFORE:", await page.evaluate(READ_ALL))

        await page.evaluate(tj.COUNTER_SCROLL_JS)
        await page.wait_for_timeout(500)
        ci = await page.evaluate(CODE_INPUT_JS)
        print("내역코드 input:", ci)
        if ci:
            await mouse_click(page, ci["x"], ci["y"])
            await page.wait_for_timeout(200)
            # 기존값 지우고 코드 타이핑 + Enter.
            await page.keyboard.press("Control+A")
            await page.keyboard.type(CODE, delay=40)
            await page.wait_for_timeout(300)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(1800)
            print("내역명(타이핑+Enter 후):", await page.evaluate(NM_JS))
            print("AFTER:", await page.evaluate(READ_ALL))
    except Exception as e:  # noqa: BLE001
        print("ERROR:", repr(e))
    finally:
        await b.close()
        await pw.stop()


asyncio.run(main())
