"""금액(공급가액=거래금액) = 셀 에디터 실제 타이핑 + '확인' 팝업 처리 검증 — 5000원.

사용자 규명(2026-07-09): 금액 입력 시 ERP 트리거 발화 → 확인 팝업 → 확인 눌러야 완료, 저장 가능.
setValue 는 이 트리거를 안 거쳐 파생상태 미완 → 저장 DB오류였음. 이 프로브: 금액 5000 을 에디터에
타이핑→Enter→확인 팝업 클릭→SPPRC_AMT2/SPPRC_AMT/TOTAL_AMT 가 5000 으로 반영되는지 확인. 저장X.
"""
import asyncio
import sys

sys.path.insert(0, "/Users/wishdev/et-works/dashboard-design/backend")
from playwright.async_api import async_playwright  # noqa: E402

from app.agents.card_collect import js as cc_js  # noqa: E402
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
AMOUNT = 5000

READ_ALL_ROWS = r"""() => { try {
  const g=window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
  const n=g.getDataSource().getRowCount(); const out=[];
  for(let i=0;i<n;i++){ const r=g.getDataSource().getJsonRows(i,i)[0]||{}; out.push({i, PARTNER:String(r.PARTNER_NM||''), AMT:String(r.SPPRC_AMT2||'')}); }
  return {n, rows:out};
} catch(e){ return {e:String(e).slice(0,80)}; } }"""

COUNTER_READ_FULL = r"""() => {
  const c=s=>String(s==null?'':s).replace(/\s+/g,' ').trim();
  const lbl=[...document.querySelectorAll('label,span,div,td,th')].find(e=>e.offsetParent!==null && c(e.innerText)==='상대계정거래처');
  if(!lbl) return {found:false};
  const lr=lbl.getBoundingClientRect();
  return {found:true, vals:[...document.querySelectorAll('input')].filter(i=>i.offsetParent!==null && Math.abs(i.getBoundingClientRect().top-lr.top)<26 && i.getBoundingClientRect().left>lr.left).map(i=>c(i.value))};
}"""

PICKER_ROW_RECT_JS = r"""(rowIndex) => {
  const c=s=>String(s==null?'':s).replace(/\s+/g,' ').trim();
  const p=[...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];
  if(!p) return null; const gridEl=p.querySelector('.dews-ui-grid'); if(!gridEl) return null;
  const gr=gridEl.getBoundingClientRect();
  return {x:Math.round(gr.x+150), y:Math.round(gr.y+30+rowIndex*32+16)};
}"""

DETAIL_ROW_CLICK = r"""(idx) => {
  const g=document.querySelectorAll('.dews-ui-grid')[1]; const r=g.getBoundingClientRect();
  return {x:Math.round(r.x+220), y:Math.round(r.y+34+idx*32+16)};
}"""


async def qmaster_cleanup(page):
    box = await page.evaluate(BTN_BOX_JS, selectors.BTN_LOOKUP)
    if box:
        await page.mouse.click(box["x"], box["y"])
    for _ in range(20):
        await page.wait_for_timeout(700)
        if isinstance(await page.evaluate(MASTER_ROWCOUNT_JS), int):
            break
    dump = await page.evaluate(MASTER_DUMP_JS, 0)
    rows = dump.get("rows") or []
    ours = all(str(x.get("WRT_EMP_NM") or "").strip() == NAME and str(x.get("ABDOCU_FG_CD") or "") == "53" and not str(x.get("DOCU_NO") or "").strip() for x in rows)
    if dump.get("n", 0) > 0 and ours:
        await page.evaluate(SELECT_MASTER_JS, 0)
        dbox = await page.evaluate(BTN_BOX_JS, selectors.BTN_DELETE)
        if dbox:
            await page.mouse.click(dbox["x"], dbox["y"])
        for _ in range(8):
            await page.wait_for_timeout(1000)
            ms = await page.evaluate(cc_js.MODALS_SNAPSHOT_JS)
            if not ms:
                break
            for lb in ("예", "확인", "삭제"):
                btn = await page.evaluate(cc_js.MODAL_BTN_BOX_JS, lb)
                if btn:
                    await page.mouse.click(btn["x"], btn["y"]); break
        print("   문서 정리 완료")

