"""상대계정거래처 위젯 방식 end-to-end 검증 — 적용→빈행삭제→저장→재조회 persist→삭제.

확정 사실(2026-07-09): 부가선택 상대계정거래처 🔍 → 본인 검색 → 행 더블클릭 = 상대계정 등록
(내역코드/내역명). 부작용으로 detail 빈 행 1개 추가(ERP 동작) → 삭제 필요. 이 런에서:
  1) 위젯 적용 → 빈행 추가 확인
  2) row0 선택 → 상대계정 등록 확인(내역명=본인)
  3) 빈행 삭제(메커니즘 확정) → 1행 유지
  4) F7 저장 → 재조회 → row0 상대계정 persist 확인 → F6 삭제
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

DETAIL_ROW_CLICK = r"""(idx) => {
  const g=document.querySelectorAll('.dews-ui-grid')[1]; const r=g.getBoundingClientRect();
  return {x:Math.round(r.x+220), y:Math.round(r.y+34+idx*32+16)};  // 적요 컬럼(텍스트) row idx
}"""

# 빈 detail 행 삭제 시도(dataSource API 우선). 반환 {via, rc}.
DEL_ROW_JS = r"""(idx) => { try {
  const g=window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
  const ds=g.getDataSource(); let via='';
  if(typeof ds.removeRow==='function'){ ds.removeRow(idx); via='ds.removeRow'; }
  else if(typeof ds.removeRows==='function'){ ds.removeRows([idx]); via='ds.removeRows'; }
  else if(typeof g.deleteSelection==='function'){ g.setSelection({startRow:idx,endRow:idx,startColumn:0,endColumn:0}); g.deleteSelection(); via='g.deleteSelection'; }
  return {ok:true, via, rc:ds.getRowCount()};
} catch(e){ return {ok:false, e:String(e).slice(0,90)}; } }"""


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


async def apply_counter(page):
    await page.evaluate(tj.COUNTER_SCROLL_JS)
    await page.wait_for_timeout(500)
    box = await page.evaluate(tj.COUNTER_PICKER_BOX_JS)
    if not box:
        return False
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
        print("pick err:", err)
        return False
    rect = await page.evaluate(ROW_RECT_JS, row["i"])
    await page.mouse.dblclick(rect["x"], rect["y"])
    await page.wait_for_timeout(1800)
    return True


async def select_row0_read(page):
    pt = await page.evaluate(DETAIL_ROW_CLICK, 0)
    await mouse_click(page, pt["x"], pt["y"])
    await page.wait_for_timeout(1000)
    return await page.evaluate(COUNTER_READ_FULL)


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
        print("1) setup:", await page.evaluate(READ_ALL))

        if not await apply_counter(page):
            print("counter 적용 실패"); return
        print("2) apply 후:", await page.evaluate(READ_ALL))
        print("   row0 상대계정:", await select_row0_read(page))

        # 3) 빈 행 삭제 — 반드시 '마지막(추가된 빈)' 행을 대상으로. 시각 검증 스크린샷.
        cur = await page.evaluate(READ_ALL)
        # 빈 행 = PARTNER 없는 행 중 가장 마지막 인덱스(사용자 지적: 마지막 행을 지워야 함).
        blanks = [r["i"] for r in cur["rows"] if not r["PARTNER"]]
        blank_idx = max(blanks) if blanks else None
        print("3) 전체행:", cur, "→ 삭제대상(빈·마지막) idx:", blank_idx)
        if blank_idx is not None:
            # grid API 로도 현재행 지정 + 좌표 클릭 이중 확정.
            await page.evaluate("(i)=>{try{const g=window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;g.setCurrent({itemIndex:i,fieldName:(g.getColumns().find(c=>c.visible)||g.getColumns()[1]).fieldName});}catch(e){}}", blank_idx)
            pt = await page.evaluate(DETAIL_ROW_CLICK, blank_idx)
            await mouse_click(page, pt["x"], pt["y"])
            await page.wait_for_timeout(500)
            await page.screenshot(path=str(Path(__file__).resolve().parent / "artifacts" / "del_before.png"))
            dbox = await page.evaluate(BTN_BOX_JS, selectors.BTN_DELETE)
            if dbox:
                await page.mouse.click(dbox["x"], dbox["y"])
                for _ in range(6):
                    await page.wait_for_timeout(800)
                    ms = await page.evaluate(cc_js.MODALS_SNAPSHOT_JS)
                    if not ms:
                        break
                    print("   모달:", ms[:1] if isinstance(ms, list) else ms)
                    for lb in ("예", "확인", "삭제"):
                        btn = await page.evaluate(cc_js.MODAL_BTN_BOX_JS, lb)
                        if btn:
                            await page.mouse.click(btn["x"], btn["y"])
                            break
            await page.wait_for_timeout(800)
            await page.screenshot(path=str(Path(__file__).resolve().parent / "artifacts" / "del_after.png"))
        print("   삭제 후:", await page.evaluate(READ_ALL))
        print("   남은행 상대계정:", await select_row0_read(page))

        # 4) 저장 — 저장 전 그리드 편집 확정(헤드리스 미커밋 → DB오류 가설) + row0 포커스.
        await page.evaluate("""() => { try { const g=window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid; if(g.commit)g.commit(); if(g.getDataSource().commit)g.getDataSource().commit(); } catch(e){} }""")
        pt0 = await page.evaluate(DETAIL_ROW_CLICK, 0)
        await mouse_click(page, pt0["x"], pt0["y"])
        await page.wait_for_timeout(600)
        await ts.set_master_total(page, 12500)
        await page.keyboard.press("F7")
        seq = []
        for _ in range(24):
            await page.wait_for_timeout(700)
            toasts = await page.evaluate(cc_js.VALIDATION_TOAST_JS)
            if toasts:
                seq.append({"toast": toasts})
            modals = await page.evaluate(cc_js.MODALS_SNAPSHOT_JS)
            if modals:
                for m in modals:
                    seq.append({"title": m.get("title"), "text": (m.get("text") or "")[:110]})
                clicked = None
                for label in ("예", "확인"):
                    btn = await page.evaluate(cc_js.MODAL_BTN_BOX_JS, label)
                    if btn:
                        await page.mouse.click(btn["x"], btn["y"])
                        clicked = label
                        break
                seq.append({"clicked": clicked})
                continue
            if seq and not modals and not toasts:
                break
        print("4) save 모달 시퀀스:")
        for s in seq:
            print("   ", s)
        await page.wait_for_timeout(800)
        await qmaster(page)
        await page.wait_for_timeout(500)
        print("   재조회 detail:", await page.evaluate(READ_ALL))
        print("   재조회 row0 상대계정:", await select_row0_read(page))
        await page.screenshot(path=str(Path(__file__).resolve().parent / "artifacts" / "counter_final.png"))

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
            print("5) deleted doc -> after=", await qmaster(page))
    except Exception as e:  # noqa: BLE001
        print("ERROR:", repr(e))
    finally:
        await b.close()
        await pw.stop()


asyncio.run(main())
