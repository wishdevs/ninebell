"""세금계산서 잔존 전표 소재 진단 4차 — split 녹화 분석 단서(회계일 8/11 근방)로 좁혀 재조회.

split 녹화(tax_invoice_codegen_split.py) 는 회계일(ACTG_DT)을 날짜 위젯으로 "10"→"11" 로 바꾼
흔적이 있다. '회계일' 조회모드 + 일자를 11로 맞춰 재조회한다. 읽기 전용.

Usage: cd backend && .venv/bin/python e2e/tax_invoice_period_diag4.py
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
from nbkit.omnisol import selectors  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402

def _dump_rows(dump: dict) -> list[dict]:
    rows = dump.get("rows") or []
    return [
        {"ABDOCU_NO": r.get("ABDOCU_NO"), "ABDOCU_FG_CD": r.get("ABDOCU_FG_CD"),
         "WRT_EMP_NM": r.get("WRT_EMP_NM"), "ACTG_DT": r.get("ACTG_DT"), "WRT_DT": r.get("WRT_DT"),
         "DOCU_NO": r.get("DOCU_NO")}
        for r in rows
    ]


async def _set_day(page, value: str) -> None:
    box = await page.evaluate(
        "() => { const m = document.querySelector('#s_month'); if(!m) return null;"
        " const mr = m.getBoundingClientRect();"
        " const c = [...document.querySelectorAll('input')].filter(i => i.offsetParent!==null && i!==m"
        " && Math.abs(i.getBoundingClientRect().top-mr.top)<10 && i.getBoundingClientRect().left>mr.right"
        " && i.getBoundingClientRect().left<mr.right+120)[0];"
        " if(!c) return null; const r=c.getBoundingClientRect();"
        " return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)}; }"
    )
    if not box:
        return
    await page.mouse.click(box["x"], box["y"])
    await page.wait_for_timeout(150)
    await page.keyboard.press("End")
    for _ in range(4):
        await page.keyboard.press("Backspace")
    await page.keyboard.type(value)
    await page.keyboard.press("Tab")
    await page.wait_for_timeout(400)


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

        # 결의구분 전체(무필터)로.
        await page.evaluate(
            "(sel) => { const s=document.querySelector(sel); const w=window.jQuery(s).data('kendoDropDownList');"
            " if(w){w.value('');w.trigger('change');} }", selectors.GUBUN_SELECT,
        )
        await page.wait_for_timeout(500)

        # '결의일' 드롭다운을 '회계일'로 토글.
        dd_box = await page.evaluate(
            "() => { const l = [...document.querySelectorAll('span,div')].find(e=>e.offsetParent!==null"
            " && e.innerText && e.innerText.trim()==='결의일'); if(!l) return null;"
            " const w = l.closest('.k-dropdown') || l.parentElement; const r = w.getBoundingClientRect();"
            " return {x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2)}; }"
        )
        if dd_box:
            await page.mouse.click(dd_box["x"], dd_box["y"])
            await page.wait_for_timeout(400)
            opt2 = await page.evaluate(
                "() => { const it = [...document.querySelectorAll('li.k-item, .k-list li')]"
                ".filter(e=>e.offsetParent!==null).find(e=>e.innerText.includes('회계일'));"
                " if(!it) return null; const r = it.getBoundingClientRect();"
                " return {x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2)}; }"
            )
            if opt2:
                await page.mouse.click(opt2["x"], opt2["y"])
                await page.wait_for_timeout(500)

        for day in ("11", "10", "07", "08", "26"):
            await _set_day(page, day)
            rc = await query_master(page)
            dump = await page.evaluate(MASTER_DUMP_JS, 0)
            rows = _dump_rows(dump)
            print(f"[query 회계일=2026-08-{day}] rowcount={rc} rows={json.dumps(rows, ensure_ascii=False)}", flush=True)
            if rc and rc > 0:
                await page.screenshot(path=f"e2e/artifacts/tax_invoice_period_diag4_hit_{day}.png")

        await browser.close()
        await pw.stop()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc!r}", flush=True)
        try:
            await page.screenshot(path="e2e/artifacts/tax_invoice_period_diag4_exception.png")
        except Exception:  # noqa: BLE001
            pass
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
