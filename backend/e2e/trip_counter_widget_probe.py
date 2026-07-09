"""상대계정거래처 = 하단 내역 위젯(🔍 코드피커)로 입력 재검증 — 사용자 지목(2026-07-09).

실제 상대계정거래처 UI = detail 그리드가 아니라 **항목/내역코드/내역명 테이블**(상대계정거래처 행에
🔍 코드피커). BFC_PARTNER_CD 숨김필드 setValue 는 이름 미해석이라 헛세팅. 이 위젯 피커로 본인
선택 → 내역명 채워지나 + detail 행 리셋되나(과거 함정) + 저장 persist 를 실측한다.

⚠ 내역명 채워지고 리셋 없으면만 F7 1회 + F6 삭제. 아니면 저장 생략.
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

NAME = "이트라이브2"
CODE = "2026032511"

READ_DETAIL = r"""() => { try {
  const g=window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
  const n=g.getDataSource().getRowCount(); const row=Math.max(0,n-1);
  const r=g.getDataSource().getJsonRows(row,row)[0]||{};
  return {rc:n, PARTNER:String(r.PARTNER_NM||''), AMT:String(r.SPPRC_AMT2||''), NOTE:String(r.NOTE_DC||''),
          BFC_CD:String(r.BFC_PARTNER_CD||''), BFC_NM:String(r.BFC_PARTNER_NM==null?'':r.BFC_PARTNER_NM)};
} catch(e){ return {e:String(e).slice(0,90)}; } }"""

# '상대계정거래처' 라벨 주변 클릭 후보 전체(돋보기 아이콘 정체 파악용).
COUNTER_NEAR_JS = r"""() => {
  const c=s=>String(s==null?'':s).replace(/\s+/g,' ').trim();
  const lbl=[...document.querySelectorAll('label,span,div,td,th')].find(e=>e.offsetParent!==null && c(e.innerText)==='상대계정거래처');
  if(!lbl) return {found:false};
  const lr=lbl.getBoundingClientRect();
  const near=[...document.querySelectorAll('button,a,img,i,span,svg,.dews-codepicker-button')].filter(e=>{
    if(e.offsetParent===null) return false; const r=e.getBoundingClientRect();
    return r.width>0 && Math.abs(r.top-lr.top)<24 && r.left>lr.left-4 && r.left<lr.left+400;
  }).slice(0,12).map(e=>{const r=e.getBoundingClientRect();return {tag:e.tagName, cls:(e.className||'').toString().slice(0,50), x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2), w:Math.round(r.width)};});
  return {found:true, labelRect:{x:Math.round(lr.x),y:Math.round(lr.y)}, near};
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


async def open_counter_picker(page):
    """상대계정거래처 위젯 스크롤 → 🔍 클릭 → 거래처 팝업 오픈 폴링. 반환 opened(bool)."""
    if not await page.evaluate(tj.COUNTER_SCROLL_JS):
        return False
    await page.wait_for_timeout(500)
    box = await page.evaluate(tj.COUNTER_PICKER_BOX_JS)
    if not box:
        return False
    await mouse_click(page, box["x"], box["y"])
    for _ in range(20):  # 거래처 팝업 준비 폴링(~6s)
        await page.wait_for_timeout(300)
        n = await page.evaluate(js_lib.PICKER_ROWCOUNT_JS)
        if isinstance(n, int) and n >= 0:
            return True
    return False


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
        print("detail BEFORE:", await page.evaluate(READ_DETAIL))
        print("상대계정 위젯 주변:", await page.evaluate(COUNTER_NEAR_JS))

        opened = await open_counter_picker(page)
        print("counter picker opened:", opened)
        if opened:
            await _picker_search(page, NAME)
            read = await page.evaluate(js_lib.PICKER_READ_MULTI_JS, [ts.PARTNER_FIELDS, 0])
            row, err = ts.pick_partner_row(read.get("options") or [], NAME, CODE)
            print("pick:", "err=" + err if err else f"row i={row.get('i')} {row.get('PARTNER_NM')}({row.get('PARTNER_CD')})")
            if not err:
                await page.evaluate(js_lib.PICKER_SELECT_JS, row["i"])
                await page.wait_for_timeout(400)
                box = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
                if box:
                    await mouse_click(page, box["x"], box["y"])
                await page.wait_for_timeout(1800)
                # 스크롤 이동 전에 내역명 재독 + 전 행 덤프(서브디테일 vs 데이터 소실 구분).
                print("상대계정 내역명(위젯 재독, 스크롤전):", await page.evaluate(tj.COUNTER_INPUT_VAL_JS))
                READ_ALL = r"""() => { try {
                  const g=window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
                  const n=g.getDataSource().getRowCount(); const out=[];
                  for(let i=0;i<n;i++){ const r=g.getDataSource().getJsonRows(i,i)[0]||{};
                    out.push({i, PARTNER:String(r.PARTNER_NM||''), AMT:String(r.SPPRC_AMT2||''), NOTE:String(r.NOTE_DC||''),
                              BFC_CD:String(r.BFC_PARTNER_CD||''), EVDN:String(r.EVDN_TP_NM||''), RDOLINE:String(r.RDOLINE_SQ||''), DOLINE:String(r.DOLINE_SQ||'')}); }
                  return {n, rows:out};
                } catch(e){ return {e:String(e).slice(0,90)}; } }"""
                print("ALL rows AFTER apply:", await page.evaluate(READ_ALL))
                await page.evaluate(tj.RESET_SCROLL_TO_DETAIL_JS)
                await page.wait_for_timeout(500)
                after = await page.evaluate(READ_DETAIL)
                print("detail AFTER(last row):", after)
                reset = not after.get("PARTNER") or not after.get("AMT")
                print(">>> 리셋 여부:", "리셋됨(PARTNER/AMT 소실)" if reset else "정상(detail 유지)",
                      "· BFC_NM=", after.get("BFC_NM"))
                if not reset and (after.get("BFC_NM") or after.get("BFC_CD")):
                    print(">>> 위젯 입력 성공 — 실저장 검증")
                    await ts.set_master_total(page, 12500)
                    r = await card_steps.save_document(page, confirm=True)
                    print("save:", r.get("ok"), r.get("reason") or r.get("via"))
                    await qmaster(page)
                    await page.wait_for_timeout(500)
                    print("detail after save+requery:", await page.evaluate(READ_DETAIL))
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
                else:
                    print(">>> 저장 생략(리셋 or 미반영).")
    except Exception as e:  # noqa: BLE001
        print("ERROR:", repr(e))
        try:
            await page.screenshot(path=str(Path(__file__).resolve().parent / "artifacts" / "counter_widget_err.png"))
        except Exception:
            pass
    finally:
        await b.close()
        await pw.stop()


asyncio.run(main())