# 금액 셀 에디터 = gridDetail_number(숫자 입력 오버레이). w>10 로 접힌 input(_line, w=1) 배제.
EDITOR_INPUT_JS = r"""() => {
  const inp=[...document.querySelectorAll('input')].find(i=>/gridDetail_number/.test(i.id||'') && i.offsetParent!==null && i.getBoundingClientRect().width>10);
  if(!inp) return null; const r=inp.getBoundingClientRect();
  return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2), id:inp.id||'', val:inp.value||''};
}"""

READ_AMTS = r"""() => { try {
  const ds=window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid.getDataSource();
  const r=ds.getJsonRows(ds.getRowCount()-1, ds.getRowCount()-1)[0]||{};
  return {rc:ds.getRowCount(), PARTNER:String(r.PARTNER_NM||''), SPPRC_AMT2:String(r.SPPRC_AMT2||''),
          SPPRC_AMT:String(r.SPPRC_AMT||''), TOTAL_AMT:String(r.TOTAL_AMT||'')};
} catch(e){ return {e:String(e).slice(0,80)}; } }"""


async def type_amount_with_confirm(page, amount):
    """SPPRC_AMT2 에디터 열기 → 숫자 input 에 직접 focus·치환 타이핑 → Enter → 확인 팝업 처리."""
    await page.keyboard.press("Escape")  # 잔여 에디터 정리.
    await page.wait_for_timeout(300)
    op = await page.evaluate(js_lib.OPEN_DETAIL_CELL_EDITOR_JS, "SPPRC_AMT2")
    if not op.get("ok"):
        return {"ok": False, "reason": f"에디터 열기 실패: {op.get('reason')}"}
    await page.wait_for_timeout(600)
    rect = await page.evaluate(EDITOR_INPUT_JS)
    if not rect:
        return {"ok": False, "reason": "숫자 에디터 input 없음"}
    active = await page.evaluate("() => (document.activeElement&&document.activeElement.id)||'(none)'")
    print(f"   숫자에디터 id={rect['id']} 기존값='{rect['val']}' · 현재 focus={active}")
    await page.screenshot(path="/Users/wishdev/et-works/dashboard-design/backend/e2e/artifacts/amt_editor.png")
    # 숫자 input 을 id 로 직접 잡아 focus·기존값 선택·치환 입력(마우스 좌표 대신).
    loc = page.locator(f'#{rect["id"]}')
    await loc.click()
    await page.wait_for_timeout(150)
    await loc.select_text()  # 기존 '0' 선택(Meta+a 는 에디터 닫힘 유발).
    await page.wait_for_timeout(100)
    await loc.press_sequentially(str(amount), delay=110)
    await page.wait_for_timeout(250)
    active2 = await page.evaluate("() => (document.activeElement&&document.activeElement.id)||'(none)'")
    val_now = await page.evaluate("() => { const i=[...document.querySelectorAll('input')].find(x=>/gridDetail_number/.test(x.id||'')&&x.offsetParent); return i?i.value:'(gone)'; }")
    print(f"   타이핑 후 focus={active2} · 에디터 현재값='{val_now}'")
    await loc.press("Tab")  # Tab 커밋 → blur/change 트리거(Enter 보다 핸들러 발화 확실).
    confirms = []
    for _ in range(8):
        await page.wait_for_timeout(700)
        modals = await page.evaluate(cc_js.MODALS_SNAPSHOT_JS)
        if modals:
            for m in modals:
                confirms.append({"title": m.get("title"), "text": (m.get("text") or "")[:70]})
            clicked = None
            for lb in ("확인", "예"):
                btn = await page.evaluate(cc_js.MODAL_BTN_BOX_JS, lb)
                if btn:
                    await page.mouse.click(btn["x"], btn["y"])
                    clicked = lb
                    break
            confirms.append({"clicked": clicked})
            continue
        break
    return {"ok": True, "confirms": confirms[:6]}


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
        print("금액 입력 전:", await page.evaluate(READ_AMTS))

        print(f"▶ 금액 {AMOUNT} 타이핑 + 확인 팝업 처리…")
        res = await type_amount_with_confirm(page, AMOUNT)
        print("   결과:", res)
        after = await page.evaluate(READ_AMTS)
        print("금액 입력 후:", after)
        ok = after.get("SPPRC_AMT2") in (str(AMOUNT), f"{AMOUNT:,}")
        print(f"\n{'✅ 5000원 정상 기입' if ok else '❌ 금액 반영 실패/불일치'} — SPPRC_AMT2={after.get('SPPRC_AMT2')}")
        if not ok:
            return

        # ── 이어서: 상대계정 등록 → 빈행 삭제 → 저장(계좌번호 예) → DB오류 사라졌나 확인 ──
        await ts.set_row_note(page, "통행료(현금)")
        print("\n▶ 상대계정거래처 = 본인 등록…")
        row = None
        for att in range(3):
            scrolled = await page.evaluate(tj.COUNTER_SCROLL_JS)
            if not scrolled:
                print(f"   ({att}) COUNTER_SCROLL=False(라벨 못찾음)"); await page.wait_for_timeout(600); continue
            await page.wait_for_timeout(700)
            pbox = await page.evaluate(tj.COUNTER_PICKER_BOX_JS)
            if not pbox:
                print(f"   ({att}) 피커버튼 없음"); await page.wait_for_timeout(600); continue
            await mouse_click(page, pbox["x"], pbox["y"])
            n = -1
            for _ in range(25):
                await page.wait_for_timeout(300)
                n = await page.evaluate(js_lib.PICKER_ROWCOUNT_JS)
                if isinstance(n, int) and n > 50:
                    break
            await _picker_search(page, NAME)
            await page.wait_for_timeout(600)
            rd = await page.evaluate(js_lib.PICKER_READ_MULTI_JS, [ts.PARTNER_FIELDS, 0])
            row, err = ts.pick_partner_row(rd.get("options") or [], NAME, "2026032511")
            print(f"   ({att}) rowcount={n} pick={'OK i='+str(row['i']) if row else err}")
            if not err:
                break
            await page.evaluate(js_lib.PICKER_CLOSE_JS); await page.wait_for_timeout(500)
        if row:
            rr = await page.evaluate(PICKER_ROW_RECT_JS, row["i"])
            await page.mouse.dblclick(rr["x"], rr["y"])
            await page.wait_for_timeout(1800)
            # 원행 선택해서 상대계정 읽기(빈행이 현재행이면 안 보임).
            pt0 = await page.evaluate(DETAIL_ROW_CLICK, 0)
            await mouse_click(page, pt0["x"], pt0["y"])
            await page.wait_for_timeout(800)
        print("   상대계정(원행):", await page.evaluate(COUNTER_READ_FULL), "· 행:", await page.evaluate(READ_ALL_ROWS))

        # 빈(마지막) 행 삭제.
        allrows = await page.evaluate(READ_ALL_ROWS)
        blanks = [r["i"] for r in allrows["rows"] if not r["PARTNER"]]
        if blanks:
            bi = max(blanks)
            pt = await page.evaluate(DETAIL_ROW_CLICK, bi)
            await mouse_click(page, pt["x"], pt["y"])
            await page.wait_for_timeout(400)
            dbox = await page.evaluate(BTN_BOX_JS, selectors.BTN_DELETE)
            await page.mouse.click(dbox["x"], dbox["y"])
            for _ in range(6):
                await page.wait_for_timeout(700)
                ms = await page.evaluate(cc_js.MODALS_SNAPSHOT_JS)
                if not ms:
                    break
                for lb in ("예", "확인", "삭제"):
                    btn = await page.evaluate(cc_js.MODAL_BTN_BOX_JS, lb)
                    if btn:
                        await page.mouse.click(btn["x"], btn["y"]); break
            await page.wait_for_timeout(600)
        print("   삭제 후 행:", await page.evaluate(READ_ALL_ROWS))

        # 저장.
        await ts.set_master_total(page, AMOUNT)
        await page.keyboard.press("F7")
        seq = []
        for _ in range(24):
            await page.wait_for_timeout(700)
            modals = await page.evaluate(cc_js.MODALS_SNAPSHOT_JS)
            if modals:
                seq.append({"title": modals[0].get("title"), "text": (modals[0].get("text") or "")[:60]})
                for lb in ("예", "확인"):
                    btn = await page.evaluate(cc_js.MODAL_BTN_BOX_JS, lb)
                    if btn:
                        await page.mouse.click(btn["x"], btn["y"]); seq.append({"clicked": lb}); break
                continue
            if seq:
                break
        print("\n▶ 저장 모달 시퀀스:")
        for s in seq:
            print("   ", s)
        db_err = any("오류" in (s.get("title") or "") for s in seq)
        print(f"\n{'❌ 아직 DB 오류' if db_err else '✅ DB 오류 없이 저장 시퀀스 통과'}")

        # 문서 정리(가드레일).
        await qmaster_cleanup(page)
    except Exception as e:  # noqa: BLE001
        print("ERROR:", repr(e))
    finally:
        await b.close()
        await pw.stop()


asyncio.run(main())
