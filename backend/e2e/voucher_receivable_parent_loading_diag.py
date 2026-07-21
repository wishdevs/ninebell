"""읽기전용(+1회 필요악 팝업) 진단 — close_child 직후 부모 페이지에 실제로 뜨는 로딩
인디케이터를 시간축으로 스캔한다(도메인전문가 확정 근본원인: 팝업 닫힘→본창 로딩→그 로딩이
끝나기 전에 다음 행 결제를 누르면 실패).

부작용: row0 결재를 1회 열고 닫는다(EAP draft 1건) — 그 이후는 순수 관찰(폴링)만, row1 은
건드리지 않는다(클릭 자체를 안 함 — 이번 진단은 '무엇이 뜨는지'만 본다).

Usage:
    cd backend && .venv/bin/python e2e/voucher_receivable_parent_loading_diag.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT, _ScaledPage  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402
from nbkit.omnisol.menu_schemas import VOUCHER_RECEIVABLE  # noqa: E402

from app.agents.voucher_receivable import steps  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

# 로딩/버지 계열 후보를 폭넓게 스캔(클래스명에 load/busy/spinner/mask 포함, 대소문자 무시).
LOADING_CANDIDATES_JS = r"""() => {
  const out = [];
  const els = document.querySelectorAll(
    '[class*="load" i], [class*="busy" i], [class*="spinner" i], [class*="mask" i]'
  );
  for (const el of els) {
    const cls = (el.className && el.className.toString) ? el.className.toString() : String(el.className || '');
    const r = el.getBoundingClientRect();
    const visible = el.offsetParent !== null && r.width > 0 && r.height > 0;
    out.push({ tag: el.tagName, cls, id: el.id, visible, w: Math.round(r.width), h: Math.round(r.height) });
  }
  return out;
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

        await steps.expand_condition_panel(page)
        await steps.set_dept_all(page)
        await steps.set_period_this_month(page)
        await steps.clear_writer(page)
        await steps.set_docu_status(page)
        await steps.set_gwaprvlst(page)
        await steps.set_docu_types(page)
        rq = await steps.run_query(page)
        print(f"[diag] run_query={rq}", flush=True)

        key0 = await steps.read_row_key(page, 0)
        await steps.uncheck_all_rows(page)
        await steps.check_row(page, 0)
        print(f"[diag] row0 key={key0} checked_row_indexes={await steps.checked_row_indexes(page)}", flush=True)

        child0 = await steps.open_approval(page)
        print(f"[diag] row0 open_approval -> {'Page' if child0 else None}", flush=True)
        if child0 is None:
            print("[FATAL] row0 자체가 안 열림 — 진단 조기 종료", flush=True)
            return
        await steps.poll_child_ready(child0)

        # ── 핵심 관찰 구간: close 직후부터 로딩류 요소를 시간축으로 스캔 ─────────────
        t_close = time.monotonic()
        await steps.close_child(child0)
        print(f"[diag] closed at t=0.00s — 이제 {8}s 동안 100ms 간격으로 로딩류 요소 스캔", flush=True)

        timeline: list[dict] = []
        for _ in range(80):  # 8s / 100ms
            t = round(time.monotonic() - t_close, 2)
            try:
                cands = await raw_page.evaluate(LOADING_CANDIDATES_JS)
            except Exception as exc:  # noqa: BLE001
                cands = [{"error": str(exc)}]
            visible = [c for c in cands if c.get("visible")]
            if visible:
                print(f"[diag] t={t}s visible-loading-elements: {visible}", flush=True)
            timeline.append({"t": t, "visible": visible})
            await raw_page.wait_for_timeout(100)

        # 결재 버튼 rect 도 같은 구간에서 함께 관찰(참고용 — 버튼 자체는 계속 유효했는지).
        from app.agents.voucher_receivable import js as vjs

        rect_after = await raw_page.evaluate(vjs.APPROVAL_BTN_RECT_JS)
        print(f"[diag] 8s 후 approval rect = {rect_after}", flush=True)

        (ARTIFACTS / "voucher_receivable_parent_loading_diag.json").write_text(
            json.dumps({"row0_key": key0, "timeline": timeline, "rect_after_8s": rect_after}, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"[artifact] {ARTIFACTS / 'voucher_receivable_parent_loading_diag.json'}", flush=True)
        await raw_page.screenshot(path=str(ARTIFACTS / "voucher_receivable_parent_loading_diag_final.png"), full_page=True)

        # 요약: 어떤 클래스가 어느 시간대에 visible=True 였는지.
        by_class: dict[str, list[float]] = {}
        for row in timeline:
            for c in row["visible"]:
                key = c.get("cls", "?")
                by_class.setdefault(key, []).append(row["t"])
        print("\n[diag] visible-window per class:", flush=True)
        for cls, times in by_class.items():
            print(f"  {cls!r}: first={min(times)}s last={max(times)}s count={len(times)}", flush=True)
        if not by_class:
            print("  (관찰 구간 동안 로딩류 요소 visible=True 인 것이 하나도 없었음)", flush=True)

    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
