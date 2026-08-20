"""세금계산서 잔존 전표 조회 0건 원인 진단 2차 — '일자' 서브필드(19) 클리어/변경 시도.

1차 진단(tax_invoice_period_diag.py)은 결의일/회계일 모드 토글 + 부서/작성자/결의구분 무필터로도
0건이었다. 이번엔 아직 안 건드린 변수 — 상단 '결의일 2026-08 [icon] 19' 의 **일자 서브필드
(id 없음, 위치로만 탐색)**를 실제 키보드 조작(클릭+선택+삭제/변경)으로 넓혀본다. 읽기 전용.

Usage: cd backend && .venv/bin/python e2e/tax_invoice_period_diag2.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright  # noqa: E402

from app.config import get_settings  # noqa: E402
from e2e.product_cycle import MASTER_DUMP_JS, PASSWORD, USERID, query_master  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402

DAY_INPUT_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const month = document.querySelector('#s_month');
  if (!month) return null;
  const mr = month.getBoundingClientRect();
  const cand = [...document.querySelectorAll('input')].filter(i => {
    if (i.offsetParent === null || i === month) return false;
    const r = i.getBoundingClientRect();
    return Math.abs(r.top - mr.top) < 10 && r.left > mr.right && r.left < mr.right + 120;
  });
  if (!cand.length) return null;
  const i = cand[0];
  const r = i.getBoundingClientRect();
  return { value: c(i.value), x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2) };
}"""


def _dump_rows(dump: dict) -> list[dict]:
    rows = dump.get("rows") or []
    return [
        {"ABDOCU_NO": r.get("ABDOCU_NO"), "ABDOCU_FG_CD": r.get("ABDOCU_FG_CD"),
         "WRT_EMP_NM": r.get("WRT_EMP_NM"), "ACTG_DT": r.get("ACTG_DT"), "WRT_DT": r.get("WRT_DT"),
         "DOCU_NO": r.get("DOCU_NO")}
        for r in rows
    ]


async def main() -> None:
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page(viewport=selectors.VIEWPORT)
    base = get_settings().erp_base
    try:
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await page.goto(f"{base}/FI/GLDDOC00300")
        for _ in range(20):
            if await page.evaluate("(s) => !!document.querySelector(s)", selectors.GUBUN_SELECT):
                break
            await page.wait_for_timeout(1000)
        await page.wait_for_timeout(1500)

        day = await page.evaluate(DAY_INPUT_JS)
        print("[day_input]", day, flush=True)

        # 결의구분은 비워 전체(모든 문서종류) 조회 — 스코프를 최대한 넓힌다.
        await page.evaluate(
            "(sel) => { const s=document.querySelector(sel); const w=window.jQuery(s).data('kendoDropDownList');"
            " if(w){w.value('');w.trigger('change');} }", selectors.GUBUN_SELECT,
        )
        await page.wait_for_timeout(500)

        if day:
            await page.mouse.click(day["x"], day["y"])
            await page.wait_for_timeout(200)
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Delete")
            await page.keyboard.press("Tab")
            await page.wait_for_timeout(500)
            day_after = await page.evaluate(DAY_INPUT_JS)
            print("[day_input_after_clear]", day_after, flush=True)

        rc = await query_master(page)
        dump = await page.evaluate(MASTER_DUMP_JS, 0)
        print(f"[query 일자클리어, 결의구분=전체, 2026-08] rowcount={rc}", flush=True)
        print("[rows]", json.dumps(_dump_rows(dump), ensure_ascii=False), flush=True)
        await page.screenshot(path="e2e/artifacts/tax_invoice_period_diag2_daycleared.png")

        await browser.close()
        await pw.stop()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc!r}", flush=True)
        try:
            await page.screenshot(path="e2e/artifacts/tax_invoice_period_diag2_exception.png")
        except Exception:  # noqa: BLE001
            pass
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
