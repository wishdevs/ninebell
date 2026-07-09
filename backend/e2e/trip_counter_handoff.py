"""상대계정거래처 입력까지만 자동 진행 후 브라우저를 열어둔 채 대기(사람이 이어서 저장 테스트).

headless=False + slow_mo 로 화면에 창이 뜨고 천천히 진행. 상대계정 등록까지만 하고 빈행 삭제·
저장은 하지 않고 30분간 창을 유지 → 사용자가 그 창에서 직접 빈행 삭제 + F7 저장을 해본다.
"""
import asyncio
import sys

sys.path.insert(0, "/Users/wishdev/et-works/dashboard-design/backend")
from playwright.async_api import async_playwright  # noqa: E402

from app.agents.common import doc_steps  # noqa: E402
from app.agents.trip_domestic import js as tj, steps as ts  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT  # noqa: E402
from nbkit.browser.actions import js_click, mouse_click  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.omnisol.codepicker import _picker_search  # noqa: E402
from nbkit.omnisol.menu_schemas import EXPENSE_CARD  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

NAME, CODE = "이트라이브2", "2026032511"

READ_ALL = r"""() => { try {
  const g=window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
  const n=g.getDataSource().getRowCount(); const out=[];
  for(let i=0;i<n;i++){ const r=g.getDataSource().getJsonRows(i,i)[0]||{};
    out.push({i, PARTNER:String(r.PARTNER_NM||''), AMT:String(r.SPPRC_AMT2||'')}); }
  return {n, rows:out};
} catch(e){ return {e:String(e).slice(0,90)}; } }"""

COUNTER_READ_FULL = r"""() => {
  const c=s=>String(s==null?'':s).replace(/\s+/g,' ').trim();
  const lbl=[...document.querySelectorAll('label,span,div,td,th')].find(e=>e.offsetParent!==null && c(e.innerText)==='상대계정거래처');
  if(!lbl) return {found:false};
  const lr=lbl.getBoundingClientRect();
  const inputs=[...document.querySelectorAll('input')].filter(i=>i.offsetParent!==null && Math.abs(i.getBoundingClientRect().top-lr.top)<26 && i.getBoundingClientRect().left>lr.left).map(i=>c(i.value));
  return {found:true, vals:inputs};
}"""

ROW_RECT_JS = r"""(rowIndex) => {
  const c=s=>String(s==null?'':s).replace(/\s+/g,' ').trim();
  const p=[...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];
  if(!p) return null; const gridEl=p.querySelector('.dews-ui-grid'); if(!gridEl) return null;
  const gr=gridEl.getBoundingClientRect();
  return {x:Math.round(gr.x+150), y:Math.round(gr.y+30+rowIndex*32+16)};
}"""

EDITOR_INPUT_JS = r"""() => {
  const inp=[...document.querySelectorAll('input')].find(i=>/gridDetail_line|gridDetail|_editor/.test(i.id||'') && i.offsetParent!==null);
  if(!inp) return null; const r=inp.getBoundingClientRect();
  return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2), id:inp.id||''};
}"""

READ_AMTS = r"""() => { try {
  const ds=window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid.getDataSource();
  const r=ds.getJsonRows(ds.getRowCount()-1, ds.getRowCount()-1)[0]||{};
  return {SPPRC_AMT2:String(r.SPPRC_AMT2||''), SPPRC_AMT:String(r.SPPRC_AMT||''), TOTAL_AMT:String(r.TOTAL_AMT||'')};
} catch(e){ return {e:String(e).slice(0,80)}; } }"""


async def type_amount(page, amount):
    """공급가액(거래금액) SPPRC_AMT2 셀 에디터를 열어 **실제 타이핑 + Enter**(ERP 계산 핸들러 발화)."""
    op = await page.evaluate(js_lib.OPEN_DETAIL_CELL_EDITOR_JS, "SPPRC_AMT2")
    if not op.get("ok"):
        return {"ok": False, "reason": op.get("reason")}
    await page.wait_for_timeout(500)
    rect = await page.evaluate(EDITOR_INPUT_JS)
    if not rect:
        return {"ok": False, "reason": "에디터 input 없음"}
    await mouse_click(page, rect["x"], rect["y"])
    await page.wait_for_timeout(150)
    await page.keyboard.press("Meta+A")  # mac 전체선택(Control+A 는 줄맨앞 이동이라 기존 0 이 남음).
    await page.keyboard.press("Backspace")
    await page.keyboard.type(str(amount), delay=70)
    await page.wait_for_timeout(200)
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(900)
    return {"ok": True, "editor": rect.get("id")}


