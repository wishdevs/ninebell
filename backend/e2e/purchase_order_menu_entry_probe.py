"""HEADLESS 읽기전용(부작용 0) 프로브 — 구매발주 화면① 진입 + 필드 구조 실측 (❓2 확정, ❓5).

전 단계(`purchase_order_discover_probe.py`)가 사이드바 DOM 에서 확보한 실제 딥링크
(`/PU/PUOPRQ00200_X20616` 등, href 속성값 — 클릭 없이 확인됨)를 `navigator.navigate_menu`
로 실제 진입해 그리드 로드로 성공을 판정한다(OMNISOL_NOTES §6: URL 이 아니라 그리드 상태).

이어서 화면① 상단 필드(구매그룹/구매조직/통화/구매요청번호/이동요청번호/구매사유)와
체크박스(구매요청/이동요청) 초기 상태를 라벨 기반으로 전량 덤프한다(❓5). 클릭은 메뉴
진입(딥링크 goto)뿐 — 필드/체크박스는 읽기만 한다.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/purchase_order_menu_entry_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Page, async_playwright  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT, _ScaledPage  # noqa: E402
from nbkit.omnisol import js_lib  # noqa: E402
from nbkit.omnisol.errors import MenuError  # noqa: E402
from nbkit.omnisol.navigator import navigate_menu  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

# discover_probe 실측 href 그대로(❓2 확정 대상 — 클릭 없이 DOM 에서 확보됨).
DEEPLINK = "/PU/PUOPRQ00200_X20616"
MENU_LABEL = "프로젝트BOM구매요청[나인벨]"

# 라벨(<label>)이 속한 <li> 안의 입력요소 전량을 읽는다 — dews 폼 관례(FIELD_DISPLAY_JS 와
# 동일 구조: label.closest('li') 스코프). 코드피커/체크박스/select/text input 을 구분해 값을 낸다.
DUMP_FORM_FIELDS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const out = [];
  const labels = [...document.querySelectorAll('label')].filter(l => l.offsetParent !== null);
  for (const lbl of labels) {
    const text = c(lbl.innerText);
    if (!text) continue;
    const li = lbl.closest('li') || lbl.closest('div');
    if (!li) continue;
    const picker = li.querySelector('.dews-multicodepicker-text, .dews-codepicker-text');
    const pickerBtn = li.querySelector('.dews-codepicker-button, .dews-multicodepicker-button');
    const checkbox = li.querySelector('input[type=checkbox]');
    const select = li.querySelector('select');
    const textInput = li.querySelector('input[type=text], input:not([type])');
    out.push({
      label: text,
      hasPickerText: !!picker, pickerValue: picker ? picker.value : null,
      hasPickerBtn: !!pickerBtn,
      hasCheckbox: !!checkbox, checkboxChecked: checkbox ? checkbox.checked : null,
      hasSelect: !!select, selectValue: select ? (select.options[select.selectedIndex]||{}).text : null,
      hasTextInput: !!(textInput && textInput !== picker), textInputValue: (textInput && textInput !== picker) ? textInput.value : null,
    });
  }
  return out;
}"""

# 화면 상단 '적용' 버튼이 달린 필터 행(이동출고저장위치 등) — th/td 라벨 기반, li 구조가 아닐 수 있어 별도 스캔.
DUMP_FILTER_ROWS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const btns = [...document.querySelectorAll('button')].filter(b => b.offsetParent !== null && c(b.innerText) === '적용');
  return btns.map(b => {
    const row = b.closest('tr') || b.closest('li') || b.closest('div');
    const r = b.getBoundingClientRect();
    return { rowText: row ? c(row.innerText).slice(0, 150) : '', btnRect: { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2) } };
  });
}"""

GRID_INFO_JS = r"""() => {
  const grids = [...document.querySelectorAll('.dews-ui-grid')];
  return grids.map((g, i) => {
    try {
      const ctrl = window.jQuery(g).data('dewsControl')._grid;
      const cols = ctrl.getColumns().map(col => ({ fieldName: col.fieldName, header: col.header, visible: col.visible }));
      return { i, rowCount: ctrl.getDataSource().getRowCount(), columnCount: cols.length, columns: cols.slice(0, 50) };
    } catch (e) { return { i, error: String(e).slice(0, 80) }; }
  });
}"""


async def _dump(name: str, data) -> None:
    path = ARTIFACTS / f"purchase_order_menu_entry_{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[dump] {path}", flush=True)


async def _shot(page: Page, name: str) -> None:
    try:
        p = str(ARTIFACTS / f"purchase_order_menu_entry_{name}.png")
        await page.screenshot(path=p, full_page=True)
        print(f"[shot] {p}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[shot] skipped {name}: {exc!r}", flush=True)


async def main() -> None:
    results: dict = {"userid": USERID, "deeplink": DEEPLINK}
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=0)
    raw_page = await browser.new_page(viewport=LIVE_VIEWPORT)
    page = _ScaledPage(raw_page, DELAY_SCALE)
    base = get_settings().erp_base

    try:
        print("[entry] login + SCM 전환…", flush=True)
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await ensure_user_type(page, "SCM")

        print(f"[menu] 진입 시도: {DEEPLINK}", flush=True)
        try:
            await navigate_menu(page, DEEPLINK, base, label=MENU_LABEL, grids_required=1)
            results["menu_entry"] = {"ok": True}
            print("[menu] 진입 성공(그리드 로드 확인)", flush=True)
        except MenuError as exc:
            results["menu_entry"] = {"ok": False, "error": str(exc)}
            print(f"[menu] 진입 실패: {exc}", flush=True)
            await _shot(page, "99_menu_fail")
            await _dump("results", results)
            await browser.close()
            await pw.stop()
            return

        await page.wait_for_timeout(1_500)
        await _shot(page, "01_screen1_landing")

        grid_info = await page.evaluate(GRID_INFO_JS)
        results["grid_info"] = grid_info
        print(f"[grid] {len(grid_info)}개 그리드:", flush=True)
        for g in grid_info:
            if "error" in g:
                print(f"   [{g['i']}] error={g['error']}", flush=True)
            else:
                print(f"   [{g['i']}] rowCount={g['rowCount']} columnCount={g['columnCount']}", flush=True)

        fields = await page.evaluate(DUMP_FORM_FIELDS_JS)
        results["form_fields"] = fields
        print(f"[fields] {len(fields)}개 라벨 필드:", flush=True)
        for f in fields:
            print(f"   - {f}", flush=True)

        filter_rows = await page.evaluate(DUMP_FILTER_ROWS_JS)
        results["filter_rows"] = filter_rows
        print(f"[filter_rows] {len(filter_rows)}개 '적용' 버튼 행:", flush=True)
        for r in filter_rows:
            print(f"   - {r}", flush=True)

        await _dump("results", results)
        print("\n===== MENU ENTRY PROBE COMPLETE (읽기 전용) =====", flush=True)

    except Exception as exc:  # noqa: BLE001
        results["error"] = f"probe exception: {exc!r}"
        print(f"[ERROR] {results['error']}", flush=True)
        await _shot(raw_page, "exception")
        await _dump("results", results)
    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
