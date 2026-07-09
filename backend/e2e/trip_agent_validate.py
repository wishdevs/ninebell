"""실제 에이전트 스텝(steps.type_amount / register_counter_partner / delete_blank_row)으로
end-to-end 저장 검증 — 소스 반영분이 실동작하는지. 5000원. F7 실저장 1회 + F6 삭제(가드레일)."""
import asyncio
import sys

sys.path.insert(0, "/Users/wishdev/et-works/dashboard-design/backend")
from playwright.async_api import async_playwright  # noqa: E402

from app.agents.card_collect import js as cc_js, steps as card_steps  # noqa: E402
from app.agents.common import doc_steps  # noqa: E402
from app.agents.trip_domestic import js as tj, steps as ts  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT  # noqa: E402
from nbkit.browser.actions import js_click  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.omnisol.menu_schemas import EXPENSE_CARD  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402
from e2e.e2e_smoke import BTN_BOX_JS, MASTER_DUMP_JS, MASTER_ROWCOUNT_JS, SELECT_MASTER_JS  # noqa: E402

NAME, AMOUNT = "이트라이브2", 5000


async def qmaster(page):
    box = await page.evaluate(BTN_BOX_JS, selectors.BTN_LOOKUP)
    if box:
        await page.mouse.click(box["x"], box["y"])
    for _ in range(20):
        await page.wait_for_timeout(700)
        if isinstance(await page.evaluate(MASTER_ROWCOUNT_JS), int):
            break


async def main():
    from app.live.runner import _ScaledPage  # 실제 에이전트와 동일 조건 재현.

    pw = await async_playwright().start()
    b = await pw.chromium.launch(headless=True)
    raw_page = await b.new_page(viewport=LIVE_VIEWPORT)
    page = _ScaledPage(raw_page, 0.4)  # trip-domestic delay_scale=0.4
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

        # ── 실제 에이전트 스텝 ──
        print("type_amount:", await ts.type_amount(page, AMOUNT))
        print("set_row_note:", (await ts.set_row_note(page, "통행료(현금)")).get("ok"))
        print("register_counter_partner:", await ts.register_counter_partner(page, NAME))
        print("delete_blank_row:", await ts.delete_blank_row(page))
        print("set_master_total:", (await ts.set_master_total(page, AMOUNT)).get("ok"))
        print("상대계정 검증:", await page.evaluate(tj.COUNTER_VALS_JS), "· 행:", await page.evaluate(tj.DETAIL_ROWS_JS))

        # 저장(실제 save_document — 모달 예/확인 처리).
        r = await card_steps.save_document(page, confirm=True)
        print("\nsave_document:", r.get("ok"), "·", r.get("reason") or r.get("via"))
        print("모달:", [m.get("title") for m in (r.get("modals_seen") or [])])

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
                        await page.mouse.click(btn["x"], btn["y"]); break
            print("문서 정리 완료")
        print("\n" + ("✅ 소스 반영분 end-to-end 저장 성공" if r.get("ok") else "❌ 저장 실패"))
    except Exception as e:  # noqa: BLE001
        print("ERROR:", repr(e))
    finally:
        await b.close()
        await pw.stop()


asyncio.run(main())
