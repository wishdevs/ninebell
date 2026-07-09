"""상대계정거래처 전체 플로우 — 영상 녹화 + 단계별 스크린샷(사용자가 화면을 볼 수 있게).

slow_mo 로 동작을 느리게, 매 단계 스크린샷(artifacts/steps/NN_label.png) + 영상(artifacts/video/).
플로우: 로그인→회계→결의서입력→출장국내→행추가→증빙10→거래처→예산→프로젝트→금액→적요
→상대계정(부가선택🔍→본인검색→더블클릭)→빈행삭제→F7저장(계좌번호 예)→DB오류 관찰.
⚠ 실저장 1회 시도 + 문서 삭제(가드레일).
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
ART = Path(__file__).resolve().parent / "artifacts"
STEPS = ART / "steps"
VID = ART / "video"
_step = 0

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
  return {x:Math.round(r.x+220), y:Math.round(r.y+34+idx*32+16)};
}"""


async def shot(page, label):
    global _step
    _step += 1
    await page.wait_for_timeout(250)
    await page.screenshot(path=str(STEPS / f"{_step:02d}_{label}.png"))
    print(f"  📸 {_step:02d}_{label}")


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


async def main():
    for d in (STEPS, VID):
        d.mkdir(parents=True, exist_ok=True)
    # 기존 step 스샷 정리(번호 꼬임 방지).
    for f in STEPS.glob("*.png"):
        f.unlink()
    pw = await async_playwright().start()
    b = await pw.chromium.launch(headless=True, slow_mo=280)  # 느리게 → 영상 보기 편하게.
    ctx = await b.new_context(viewport=LIVE_VIEWPORT, record_video_dir=str(VID))
    page = await ctx.new_page()
    base = get_settings().erp_base
    try:
        await ensure_logged_in(page, NAME, "1111", base)
        await ensure_user_type(page, "회계")
        await navigate_schema(page, EXPENSE_CARD, base)
        for _ in range(20):
            if await page.evaluate("(s)=>!!document.querySelector(s)", selectors.GUBUN_SELECT):
                break
            await page.wait_for_timeout(500)
        await shot(page, "결의서입력_열림")

        await page.evaluate(js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS, {"selector": selectors.GUBUN_SELECT, "text": "출장(국내·자차)"})
        await page.wait_for_timeout(1800)
        await shot(page, "결의구분_출장국내")
        await js_click(page, selectors.BTN_ADD)
        for _ in range(33):
            await page.wait_for_timeout(300)
            if (await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)) > 0:
                break
        await shot(page, "행추가_F3")
        await doc_steps.open_evdn_editor(page)
        await doc_steps.select_evdn_code(page, "10")
        await shot(page, "증빙_10")
        await ts.fill_partner(page, "10512", "한국도로공사")
        await shot(page, "거래처_한국도로공사")
        await ts.fill_budget_fixed(page, "인사/기획팀", "판관비")
        await shot(page, "예산단위")
        await ts.fill_project(page, {"code": "1310|1310", "name": "포장개선"})
        await shot(page, "프로젝트")
        await ts.set_transaction_amount(page, 12500)
        await shot(page, "금액_12500")
        await ts.set_row_note(page, "통행료(현금)")
        await shot(page, "적요")

        # 상대계정 — 부가선택 🔍.
        await page.evaluate(tj.COUNTER_SCROLL_JS)
        await page.wait_for_timeout(500)
        await shot(page, "부가선택_스크롤")
        box = await page.evaluate(tj.COUNTER_PICKER_BOX_JS)
        await mouse_click(page, box["x"], box["y"])
        for _ in range(20):
            await page.wait_for_timeout(300)
            n = await page.evaluate(js_lib.PICKER_ROWCOUNT_JS)
            if isinstance(n, int) and n >= 0:
                break
        await shot(page, "거래처팝업_열림")
        await _picker_search(page, NAME)
        await shot(page, "본인검색_이트라이브2")
        read = await page.evaluate(js_lib.PICKER_READ_MULTI_JS, [ts.PARTNER_FIELDS, 0])
        row, err = ts.pick_partner_row(read.get("options") or [], NAME, CODE)
        rect = await page.evaluate(ROW_RECT_JS, row["i"])
        await page.mouse.dblclick(rect["x"], rect["y"])
        await page.wait_for_timeout(1800)
        await shot(page, "더블클릭적용_빈행추가됨")
        print("   apply 후:", await page.evaluate(READ_ALL))

        # 원행 선택 → 상대계정 확인.
        pt = await page.evaluate(DETAIL_ROW_CLICK, 0)
        await mouse_click(page, pt["x"], pt["y"])
        await page.wait_for_timeout(1000)
        await shot(page, "원행선택_상대계정보임")
        print("   원행 상대계정:", await page.evaluate(COUNTER_READ_FULL))

        # 빈(마지막) 행 선택 → 삭제.
        cur = await page.evaluate(READ_ALL)
        blanks = [r["i"] for r in cur["rows"] if not r["PARTNER"]]
        blank_idx = max(blanks) if blanks else None
        if blank_idx is not None:
            pt = await page.evaluate(DETAIL_ROW_CLICK, blank_idx)
            await mouse_click(page, pt["x"], pt["y"])
            await page.wait_for_timeout(400)
            await shot(page, f"빈행선택_idx{blank_idx}")
            dbox = await page.evaluate(BTN_BOX_JS, selectors.BTN_DELETE)
            await page.mouse.click(dbox["x"], dbox["y"])
            for _ in range(6):
                await page.wait_for_timeout(800)
                ms = await page.evaluate(cc_js.MODALS_SNAPSHOT_JS)
                if not ms:
                    break
                for lb in ("예", "확인", "삭제"):
                    btn = await page.evaluate(cc_js.MODAL_BTN_BOX_JS, lb)
                    if btn:
                        await page.mouse.click(btn["x"], btn["y"])
                        break
            await page.wait_for_timeout(600)
            await shot(page, "빈행삭제_후")
        print("   삭제 후:", await page.evaluate(READ_ALL))

        # 저장.
        await ts.set_master_total(page, 12500)
        await page.keyboard.press("F7")
        for _ in range(24):
            await page.wait_for_timeout(700)
            modals = await page.evaluate(cc_js.MODALS_SNAPSHOT_JS)
            toasts = await page.evaluate(cc_js.VALIDATION_TOAST_JS)
            if modals:
                title = (modals[0].get("title") or "")[:10]
                await shot(page, f"저장모달_{title}")
                for lb in ("예", "확인"):
                    btn = await page.evaluate(cc_js.MODAL_BTN_BOX_JS, lb)
                    if btn:
                        await page.mouse.click(btn["x"], btn["y"])
                        print(f"   모달 '{modals[0].get('title')}' → {lb} 클릭")
                        break
                continue
            if toasts:
                print("   toast:", toasts)
            await page.wait_for_timeout(300)
            if not modals and not toasts and _step > 20:
                break
        await shot(page, "저장_최종상태")

        # 문서 삭제(가드레일).
        await qmaster(page)
        await page.wait_for_timeout(500)
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
                        await page.mouse.click(btn["x"], btn["y"])
                        break
            print("   문서정리 후:", await qmaster(page))
    except Exception as e:  # noqa: BLE001
        print("ERROR:", repr(e))
        await shot(page, "ERROR")
    finally:
        vpath = None
        try:
            vpath = await page.video.path()
        except Exception:
            pass
        await ctx.close()
        await b.close()
        await pw.stop()
        print(f"\n🎬 영상: {vpath}")
        print(f"🖼  스텝 스샷: {STEPS}")


asyncio.run(main())
