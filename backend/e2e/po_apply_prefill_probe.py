"""라이브 검증 — apply_project: 프리필==검색어(ETRI-001 재적용) / 프리필≠검색어(2261→ETRI-001). 조회조건 확정만."""
from __future__ import annotations
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.async_api import async_playwright
from app.agents.purchase_order import steps
from app.config import get_settings
from app.live.runner import LIVE_VIEWPORT, _ScaledPage
from nbkit.omnisol.navigator import navigate_menu
from nbkit.patterns.login_flow import ensure_logged_in
from nbkit.patterns.user_type_flow import ensure_user_type

CASES = [("ETRIBE ERP TEST 001", "ETRI-001"), ("ZJ90-130", "2261"), ("ETRIBE ERP TEST 001", "ETRI-001"), ("ETRIBE ERP TEST 001", "ETRI-001")]
async def main():
    pw = await async_playwright().start(); browser = await pw.chromium.launch(headless=True)
    page = _ScaledPage(await browser.new_page(viewport=LIVE_VIEWPORT), 0.4); base = get_settings().erp_base
    await ensure_logged_in(page, "이트라이브2", "1111", base); await ensure_user_type(page, "SCM")
    await navigate_menu(page, "/PU/PUOPRQ00200_X20616", base, label="apply", grids_required=1); await page.wait_for_timeout(1500)
    for kw, no in CASES:
        r = await steps.apply_project(page, kw, no)
        print(f"[apply] {kw!r}/{no} → {json.dumps(r, ensure_ascii=False)[:200]}", flush=True)
        await page.wait_for_timeout(800)
    await browser.close(); await pw.stop()
asyncio.run(main())
