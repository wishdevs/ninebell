"""상대계정거래처 이름(BFC_PARTNER_NM) 채우기 fix-probe — 여러 접근을 한 세션에서 시험.

배경(2026-07-09 진단): BFC_PARTNER_CD 직접 setValue 는 코드만 저장되고 이름(BFC_PARTNER_NM)이
비어 화면에 상대계정거래처가 안 보인다. 정상 코드피커 '적용' 경로는 이름을 해석한다 → 상대계정
셀 피커로 여는 방법을 찾는다.

시도(저장 없이 in-memory 확인 → 되는 접근으로만 실저장+재조회+삭제):
  A) BFC_PARTNER_CD 셀 피커 open → 본인 검색·선택·적용 → BFC_NM 채워지나?
  B) setValue(BFC_PARTNER_CD) 후 grid commit/refresh → 이름 해석되나?
  C) setValue(BFC_PARTNER_NM) 직접 → 설정되나(Invalid field index?)?

⚠ F7 저장은 A 성공 시 1회만 + F6 삭제(가드레일). 상신 금지.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "/Users/wishdev/et-works/dashboard-design/backend")
from playwright.async_api import async_playwright  # noqa: E402

from app.agents.card_collect import js as cc_js, steps as card_steps  # noqa: E402
from app.agents.common import doc_steps  # noqa: E402
from app.agents.trip_domestic import steps as ts  # noqa: E402
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

READ_BFC = r"""() => { try {
  const ds=window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid.getDataSource();
  const n=ds.getRowCount(); const r=n>0?ds.getJsonRows(n-1,n-1)[0]:{};
  return {rc:n, BFC_CD:String(r.BFC_PARTNER_CD==null?'':r.BFC_PARTNER_CD), BFC_NM:String(r.BFC_PARTNER_NM==null?'':r.BFC_PARTNER_NM),
          keys: Object.keys(r).filter(k=>/BFC/.test(k))};
} catch(e){ return {e:String(e).slice(0,90)}; } }"""

# setValue + commit/refresh 변형(이름 해석 트리거 시도).
SET_COMMIT = r"""(code) => { try {
  const g=window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
  const ds=g.getDataSource(); const row=Math.max(0,ds.getRowCount()-1);
  g.setValue(row,'BFC_PARTNER_CD',code);
  const tried=[];
  for (const m of ['commit','refresh','update','commitChanges']) { try { if (typeof g[m]==='function'){ g[m](); tried.push('g.'+m); } } catch(e){} }
  for (const m of ['commitChanges','update']) { try { if (typeof ds[m]==='function'){ ds[m](); tried.push('ds.'+m); } } catch(e){} }
  const r=ds.getJsonRows(row,row)[0]||{};
  return {ok:true, tried, BFC_CD:String(r.BFC_PARTNER_CD||''), BFC_NM:String(r.BFC_PARTNER_NM||'')};
} catch(e){ return {ok:false,e:String(e).slice(0,90)}; } }"""

# BFC_PARTNER_NM 직접 setValue 시도(설정 가능/Invalid field index 여부).
SET_NM = r"""(nm) => { try {
  const g=window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
  const row=Math.max(0,g.getDataSource().getRowCount()-1);
  g.setValue(row,'BFC_PARTNER_NM',nm);
  const r=g.getDataSource().getJsonRows(row,row)[0]||{};
  return {ok:true, BFC_NM:String(r.BFC_PARTNER_NM==null?'':r.BFC_PARTNER_NM)};
} catch(e){ return {ok:false,e:String(e).slice(0,90)}; } }"""


async def try_picker_on(page, field: str):
    """detail 셀 field 피커 open → 본인 검색·선택·적용 → 결과 read. 반환 (opened, read_after)."""
    op = await ts._open_detail_cell_picker(page, field, f"상대계정({field})")
    if not op.get("ok"):
        return {"open": op}
    await _picker_search(page, NAME)
    read = await page.evaluate(js_lib.PICKER_READ_MULTI_JS, [ts.PARTNER_FIELDS, 0])
    row, err = ts.pick_partner_row(read.get("options") or [], NAME, CODE)
    if err:
        await page.evaluate(js_lib.PICKER_CLOSE_JS)
        await page.wait_for_timeout(400)
        return {"open": op, "pick_err": err}
    sel = await page.evaluate(js_lib.PICKER_SELECT_JS, row["i"])
    await page.wait_for_timeout(400)
    box = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
    if box:
        await mouse_click(page, box["x"], box["y"])
    await page.wait_for_timeout(1500)
    return {"open": op, "sel": sel, "applied": bool(box), "read": await page.evaluate(READ_BFC)}


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


async def maybe_save_and_cleanup(page):
    await ts.set_master_total(page, 12500)
    r = await card_steps.save_document(page, confirm=True)
    print("save:", r.get("ok"), r.get("reason") or r.get("via"))
    await page.wait_for_timeout(800)
    await qmaster(page)
    await page.wait_for_timeout(500)
    print("detail after save+requery:", await page.evaluate(READ_BFC))
    dump = await page.evaluate(MASTER_DUMP_JS, 0)
    rows = dump.get("rows") or []
    ours = all(str(x.get("WRT_EMP_NM") or "").strip() == NAME and str(x.get("ABDOCU_FG_CD") or "") == "53" and not str(x.get("DOCU_NO") or "").strip() for x in rows)
    print(f"delete guardrail: n={dump.get('n')} all_ours={ours}")
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
        print("baseline:", await page.evaluate(READ_BFC))

        # C) BFC_PARTNER_NM 직접 setValue.
        print("C set_nm:", await page.evaluate(SET_NM, NAME))
        # B) setValue(CD)+commit/refresh.
        print("B set+commit:", await page.evaluate(SET_COMMIT, CODE))
        # A) BFC_PARTNER_CD 셀 피커.
        a_cd = await try_picker_on(page, "BFC_PARTNER_CD")
        print("A picker BFC_PARTNER_CD:", a_cd)

        after = await page.evaluate(READ_BFC)
        print("state after attempts:", after)

        # 결정적: 상대계정 컬럼이 화면에 뭘 '표시'하나(코드 바인딩+이름 룩업이면 표시는 이름일 수 있음).
        DISPLAY = r"""() => { try {
          const g=window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
          const n=g.getDataSource().getRowCount(); const row=Math.max(0,n-1);
          const disp=(g.getDisplayValuesOfRow?g.getDisplayValuesOfRow(row):{})||{};
          const cols=(g.getColumns?g.getColumns():[]).filter(c=>/BFC|상대/.test((c.fieldName||'')+'|'+(c.header&&c.header.text||c.header||'')));
          return { bfcDisplay: Object.fromEntries(Object.entries(disp).filter(([k])=>/BFC/.test(k))),
                   bfcCols: cols.map(c=>({field:c.fieldName, header:(c.header&&c.header.text)||c.header, lookup: c.lookupDisplay||c.values||null, visible:c.visible})) };
        } catch(e){ return {e:String(e).slice(0,120)}; } }"""
        print("DISPLAY 상대계정:", await page.evaluate(DISPLAY))
        if after.get("BFC_NM"):
            print(">>> BFC_NM 채워짐 — 실저장 검증 진행")
            await maybe_save_and_cleanup(page)
        else:
            print(">>> 아직 이름 미해석 — 저장 생략(전표 미생성).")
    except Exception as e:  # noqa: BLE001
        print("ERROR:", repr(e))
    finally:
        await b.close()
        await pw.stop()


asyncio.run(main())
