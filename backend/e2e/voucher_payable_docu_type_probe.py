"""읽기전용 초소형 프로브 — 전표조회승인(GLDDOC00700) 전표유형 MultiCodePicker(#s_docu_cd)
팝업에 외상매입금(voucher-payable) 후보값 '내구수매' 가 실제 존재하는지 확정한다.

voucher_receivable 의 e2e/voucher_receivable_docu_type_diag.py 를 그대로 재사용/약간 고침:
- expand_condition_panel 단독 대신 steps.ensure_field_visible(더 견고, optional-area 재접힘 방어).
- DOCU_NM 매칭 대신 실측 필드명 SYSDEF_CD/SYSDEF_NM 으로 '내구수매'/'국내매출'/'해외매출'/'일반' 매칭.

부작용 0 — 팝업을 열고 행 목록을 읽기만 하고 닫는다. 조회(F2)·결제·상신·저장·삭제 전부 하지 않는다.

Usage:
    cd backend && .venv/bin/python e2e/voucher_payable_docu_type_probe.py
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

TARGET_NAMES = ("내구수매", "국내매출", "해외매출", "일반")

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
  return { ok: true, n, cols, rows };
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

        # 전표유형 돋보기를 열기 직전 가시성 확보(optional-area 재접힘 방어) 후 픽커를 연다.
        visible = await steps.ensure_field_visible(page, steps.DOCU_TYPE_LABEL)
        print(f"[probe] 전표유형 필드 가시 = {visible}", flush=True)

        rect = await raw_page.evaluate(js.FIELD_SEARCH_BTN_RECT_JS, steps.DOCU_TYPE_LABEL)
        print(f"[probe] 전표유형 돋보기 rect = {rect}", flush=True)
        if not rect:
            print("[probe] FAIL: 돋보기 좌표를 찾지 못함 — 중단", flush=True)
            return
        await mouse_click(page, rect["x"], rect["y"])
        await page.wait_for_timeout(1_200)

        dump = await raw_page.evaluate(DUMP_POPUP_ALL_ROWS_JS)
        print(f"[probe] popup ok={dump.get('ok')} n={dump.get('n')}", flush=True)
        print(f"[probe] columns = {json.dumps(dump.get('cols'), ensure_ascii=False)}", flush=True)
        rows = dump.get("rows") or []

        matches = [r for r in rows if str(r.get("SYSDEF_NM", "")).strip() in TARGET_NAMES]
        print(f"[probe] SYSDEF_NM 매칭 행 ({', '.join(TARGET_NAMES)}):", flush=True)
        for r in sorted(matches, key=lambda r: str(r.get("SYSDEF_CD", ""))):
            print(f"  SYSDEF_CD={r.get('SYSDEF_CD')!r} SYSDEF_NM={r.get('SYSDEF_NM')!r} SYSDEF_NM2={r.get('SYSDEF_NM2')!r}", flush=True)

        has_naegu = any(str(r.get("SYSDEF_NM", "")).strip() == "내구수매" for r in rows)
        print(f"[probe] '내구수매' 존재 여부 = {has_naegu}", flush=True)

        await raw_page.screenshot(
            path=str(ARTIFACTS / "voucher_payable_docu_type_probe_popup.png"), full_page=True
        )
        (ARTIFACTS / "voucher_payable_docu_type_probe.json").write_text(
            json.dumps(dump, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(f"[artifact] {ARTIFACTS / 'voucher_payable_docu_type_probe.json'}", flush=True)
        print(f"[artifact] {ARTIFACTS / 'voucher_payable_docu_type_probe_popup.png'}", flush=True)

    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
