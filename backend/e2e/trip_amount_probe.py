"""공급가(거래금액) 컬럼 확정 + 자동계산 실측 — 출장(국내·자차)+증빙10 실 플로우(저장 없음).

사용자 정정: 금액은 '공급가액'(SPPRC_AMT)이 아니라 '공급가(거래금액)' 필드에 채워야 한다.
이 프로브는 detail 그리드 컬럼을 **헤더 라벨과 함께** 전수 덤프해 '거래금액' 필드 id 를 확정하고,
그 필드에 값 세팅 후 공급가액/부가세/합계(SPPRC_AMT/TOTAL_AMT 등)가 자동계산되는지 실측한다.
⚠ F7 금지. Usage: cd backend && .venv/bin/python e2e/trip_amount_probe.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright  # noqa: E402

from app.agents.common import doc_steps  # noqa: E402
from app.agents.trip_domestic import js as trip_js  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT  # noqa: E402 — 프로덕션 뷰포트
from nbkit.browser.actions import js_click  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.omnisol.menu_schemas import EXPENSE_CARD  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

import os  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
ART = Path(__file__).resolve().parent / "artifacts"

# grid[1] 컬럼 field↔header 전수 + 금액/거래금액 헤더 필터.
COLS_JS = """() => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
    const cols = (g.getColumns ? g.getColumns() : []).map(cc => ({
      field: cc.fieldName || cc.name || null,
      header: (cc.header && (cc.header.text || cc.header.caption)) || cc.caption || cc.title || cc.headerText || null,
    }));
    const amt = cols.filter(c => c.header && /금액|공급가|거래/.test(String(c.header)));
    return { ok: true, all: cols, amount_headers: amt };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 120) }; }
}"""

# 여러 금액 필드 raw 재독(자동계산 확인용).
_AMT_FIELDS = ["REALPAI_SPPRC_AMT2", "SPPRC_AMT", "SPPRC_AMT2", "TAXAMT_AMT", "TAXAMT_AMT2",
               "TOTAL_AMT", "ABDOCU_AMT", "TOT_ABDOCU_AMT", "REALPAI_VAT_AMT", "TIP_AMT"]
READ_AMTS_JS = """(fields) => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
    const n = g.getDataSource().getRowCount(); const row = Math.max(0, n-1);
    const out = {};
    for (const f of fields) { try { const v = g.getValue(row, f); out[f] = v==null?'':String(v); } catch(e){ out[f]='<err>'; } }
    // 마스터 합계.
    try { const m = window.jQuery(document.querySelectorAll('.dews-ui-grid')[0]).data('dewsControl')._grid;
      out['MASTER_DETAIL_SUM_AMT'] = String(m.getValue(0,'DETAIL_SUM_AMT')); } catch(e){}
    return out;
  } catch(e) { return { err: String(e).slice(0,100) }; }
}"""


async def main() -> None:
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page(viewport=LIVE_VIEWPORT)
    base = get_settings().erp_base
    try:
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await ensure_user_type(page, "회계")
        await navigate_schema(page, EXPENSE_CARD, base)
        for _ in range(20):
            if await page.evaluate("(s) => !!document.querySelector(s)", selectors.GUBUN_SELECT):
                break
            await page.wait_for_timeout(500)
        await page.evaluate(js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS, {"selector": selectors.GUBUN_SELECT, "text": "출장(국내·자차)"})
        await page.wait_for_timeout(1_800)
        await js_click(page, selectors.BTN_ADD)
        for _ in range(33):
            await page.wait_for_timeout(300)
            if (await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)) > 0:
                break
        await doc_steps.open_evdn_editor(page)
        await doc_steps.select_evdn_code(page, "10")

        cols = await page.evaluate(COLS_JS)
        print("[cols] 금액류 헤더↔필드:", flush=True)
        for c in cols.get("amount_headers") or []:
            print(f"    {c['field']:<22} = {c['header']}", flush=True)
        (ART / "trip_amount_cols.json").write_text(json.dumps(cols, ensure_ascii=False, indent=2), encoding="utf-8")

        # 거래금액 헤더 필드 확정(헤더에 '거래금액' 포함).
        txn = next((c["field"] for c in (cols.get("amount_headers") or []) if c.get("header") and "거래금액" in c["header"]), None)
        print(f"[txn] '거래금액' 필드 = {txn}", flush=True)

        before = await page.evaluate(READ_AMTS_JS, _AMT_FIELDS)
        print(f"[before] {before}", flush=True)
        if txn:
            r = await page.evaluate(trip_js.SET_DETAIL_CELL_JS, {"field": txn, "value": 15400})
            print(f"[set] {txn}=15400 -> ok={r.get('ok')} after={r.get('after')} disp={r.get('display')}", flush=True)
            await page.wait_for_timeout(1_500)
            after = await page.evaluate(READ_AMTS_JS, _AMT_FIELDS)
            print(f"[after] {after}", flush=True)
            # 자동계산 판정: SPPRC_AMT/TOTAL_AMT 가 before 대비 변했는지.
            changed = {k: (before.get(k), after.get(k)) for k in after if before.get(k) != after.get(k)}
            print(f"[auto-calc 변화] {changed}", flush=True)
        await page.screenshot(path=str(ART / "trip_amount_probe.png"), full_page=True)
        print("[done] 저장 없이 종료", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc!r}", flush=True)
        await page.screenshot(path=str(ART / "trip_amount_exc.png"))
    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
