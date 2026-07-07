"""상대계정거래처(BFC_PARTNER) 셀 적용 후 어떤 필드가 채워지는지 진단(읽기전용, 저장 없음).

리뷰 반영 셀검증에서 BFC_PARTNER_NM 이 적용 후 빈값으로 나와, 실제 반영 필드(CD vs NM,
raw vs display)를 확정하기 위한 1회 프로브. ⚠ F7 절대 금지.
Usage: cd backend && .venv/bin/python e2e/trip_bfc_probe.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright  # noqa: E402

from app.agents.trip_domestic import steps as trip_steps  # noqa: E402
from app.config import get_settings  # noqa: E402
from nbkit.browser.actions import js_click, mouse_click  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.omnisol.menu_schemas import EXPENSE_CARD  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

import os  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")

# detail 마지막 행 전체(getJsonRows)에서 값이 있는 BFC/거래처류 키만 골라 반환 — 적용값이
# 어느 필드에 저장되는지 확정용(getValue 는 BFC_* 에서 Invalid field index 로 실패함).
DUMP_JS = """() => {
  try {
    const ds = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid.getDataSource();
    const n = ds.getRowCount();
    const row = Math.max(0, n - 1);
    const j = ds.getJsonRows(row, row)[0] || {};
    const hit = {};
    for (const k of Object.keys(j)) {
      const v = j[k];
      if (v == null || v === '') continue;
      if (/PARTNER|BFC|PARTN|CUST|이트라이브/i.test(k) || String(v).includes('이트라이브')) hit[k] = String(v);
    }
    return { ok: true, row, hit };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 120) }; }
}"""


async def main() -> None:
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page(viewport=selectors.VIEWPORT)
    base = get_settings().erp_base
    try:
        print("[entry] login/회계/GLDDOC00300…", flush=True)
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await ensure_user_type(page, "회계")
        await navigate_schema(page, EXPENSE_CARD, base)
        for _ in range(20):
            if await page.evaluate("(s) => !!document.querySelector(s)", selectors.GUBUN_SELECT):
                break
            await page.wait_for_timeout(500)
        await page.evaluate(
            js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS,
            {"selector": selectors.GUBUN_SELECT, "text": "출장(국내·자차)"},
        )
        await page.wait_for_timeout(1_800)
        await js_click(page, selectors.BTN_ADD)
        for _ in range(33):
            await page.wait_for_timeout(300)
            if (await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)) > 0:
                break

        # 먼저 거래처(PARTNER_NM) 를 한국도로공사로 채운다(BFC 가 이걸 덮어쓰는지 확인용).
        fp = await trip_steps.fill_partner(page, "10512", "한국도로공사")
        print(f"[pre] fill_partner(한국도로공사): {fp}", flush=True)
        before = await page.evaluate(DUMP_JS)
        print(f"[pre] after 거래처 채움: {before}", flush=True)

        # BFC 셀 피커 열기 → 본인 검색 → 완전일치 선택 → 적용 (steps 내부 재사용).
        op = await trip_steps._open_detail_cell_picker(page, "BFC_PARTNER_NM", "상대계정거래처")
        print(f"[bfc] open picker: {op}", flush=True)
        await trip_steps._picker_search(page, USERID)
        read = await page.evaluate(js_lib.PICKER_READ_MULTI_JS, [trip_steps.PARTNER_FIELDS, 0])
        row, err = trip_steps.pick_partner_row(read.get("options") or [], USERID, None)
        print(f"[bfc] pick row: err={err} row_i={row.get('i') if row else None} nm={row.get('PARTNER_NM') if row else None}", flush=True)
        if row:
            sel = await page.evaluate(js_lib.PICKER_SELECT_JS, row["i"])
            print(f"[bfc] select: {sel}", flush=True)
            await page.wait_for_timeout(400)
            box = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
            print(f"[bfc] apply box: {box}", flush=True)
            if box:
                await mouse_click(page, box["x"], box["y"])
            # 적용 후 1초 간격으로 BFC 필드 raw+display 관찰(최대 10s).
            for t in range(10):
                await page.wait_for_timeout(1_000)
                d = await page.evaluate(DUMP_JS)
                rc = await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)
                mod = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
                print(f"[bfc] t={t+1}s rowcount={rc} dump={d} modals={[m.get('title') for m in (mod or [])]}", flush=True)
        await page.screenshot(path=str(Path(__file__).resolve().parent / "artifacts" / "trip_bfc_probe.png"))
        print("[done] 저장 없이 종료", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc!r}", flush=True)
    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
