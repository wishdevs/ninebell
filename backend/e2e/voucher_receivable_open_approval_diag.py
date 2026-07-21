"""읽기전용(+1회 필요악 팝업) 진단 — 2번째 결재(open_approval) 가 왜 새 Page 를 못 여는지.

부작용: row0 결재를 1회 열고 닫는다(EAP draft 1건, PROCESS.md 기지 이슈 범위) — row1 은 클릭까지만
하고 팝업이 안 뜨면 그 자체가 관측 대상이라 추가 draft 는 생기지 않는다(팝업이 안 열렸으므로).

계측: 콘솔 에러/pageerror 캡처, 클릭 좌표의 elementFromPoint, checked_row_indexes, 결재버튼
rect, window.open 호출 여부(임시 훅)까지 전부 덤프한다.

Usage:
    cd backend && .venv/bin/python e2e/voucher_receivable_open_approval_diag.py
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
from nbkit.browser.actions import mouse_click  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402
from nbkit.omnisol.menu_schemas import VOUCHER_RECEIVABLE  # noqa: E402

from app.agents.voucher_receivable import js, steps  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

ELEMENT_AT_POINT_JS = r"""([x, y]) => {
  const el = document.elementFromPoint(x, y);
  if (!el) return null;
  return {
    tag: el.tagName, cls: el.className, id: el.id,
    text: (el.innerText || '').slice(0, 60),
    closestButton: (() => { const b = el.closest('button'); return b ? (b.className + '|' + (b.innerText||'').trim()) : null; })(),
  };
}"""

WINDOW_OPEN_HOOK_JS = r"""() => {
  window.__openCalls = window.__openCalls || [];
  if (!window.__origOpen) {
    window.__origOpen = window.open;
    window.open = function(...args) {
      window.__openCalls.push(String(args[0] || ''));
      return window.__origOpen.apply(window, args);
    };
  }
  return true;
}"""


async def main() -> None:
    console_errors: list[str] = []
    page_errors: list[str] = []

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS)
    context = await browser.new_context(viewport=LIVE_VIEWPORT)
    raw_page = await context.new_page()
    page = _ScaledPage(raw_page, DELAY_SCALE)
    base = get_settings().erp_base

    raw_page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    raw_page.on("pageerror", lambda e: page_errors.append(str(e)))

    try:
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await ensure_user_type(page, "회계")
        await navigate_schema(page, VOUCHER_RECEIVABLE, base)
        await page.wait_for_timeout(1_500)

        await steps.expand_condition_panel(page)
        r = await steps.set_dept_all(page)
        print(f"[diag] dept={r}", flush=True)
        await steps.set_period_this_month(page)
        await steps.clear_writer(page)
        await steps.set_docu_status(page)
        await steps.set_gwaprvlst(page)
        await steps.set_docu_types(page)
        rq = await steps.run_query(page)
        print(f"[diag] run_query={rq}", flush=True)

        await raw_page.evaluate(WINDOW_OPEN_HOOK_JS)

        # ── row0: 베이스라인(정상 케이스) — 열고 즉시 닫는다 ──────────────────────
        key0 = await steps.read_row_key(page, 0)
        await steps.uncheck_all_rows(page)
        ok0 = await steps.check_row(page, 0)
        chk0 = await steps.checked_row_indexes(page)
        print(f"[diag] row0 key={key0} check_row_ok={ok0} checked_row_indexes={chk0}", flush=True)
        rect0 = await raw_page.evaluate(js.APPROVAL_BTN_RECT_JS)
        print(f"[diag] row0 approval rect={rect0}", flush=True)
        child0 = await steps.open_approval(page)
        print(f"[diag] row0 open_approval -> {'Page' if child0 else None}", flush=True)
        opens0 = await raw_page.evaluate("() => window.__openCalls || []")
        print(f"[diag] row0 window.open calls so far = {opens0}", flush=True)
        if child0 is not None:
            await steps.poll_child_ready(child0)
            await steps.close_child(child0)
        await steps.settle_parent_after_child_close(page, child0 or object())
        await raw_page.screenshot(path=str(ARTIFACTS / "voucher_receivable_open_approval_diag_after_row0.png"), full_page=True)

        # ── row1: 실패 재현 — 계측을 총동원 ──────────────────────────────────────
        key1 = await steps.read_row_key(page, 1)
        await steps.uncheck_all_rows(page)
        ok1 = await steps.check_row(page, 1)
        chk1 = await steps.checked_row_indexes(page)
        print(f"[diag] row1 key={key1} check_row_ok={ok1} checked_row_indexes={chk1}", flush=True)
        rect1 = await raw_page.evaluate(js.APPROVAL_BTN_RECT_JS)
        print(f"[diag] row1 approval rect={rect1}", flush=True)
        if rect1:
            elem = await raw_page.evaluate(ELEMENT_AT_POINT_JS, [rect1["x"], rect1["y"]])
            print(f"[diag] row1 elementFromPoint(rect)={elem}", flush=True)

        opens_before = await raw_page.evaluate("() => (window.__openCalls || []).length")
        new_page_seen = None
        try:
            async with context.expect_page(timeout=8_000) as page_info:
                await mouse_click(page, rect1["x"], rect1["y"])
                await page.wait_for_timeout(500)
        except Exception as exc:  # noqa: BLE001
            print(f"[diag] row1 expect_page raised: {exc!r}", flush=True)
        else:
            new_page_seen = await page_info.value
            print(f"[diag] row1 expect_page got page: {new_page_seen}", flush=True)

        opens_after = await raw_page.evaluate("() => window.__openCalls || []")
        print(f"[diag] row1 window.open calls total = {opens_after} (before-count={opens_before})", flush=True)

        chk1_after_click = await steps.checked_row_indexes(page)
        print(f"[diag] row1 checked_row_indexes AFTER click = {chk1_after_click}", flush=True)

        print(f"[diag] console_errors (n={len(console_errors)}) = {console_errors[-10:]}", flush=True)
        print(f"[diag] page_errors (n={len(page_errors)}) = {page_errors[-10:]}", flush=True)

        await raw_page.screenshot(path=str(ARTIFACTS / "voucher_receivable_open_approval_diag_row1_after_click.png"), full_page=True)
        (ARTIFACTS / "voucher_receivable_open_approval_diag.json").write_text(
            json.dumps(
                {
                    "row0": {"key": key0, "check_row_ok": ok0, "checked": chk0, "rect": rect0},
                    "row1": {
                        "key": key1, "check_row_ok": ok1, "checked": chk1, "rect": rect1,
                        "elementFromPoint": elem if rect1 else None,
                        "window_open_calls": opens_after,
                        "new_page_seen": bool(new_page_seen),
                        "checked_after_click": chk1_after_click,
                    },
                    "console_errors": console_errors,
                    "page_errors": page_errors,
                },
                ensure_ascii=False, indent=2, default=str,
            ),
            encoding="utf-8",
        )
        if new_page_seen is not None:
            await new_page_seen.close()

    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
