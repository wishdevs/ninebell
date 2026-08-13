"""HEADLESS 읽기전용 프로브 — 구매발주 화면① BOM 그리드 실체 + 프로젝트 검색 UI (❓3·❓4).

⚠ 읽기 전용 규율(미션 지시): 저장(F7)·적용(모든 코드피커의 '적용' 버튼)·결재·행 데이터 변경
금지. **조회(F2)** 와 **패널 열기 + 검색** 까지만 허용. 이 프로브는:
  1. `.dews-ui-grid` 전량의 rect/visible 을 덤프해 "화면에 보이는 BOM 그리드"가 어느 인덱스인지
     확정한다(전 단계 `purchase_order_menu_entry_probe.py` 에서 잡힌 2개 그리드의 fieldName이
     화면상 컬럼(No/레벨순번/품목코드…)과 달라 진짜 그리드를 못 잡았을 가능성 — 원인분류: 셀렉터
     드리프트 후보).
  2. 조회(F2/lookup 버튼) 클릭 → 그리드 재덤프(❓4: 레벨/필드명/행수).
  3. '프로젝트' 코드피커를 열어 'ZJ90' 검색 → 결과 덤프 → **적용 클릭 없이** 닫기(❓3).
     기존 `js_lib.PROJECT_PICKER_BOX_JS`/`PROJECT_POPUP_OPEN_JS`/`PROJECT_SEARCH_SET_JS`/
     `PROJECT_READ_JS` 를 그대로 재사용(expense_card 에서 이미 검증된 프리미티브 — 이 화면에서도
     통하는지 실측).

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/purchase_order_bom_grid_probe.py
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

DEEPLINK = "/PU/PUOPRQ00200_X20616"
MENU_LABEL = "프로젝트BOM구매요청[나인벨]"

# 모든 .dews-ui-grid rect/visible — "화면에 보이는 것이 어느 인덱스인가" 진단.
ALL_GRIDS_RECT_JS = r"""() => {
  const grids = [...document.querySelectorAll('.dews-ui-grid')];
  return grids.map((g, i) => {
    const r = g.getBoundingClientRect();
    let rowCount = null, colCount = null, fields = [];
    try {
      const ctrl = window.jQuery(g).data('dewsControl')._grid;
      rowCount = ctrl.getDataSource().getRowCount();
      const cols = ctrl.getColumns();
      colCount = cols.length;
      fields = cols.map(c => c.fieldName);
    } catch (e) {}
    return {
      i, visible: g.offsetParent !== null,
      rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
      rowCount, colCount, fields,
    };
  });
}"""

# 조회(F2) 버튼 좌표 — selectors.BTN_LOOKUP 존재 확인 겸 좌표 확보(클릭은 read-only 허용).
LOOKUP_BTN_JS = r"""() => {
  const b = document.querySelector('button.main-button.lookup');
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2), visible: b.offsetParent !== null };
}"""


async def _dump(name: str, data) -> None:
    path = ARTIFACTS / f"purchase_order_bom_grid_{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[dump] {path}", flush=True)


async def _shot(page: Page, name: str) -> None:
    try:
        p = str(ARTIFACTS / f"purchase_order_bom_grid_{name}.png")
        await page.screenshot(path=p, full_page=True)
        print(f"[shot] {p}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[shot] skipped {name}: {exc!r}", flush=True)


async def main() -> None:
    results: dict = {"userid": USERID}
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=0)
    raw_page = await browser.new_page(viewport=LIVE_VIEWPORT)
    page = _ScaledPage(raw_page, DELAY_SCALE)
    base = get_settings().erp_base

    try:
        print("[entry] login + SCM 전환 + 메뉴 진입…", flush=True)
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await ensure_user_type(page, "SCM")
        try:
            await navigate_menu(page, DEEPLINK, base, label=MENU_LABEL, grids_required=1)
        except MenuError as exc:
            results["menu_entry_error"] = str(exc)
            await _dump("results", results)
            await browser.close()
            await pw.stop()
            return
        await page.wait_for_timeout(1_500)

        # ── 1) 그리드 전량 rect/visible 진단(가설: 화면상 BOM 그리드는 다른 인덱스) ──
        grids_before = await page.evaluate(ALL_GRIDS_RECT_JS)
        results["grids_before_query"] = grids_before
        print(f"[diag] 조회 전 그리드 {len(grids_before)}개:", flush=True)
        for g in grids_before:
            print(f"   [{g['i']}] visible={g['visible']} rect={g['rect']} rowCount={g['rowCount']} "
                  f"colCount={g['colCount']} fields={g['fields'][:6]}...", flush=True)
        await _shot(page, "00_before_query")

        # ── 2) 조회(F2) 클릭 — read-only 허용 동작 ──
        lookup_box = await page.evaluate(LOOKUP_BTN_JS)
        results["lookup_btn"] = lookup_box
        print(f"[lookup] 버튼 좌표: {lookup_box}", flush=True)
        if lookup_box:
            await page.mouse.click(lookup_box["x"], lookup_box["y"])
            await page.wait_for_timeout(2_500)  # 서버 왕복(조건폴링 대신 관찰 — 실측 목적 단발)
        else:
            # 폴백: F2 키.
            await page.keyboard.press("F2")
            await page.wait_for_timeout(2_500)
            print("[lookup] 버튼 미발견 — F2 키 폴백", flush=True)
        await _shot(page, "01_after_query")

        grids_after = await page.evaluate(ALL_GRIDS_RECT_JS)
        results["grids_after_query"] = grids_after
        print(f"[diag] 조회 후 그리드 {len(grids_after)}개:", flush=True)
        for g in grids_after:
            print(f"   [{g['i']}] visible={g['visible']} rect={g['rect']} rowCount={g['rowCount']} "
                  f"colCount={g['colCount']} fields={g['fields']}", flush=True)

        # ── 3) 프로젝트 코드피커 — 검색까지만, 적용 클릭 금지 ──
        box = await page.evaluate(js_lib.PROJECT_PICKER_BOX_JS)
        results["project_picker_box"] = box
        print(f"[project] 피커 버튼 좌표: {box}", flush=True)
        if box:
            await page.mouse.click(box["x"], box["y"])
            await page.wait_for_timeout(1_200)
            opened = await page.evaluate(js_lib.PROJECT_POPUP_OPEN_JS)
            results["project_popup_opened"] = opened
            print(f"[project] 팝업 열림={opened}", flush=True)
            await _shot(page, "02_project_picker_open")

            for kw in ["ZJ90", "CX85"]:
                set_ok = await page.evaluate(js_lib.PROJECT_SEARCH_SET_JS, kw)
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(1_500)
                read = await page.evaluate(js_lib.PROJECT_READ_JS, 15)
                results[f"project_search_{kw}"] = {"set_ok": set_ok, "read": read}
                print(f"[project] 검색 '{kw}' set_ok={set_ok} → {read}", flush=True)
                await _shot(page, f"03_project_search_{kw}")

            # 적용 클릭 없이 닫기(ESC — 팝업 닫힘, 폼 미반영 보장).
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(800)
            still_open = await page.evaluate(js_lib.PROJECT_POPUP_OPEN_JS)
            results["project_popup_closed_via_escape"] = not still_open
            print(f"[project] ESC 후 팝업 닫힘={not still_open}", flush=True)
            await _shot(page, "04_after_escape")
        else:
            print("[project] 피커 버튼 미발견", flush=True)

        await _dump("results", results)
        print("\n===== BOM GRID + PROJECT SEARCH PROBE COMPLETE (적용 클릭 0회) =====", flush=True)

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
