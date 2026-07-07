"""상대계정거래처 실필드 탐색 — 문서 전역에서 '상대' 라벨/컬럼을 스캔(읽기전용, 저장 없음).

BFC_PARTNER 셀이 본 거래처로 폴백돼 상대계정 필드가 아님이 확정됨(trip_bfc_probe). 실제
상대계정거래처 입력 지점이 문서에 존재하는지 확정용. ⚠ F7 금지. Usage: .venv/bin/python e2e/trip_counter_scan.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright  # noqa: E402

from app.config import get_settings  # noqa: E402
from nbkit.browser.actions import js_click  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.omnisol.menu_schemas import EXPENSE_CARD  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

import os  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")

# 문서 전역에서 '상대' 포함 짧은 텍스트 요소 + 근처 input/picker id 스캔.
SCAN_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const labels = [];
  for (const el of document.querySelectorAll('label,th,span,div,td')) {
    if (el.offsetParent === null) continue;
    const t = c(el.innerText);
    if (t && t.length <= 12 && /상대/.test(t)) {
      const r = el.getBoundingClientRect();
      // 같은 행(top 근접) 오른쪽 input/picker.
      const near = [];
      for (const i of document.querySelectorAll('input[id], button.dews-codepicker-button, [id$=-wrapper]')) {
        if (i.offsetParent === null) continue;
        const ir = i.getBoundingClientRect();
        if (Math.abs(ir.top - r.top) < 24 && ir.left >= r.left - 4) {
          near.push(i.id || i.className.slice(0,40));
        }
      }
      labels.push({ text: t, near: near.slice(0, 5) });
    }
  }
  // detail 그리드(index 1) 컬럼 헤더 중 '상대' 포함.
  let cols = [];
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
    cols = (g.getColumns ? g.getColumns() : []).map(cc => ({
      field: cc.fieldName || cc.name,
      header: (cc.header && (cc.header.text || cc.header.caption)) || cc.caption || cc.title || null,
    })).filter(x => x.header && /상대/.test(String(x.header)));
  } catch (e) {}
  return { labels, counterCols: cols };
}"""


async def main() -> None:
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page(viewport=selectors.VIEWPORT)
    base = get_settings().erp_base
    try:
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
        scan = await page.evaluate(SCAN_JS)
        print("[scan] " + json.dumps(scan, ensure_ascii=False), flush=True)
        await page.screenshot(path=str(Path(__file__).resolve().parent / "artifacts" / "trip_counter_scan.png"), full_page=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc!r}", flush=True)
    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
