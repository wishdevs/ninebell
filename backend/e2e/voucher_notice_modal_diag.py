"""읽기전용 진단 — 로그인 직후 뜨는 ERP/회사 공지 모달의 실제 DOM 구조를 덤프한다.

부작용 0 — 로그인·유형전환·메뉴진입만 하고 아무것도 클릭/제출하지 않는다.

Usage:
    cd backend && .venv/bin/python e2e/voucher_notice_modal_diag.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT, _ScaledPage  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402
from nbkit.omnisol.menu_schemas import VOUCHER_RECEIVABLE  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

DUMP_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  // '공지' 텍스트를 포함하는 모든 요소(리프 제한 없음)를 찾아 후보로 삼는다.
  const noticeEls = [...document.querySelectorAll('*')].filter(el => {
    const own = [...el.childNodes].filter(n => n.nodeType === 3).map(n => c(n.textContent)).join('');
    return own.includes('공지');
  }).slice(0, 20).map(el => ({
    tag: el.tagName, cls: el.className && el.className.toString ? el.className.toString() : String(el.className||''),
    id: el.id, text: c(el.innerText || el.textContent || '').slice(0, 40),
    visible: el.offsetParent !== null,
  }));
  // '닫기' 텍스트를 가진 버튼 전부.
  const closeBtns = [...document.querySelectorAll('button')].filter(b => c(b.innerText) === '닫기').map(b => {
    const r = b.getBoundingClientRect();
    return { cls: b.className, text: c(b.innerText), visible: b.offsetParent !== null, x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2) };
  });
  // 모달로 보이는 최상위 오버레이 컨테이너 후보(화면 대부분을 덮는 큰 fixed/absolute 요소).
  const bigOverlays = [...document.querySelectorAll('div')].filter(el => {
    const r = el.getBoundingClientRect();
    return r.width > 800 && r.height > 400 && el.offsetParent !== null;
  }).slice(0, 10).map(el => ({
    cls: el.className && el.className.toString ? el.className.toString() : String(el.className||''),
    id: el.id, w: Math.round(el.getBoundingClientRect().width), h: Math.round(el.getBoundingClientRect().height),
  }));
  return { noticeEls, closeBtns, bigOverlays };
}"""


async def main() -> None:
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS)
    context = await browser.new_context(viewport=LIVE_VIEWPORT)
    raw_page = await context.new_page()
    page = _ScaledPage(raw_page, DELAY_SCALE)
    base = get_settings().erp_base

    try:
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await ensure_user_type(page, "회계")
        await navigate_schema(page, VOUCHER_RECEIVABLE, base)
        await page.wait_for_timeout(1_500)

        dump = await raw_page.evaluate(DUMP_JS)
        print("[diag] noticeEls =", json.dumps(dump["noticeEls"], ensure_ascii=False, indent=2), flush=True)
        print("[diag] closeBtns =", json.dumps(dump["closeBtns"], ensure_ascii=False, indent=2), flush=True)
        print("[diag] bigOverlays =", json.dumps(dump["bigOverlays"], ensure_ascii=False, indent=2), flush=True)

        (ARTIFACTS / "voucher_notice_modal_diag.json").write_text(
            json.dumps(dump, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        await raw_page.screenshot(path=str(ARTIFACTS / "voucher_notice_modal_diag.png"), full_page=True)
        print(f"[artifact] {ARTIFACTS / 'voucher_notice_modal_diag.json'}", flush=True)
        print(f"[artifact] {ARTIFACTS / 'voucher_notice_modal_diag.png'}", flush=True)

    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
