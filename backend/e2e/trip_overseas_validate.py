"""해외출장(trip-overseas) end-to-end 라이브 검증 — 공통 스텝 적용 확인 + 저장. 0.4 배율.

국내에서 확정한 type_amount(예산현황)/register_counter_partner(위젯)/delete_blank_row 를 해외에 적용.
해외 특유: 결의구분 '출장(해외·정산서)', 예산 '여비교통비-해외출장', 거래처=전 행 본인. 5000원.
⚠ F7 실저장 1회 + F6 삭제(가드레일). 처음 라이브라 결의구분/예산 존재 여부도 확인.
"""
import asyncio
import sys

sys.path.insert(0, "/Users/wishdev/et-works/dashboard-design/backend")
from playwright.async_api import async_playwright  # noqa: E402

from app.agents.card_collect import js as cc_js, steps as card_steps  # noqa: E402
from app.agents.common import doc_steps  # noqa: E402
from app.agents.trip_overseas import steps as ov  # noqa: E402
from app.agents.trip_domestic import js as tj  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT, _ScaledPage  # noqa: E402
from nbkit.browser.actions import js_click  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.omnisol.menu_schemas import EXPENSE_CARD  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402
from e2e.e2e_smoke import BTN_BOX_JS, MASTER_DUMP_JS, MASTER_ROWCOUNT_JS, SELECT_MASTER_JS  # noqa: E402

NAME, AMOUNT, GUBUN = "이트라이브2", 5000, "출장(해외·정산서)"

GUBUN_VAL_JS = """(s) => { const el=document.querySelector(s); return el ? (el.value||'') + ' | ' + (el.options ? [...el.options].map(o=>o.text).join(',').slice(0,120) : '') : null; }"""


async def qmaster(page):
    box = await page.evaluate(BTN_BOX_JS, selectors.BTN_LOOKUP)
    if box:
        await page.mouse.click(box["x"], box["y"])
    for _ in range(20):
        await page.wait_for_timeout(700)
        if isinstance(await page.evaluate(MASTER_ROWCOUNT_JS), int):
            break


async def main():
    pw = await async_playwright().start()
    b = await pw.chromium.launch(headless=True)
    raw = await b.new_page(viewport=LIVE_VIEWPORT)
    page = _ScaledPage(raw, 0.4)
    base = get_settings().erp_base
    try:
        await ensure_logged_in(page, NAME, "1111", base)
        await ensure_user_type(page, "회계")
        await navigate_schema(page, EXPENSE_CARD, base)
        for _ in range(20):
            if await page.evaluate("(s)=>!!document.querySelector(s)", selectors.GUBUN_SELECT):
                break
            await page.wait_for_timeout(500)
        print("결의구분 옵션:", await page.evaluate(GUBUN_VAL_JS, selectors.GUBUN_SELECT))
        await page.evaluate(js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS, {"selector": selectors.GUBUN_SELECT, "text": GUBUN})
        await page.wait_for_timeout(1800)
        print("설정 후 결의구분:", await page.evaluate(GUBUN_VAL_JS, selectors.GUBUN_SELECT))
        await js_click(page, selectors.BTN_ADD)
        for _ in range(33):
            await page.wait_for_timeout(300)
            if (await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)) > 0:
                break
        await doc_steps.open_evdn_editor(page)
        await doc_steps.select_evdn_code(page, "10")
        print("거래처(본인):", (await ov.fill_partner_by_search(page, NAME)).get("ok"))
        print("예산단위(해외출장):", (await ov.fill_budget_fixed(page, "인사/기획팀", "판관비")).get("ok"))
        await ov.fill_project(page, {"code": "1310|1310", "name": "포장개선"})
        print("type_amount:", await ov.type_amount(page, AMOUNT))
        print("set_row_note:", (await ov.set_row_note(page, "해외 일비")).get("ok"))
        LABELS = r"""() => { const c=s=>String(s==null?'':s).replace(/\s+/g,' ').trim();
          const ls=[...document.querySelectorAll('td,th,label,span,div')].filter(e=>e.offsetParent!==null).map(e=>c(e.innerText))
            .filter(t=>/상대계정|거래처계좌|결제조건|결제수단|업무용차량|귀속사업장|자금과목|사원/.test(t) && t.length<12);
          return {labels:[...new Set(ls)].slice(0,20), scroll:null}; }"""
        diag = await page.evaluate(LABELS)
        print("부가선택 관리항목 라벨:", diag.get("labels"))
        print("COUNTER_SCROLL(상대계정거래처 라벨 찾기):", await page.evaluate(tj.COUNTER_SCROLL_JS))
        print("register_counter_partner:", await ov.register_counter_partner(page, NAME))
        print("delete_blank_row:", await ov.delete_blank_row(page))
        print("set_master_total:", (await ov.set_master_total(page, AMOUNT)).get("ok"))
        print("상대계정 검증:", await page.evaluate(tj.COUNTER_VALS_JS), "· 행:", await page.evaluate(tj.DETAIL_ROWS_JS))

        r = await card_steps.save_document(page, confirm=True)
        print("\nsave_document:", r.get("ok"), "·", r.get("reason") or r.get("via"), "· 모달:", [m.get("title") for m in (r.get("modals_seen") or [])])

        await qmaster(page)
        await page.wait_for_timeout(500)
        dump = await page.evaluate(MASTER_DUMP_JS, 0)
        rows = dump.get("rows") or []
        ours = all(str(x.get("WRT_EMP_NM") or "").strip() == NAME and not str(x.get("DOCU_NO") or "").strip() for x in rows)
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
            print("문서 정리 완료")
        print("\n" + ("✅ 해외출장 end-to-end 저장 성공" if r.get("ok") else "❌ 저장 실패"))
    except Exception as e:  # noqa: BLE001
        print("ERROR:", repr(e))
    finally:
        await b.close()
        await pw.stop()


asyncio.run(main())