async def main():
    pw = await async_playwright().start()
    b = await pw.chromium.launch(headless=False, slow_mo=350, args=["--window-size=1480,1000", "--window-position=40,40"])
    page = await b.new_page(viewport=LIVE_VIEWPORT)
    base = get_settings().erp_base
    try:
        print("▶ 로그인·메뉴 진입…")
        await ensure_logged_in(page, NAME, "1111", base)
        await ensure_user_type(page, "회계")
        await navigate_schema(page, EXPENSE_CARD, base)
        for _ in range(20):
            if await page.evaluate("(s)=>!!document.querySelector(s)", selectors.GUBUN_SELECT):
                break
            await page.wait_for_timeout(500)

        print("▶ 출장(국내·자차) + 행 + 필드 채우기…")
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
        print("▶ 금액 = 셀 에디터에 실제 타이핑(핸들러 발화 시도)…")
        amt = await type_amount(page, 12500)
        print("   금액 타이핑:", amt, "→ 필드값:", await page.evaluate(READ_AMTS))
        await ts.set_row_note(page, "통행료(현금)")

        print("▶ 상대계정거래처 = 본인(이트라이브2) 등록…")
        row = None
        for attempt in range(3):
            if not await page.evaluate(tj.COUNTER_SCROLL_JS):
                await page.wait_for_timeout(600)
                continue
            await page.wait_for_timeout(700)
            box = await page.evaluate(tj.COUNTER_PICKER_BOX_JS)
            if not box:
                await page.wait_for_timeout(600)
                continue
            await mouse_click(page, box["x"], box["y"])
            n = -1
            for _ in range(25):  # 거래처 목록 로드까지(대량 행) 대기.
                await page.wait_for_timeout(300)
                n = await page.evaluate(js_lib.PICKER_ROWCOUNT_JS)
                if isinstance(n, int) and n > 50:
                    break
            await _picker_search(page, NAME)
            await page.wait_for_timeout(600)
            read = await page.evaluate(js_lib.PICKER_READ_MULTI_JS, [ts.PARTNER_FIELDS, 0])
            row, err = ts.pick_partner_row(read.get("options") or [], NAME, CODE)
            if not err:
                break
            print(f"   상대계정 검색 재시도({attempt+1}) — rowcount={n}, err={err}")
            await page.evaluate(js_lib.PICKER_CLOSE_JS)
            await page.wait_for_timeout(600)
        if row:
            rect = await page.evaluate(ROW_RECT_JS, row["i"])
            await page.mouse.dblclick(rect["x"], rect["y"])
            await page.wait_for_timeout(1800)
        else:
            print("!! 상대계정 본인 검색 3회 실패 — 창은 열어두니 수동으로 상대계정만 넣어보세요.")

        # 원행 선택해서 상대계정 보이게 두고 대기.
        g = document_row0_click_js()
        pt = await page.evaluate(g, 0)
        await mouse_click(page, pt["x"], pt["y"])
        await page.wait_for_timeout(800)
        print("\n================ 준비 완료 ================")
        print("detail 행:", await page.evaluate(READ_ALL))
        print("상대계정거래처:", await page.evaluate(COUNTER_READ_FULL))
        print("\n👉 이제 이 브라우저 창에서 직접 해보세요:")
        print("   1) 추가된 빈(마지막) 행 선택 → 상단 툴바 삭제 버튼")
        print("   2) F7(또는 저장) → 계좌번호 팝업 '예' → 저장되는지 확인")
        print("   창은 30분간 열어둡니다. 끝나면 알려주세요(제가 종료).")
        print("==========================================\n")
        await asyncio.sleep(1800)  # 30분 대기(브라우저 유지).
    except Exception as e:  # noqa: BLE001
        print("ERROR:", repr(e))
        await asyncio.sleep(600)
    finally:
        await b.close()
        await pw.stop()


def document_row0_click_js():
    return r"""(idx) => {
      const g=document.querySelectorAll('.dews-ui-grid')[1]; const r=g.getBoundingClientRect();
      return {x:Math.round(r.x+220), y:Math.round(r.y+34+idx*32+16)};
    }"""


asyncio.run(main())
