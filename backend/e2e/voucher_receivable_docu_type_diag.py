"""읽기전용 진단 — 전표유형 MultiCodePicker 팝업의 실제 getJsonRows 필드명/값을 덤프한다.

목적: set_docu_types 가 field='DOCU_NM' 매칭 idxs=[] (n=62 는 정확)로 실패하는 근본 원인 확인.
부작용 0 — 팝업을 열고 데이터를 읽기만 하고 아무것도 체크/적용하지 않는다.

Usage:
    cd backend && .venv/bin/python e2e/voucher_receivable_docu_type_diag.py
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

from app.agents.voucher_receivable import js  # noqa: E402
from app.agents.voucher_receivable import steps  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

# 팝업 전체 행을 field 상관없이 원본 JSON으로 덤프(읽기전용).
DUMP_POPUP_ALL_ROWS_JS = r"""() => {
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const dlg = wins[wins.length - 1];
  if (!dlg) return { ok: false, reason: 'no-popup' };
  const g = window.jQuery(dlg.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
  const cols = g.getColumns().map(c => ({ field: c.fieldName, header: (c.header && c.header.text) || c.name }));
  const ds = g.getDataSource();
  const n = ds.getRowCount();
  const rows = n > 0 ? ds.getJsonRows(0, n - 1) : [];
  const disp = n > 0 ? g.getDisplayValuesOfRow(3) : null;  // idx3 = 국내매출 이어야 함(실측 idx).
  return { ok: true, n, cols, rows, display_row3: disp };
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

        # 전표유형 팝업까지 최단 경로로 도달(패널 확장 → 돋보기 클릭). 다른 필드는 건드리지 않는다.
        await steps.expand_condition_panel(page)
        rect = await raw_page.evaluate(js.FIELD_SEARCH_BTN_RECT_JS, steps.DOCU_TYPE_LABEL)
        print(f"[diag] 전표유형 돋보기 rect = {rect}", flush=True)
        await mouse_click(page, rect["x"], rect["y"])
        await page.wait_for_timeout(1_200)

        dump = await raw_page.evaluate(DUMP_POPUP_ALL_ROWS_JS)
        print(f"[diag] popup ok={dump.get('ok')} n={dump.get('n')}", flush=True)
        print(f"[diag] columns = {json.dumps(dump.get('cols'), ensure_ascii=False)}", flush=True)
        rows = dump.get("rows") or []
        print(f"[diag] rows[0..5] = {json.dumps(rows[:6], ensure_ascii=False, indent=2)}", flush=True)
        print(f"[diag] display_row3(getDisplayValuesOfRow) = {dump.get('display_row3')}", flush=True)

        # DOCU_NM 필드 존재 여부 + 값 스캔.
        has_docu_nm = bool(rows) and "DOCU_NM" in rows[0]
        print(f"[diag] rows[0] has 'DOCU_NM' key = {has_docu_nm}", flush=True)
        matches = [r for r in rows if str(r.get("DOCU_NM", "")).strip() in ("국내매출", "해외매출")]
        print(f"[diag] DOCU_NM 필드로 '국내매출'/'해외매출' 매칭된 행 수 = {len(matches)}", flush=True)

        await raw_page.screenshot(
            path=str(ARTIFACTS / "voucher_receivable_docu_type_diag_popup.png"), full_page=True
        )
        (ARTIFACTS / "voucher_receivable_docu_type_diag.json").write_text(
            json.dumps(dump, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(f"[artifact] {ARTIFACTS / 'voucher_receivable_docu_type_diag.json'}", flush=True)
        print(f"[artifact] {ARTIFACTS / 'voucher_receivable_docu_type_diag_popup.png'}", flush=True)

    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
