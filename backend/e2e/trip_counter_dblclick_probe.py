"""상대계정거래처 위젯 피커 — 행 '더블클릭'으로 적용(수동과 동일). '적용' 버튼은 빈 행을 추가해
실패했으나, 사용자 확인상 수동은 선택 즉시 내역명이 뜬다 → 더블클릭(=RealGrid 즉시 적용)을 재현.

내역명 채워지고 detail 행 추가 없으면 F7 1회 + F6 삭제로 persist 검증. 아니면 저장 생략.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "/Users/wishdev/et-works/dashboard-design/backend")
from playwright.async_api import async_playwright  # noqa: E402

from app.agents.card_collect import js as cc_js, steps as card_steps  # noqa: E402
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
from e2e.e2e_smoke import BTN_BOX_JS, MASTER_DUMP_JS, MASTER_ROWCOUNT_JS, SELECT_MASTER_JS  # noqa: E402

NAME, CODE = "이트라이브2", "2026032511"

READ_ALL = r"""() => { try {
  const g=window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
  const n=g.getDataSource().getRowCount(); const out=[];
  for(let i=0;i<n;i++){ const r=g.getDataSource().getJsonRows(i,i)[0]||{};
    out.push({i, PARTNER:String(r.PARTNER_NM||''), AMT:String(r.SPPRC_AMT2||''), BFC_CD:String(r.BFC_PARTNER_CD||'')}); }
  return {n, rows:out};
} catch(e){ return {e:String(e).slice(0,90)}; } }"""

# 피커 팝업 그리드에서 rowIndex 행의 화면 좌표(더블클릭용). RealGrid getCellBounds 시도 + 폴백.
ROW_RECT_JS = r"""(rowIndex) => {
  const c=s=>String(s==null?'':s).replace(/\s+/g,' ').trim();
  const p=[...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];
  if(!p) return null;
  const gridEl=p.querySelector('.dews-ui-grid'); if(!gridEl) return null;
  const gr=gridEl.getBoundingClientRect();
  // getCellBounds 가 화면좌표계와 안 맞아 팝업 밖(그리드 하단)을 반환함(실측) → 그리드 rect 기준
  // 추정 사용: 헤더 ~30px + 행높이 ~32px. 거래처명 컬럼 근처(left+150) 클릭.
  return {x:Math.round(gr.x+150), y:Math.round(gr.y+30+rowIndex*32+16), via:'estimate', gtop:Math.round(gr.y)};
}"""


async def qmaster(page):
    box = await page.evaluate(BTN_BOX_JS, selectors.BTN_LOOKUP)
    if box:
        await page.mouse.click(box["x"], box["y"])
    prev, st, rc = -2, 0, -1
    for _ in range(25):
        await page.wait_for_timeout(800)
        rc = await page.evaluate(MASTER_ROWCOUNT_JS)
        if isinstance(rc, int) and rc >= 0 and rc == prev:
            st += 1
            if st >= 2:
                break
        else:
            st = 0
        prev = rc
    return rc


async def setup_row(page):
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


async def cleanup(page):
    dump = await page.evaluate(MASTER_DUMP_JS, 0)
    rows = dump.get("rows") or []
    ours = all(str(x.get("WRT_EMP_NM") or "").strip() == NAME and str(x.get("ABDOCU_FG_CD") or "") == "53" and not str(x.get("DOCU_NO") or "").strip() for x in rows)
    if dump.get("n", 0) > 0 and ours:
        await page.evaluate(SELECT_MASTER_JS, 0)
        dbox = await page.evaluate(BTN_BOX_JS, selectors.BTN_DELETE)
        if dbox:
            await page.mouse.click(dbox["x"], dbox["y"])
        for _ in range(8):
            await page.wait_for_timeout(1200)
            ms = await page.evaluate(cc_js.MODALS_SNAPSHOT_JS)
            if not ms:
                break
            for lb in ("예", "확인", "삭제"):
                btn = await page.evaluate(cc_js.MODAL_BTN_BOX_JS, lb)
                if btn:
                    await page.mouse.click(btn["x"], btn["y"])
                    break
        await page.wait_for_timeout(1000)
        print(f"deleted -> after={await qmaster(page)}")


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
        await setup_row(page)
        print("BEFORE:", await page.evaluate(READ_ALL))

        # 상대계정 적용이 새 행을 추가하는 원인 = detail 현재행 미확정 가설 → row 0 을 현재행으로 확정.
        SET_CUR0 = r"""() => { try {
          const g=window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
          const cols=g.getColumns(); const f=(cols.find(c=>c.visible)||cols[7]).fieldName;
          g.setCurrent({itemIndex:0, fieldName:f}); if(g.commit)g.commit();
          return {ok:true};
        } catch(e){ return {e:String(e).slice(0,80)}; } }"""
        print("setCurrent row0:", await page.evaluate(SET_CUR0))
        await page.wait_for_timeout(400)
        # 위젯 피커 열기.
        await page.evaluate(tj.COUNTER_SCROLL_JS)
        await page.wait_for_timeout(500)
        box = await page.evaluate(tj.COUNTER_PICKER_BOX_JS)
        if not box:
            print("no picker button"); return
        await mouse_click(page, box["x"], box["y"])
        for _ in range(20):
            await page.wait_for_timeout(300)
            n = await page.evaluate(js_lib.PICKER_ROWCOUNT_JS)
            if isinstance(n, int) and n >= 0:
                break
        await _picker_search(page, NAME)
        read = await page.evaluate(js_lib.PICKER_READ_MULTI_JS, [ts.PARTNER_FIELDS, 0])
        row, err = ts.pick_partner_row(read.get("options") or [], NAME, CODE)
        if err:
            print("pick err:", err); return
        print("pick row i=", row["i"], "| n_options=", len(read.get("options") or []))
        # 열린 팝업들 진단 + 검색 상태 스크린샷.
        WINS = r"""() => [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null).map(w=>{
          const t=(w.querySelector('.k-window-title')||{}).innerText||''; const r=w.getBoundingClientRect();
          return {title:String(t).trim().slice(0,30), x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height)};})"""
        print("open k-windows:", await page.evaluate(WINS))
        await page.screenshot(path=str(Path(__file__).resolve().parent / "artifacts" / "counter_pick_searched.png"))
        # 행 더블클릭(수동 = 선택 즉시 적용).
        rect = await page.evaluate(ROW_RECT_JS, row["i"])
        print("row rect:", rect)
        if rect:
            await page.mouse.dblclick(rect["x"], rect["y"])
            await page.wait_for_timeout(1800)
        await page.screenshot(path=str(Path(__file__).resolve().parent / "artifacts" / "counter_pick_after.png"))
        after = await page.evaluate(READ_ALL)
        print("AFTER apply (행 추가는 ERP 동작):", after)

        # 원래 행(row 0)을 실제 클릭해 현재행으로 → 부가선택 위젯이 row 0 기준으로 갱신됨.
        DETAIL_ROW0_CLICK = r"""() => {
          const g=document.querySelectorAll('.dews-ui-grid')[1]; const r=g.getBoundingClientRect();
          return {x:Math.round(r.x+220), y:Math.round(r.y+34+16)};  // 적요 컬럼(텍스트) row 0
        }"""
        pt = await page.evaluate(DETAIL_ROW0_CLICK)
        await mouse_click(page, pt["x"], pt["y"])
        await page.wait_for_timeout(1000)

        # 부가선택 상대계정거래처 행의 내역코드+내역명 전량(빈값 포함).
        COUNTER_READ_FULL = r"""() => {
          const c=s=>String(s==null?'':s).replace(/\s+/g,' ').trim();
          const lbl=[...document.querySelectorAll('label,span,div,td,th')].find(e=>e.offsetParent!==null && c(e.innerText)==='상대계정거래처');
          if(!lbl) return {found:false};
          const lr=lbl.getBoundingClientRect();
          const inputs=[...document.querySelectorAll('input')].filter(i=>i.offsetParent!==null && Math.abs(i.getBoundingClientRect().top-lr.top)<26 && i.getBoundingClientRect().left>lr.left).map(i=>({id:i.id||'', v:i.value||''}));
          return {found:true, inputs};
        }"""
        print("row0 선택 후 부가선택 상대계정:", await page.evaluate(COUNTER_READ_FULL))
        print("row0 detail BFC:", await page.evaluate(READ_ALL))
        await page.screenshot(path=str(Path(__file__).resolve().parent / "artifacts" / "counter_verify_row0.png"))
        return  # 검증만 — 저장/삭제는 결과 보고 결정.

        ok = False
        nm: list = []
        if ok and any(NAME in v or "2026032511" in v for v in (nm or [])):
            print(">>> 성공(내역명 반영·행 추가 없음) — 실저장 검증")
            await ts.set_master_total(page, 12500)
            r = await card_steps.save_document(page, confirm=True)
            print("save:", r.get("ok"), r.get("reason") or r.get("via"))
            await qmaster(page)
            await page.wait_for_timeout(500)
            print("detail after save+requery:", await page.evaluate(READ_ALL))
            print("상대계정 내역명 재조회:", await page.evaluate(tj.COUNTER_INPUT_VAL_JS))
            await cleanup(page)
        else:
            print(">>> 저장 생략(내역명 미반영 or 행 추가).")
    except Exception as e:  # noqa: BLE001
        print("ERROR:", repr(e))
    finally:
        await b.close()
        await pw.stop()


asyncio.run(main())
