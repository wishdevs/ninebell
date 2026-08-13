"""HEADLESS 프로브 — '프로젝트 도움창' 선택→적용→메인화면 반영→조회(F2)→BOM 로드 검증.

team-lead 명시 승인(2026-08-13): 이 화면은 **조회 화면(문서 아님)** 이라 적용 클릭을 허용한다.
저장(F7)·결재·행 데이터 변경은 여전히 금지 — 이 프로브가 클릭하는 것은 프로젝트 선택 확정
('적용')과 조회(F2) 뿐이다(둘 다 조회조건 확정 동작, 데이터 생성 아님).

전 프로브(`purchase_order_zj90_search_probe.py`) 결론 반영:
  - ZJ90-130 은 실재 프로젝트로 확정(PJT_NO=2261, PJT_NM='ZJ90-130,  8CH BS PROCESS').
  - 같은 팝업 인스턴스에서 **검색을 2회 이상** 하면 간헐적으로 팝업이 소멸한다(원인 미확정,
    재현 비결정적 — 재오픈해도 재현된 사례 있음). **완화책**: 팝업당 검색은 항상 **1회만** 하고,
    검색 직후 결과 미확보(팝업 소멸 포함)면 **재오픈 후 재시도**(상한 2회)한다. 이 프로브는 그
    완화책을 그대로 구현한다.

사이클: CX85-137(기존 값과 동일 — 무해) → ZJ90-130(신규 선택 — 화면 필터 변경, 비가역 아님:
조회조건일 뿐 저장 안 함).

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/purchase_order_project_apply_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Page, async_playwright  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT, _ScaledPage  # noqa: E402
from nbkit.omnisol import js_lib  # noqa: E402
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

WIN_STATE_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  return wins.map(w => ({ title: c((w.querySelector('.k-window-title')||{}).innerText) }));
}"""

SET_KEYWORD_JS = r"""(q) => {
  const i = document.querySelector('#keyword');
  if (!i) return false;
  const s = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(i), 'value').set;
  s.call(i, q); i.dispatchEvent(new Event('input', { bubbles: true })); i.focus();
  return true;
}"""

READ_POPUP_GRID_JS = r"""() => {
  const wins = [...document.querySelectorAll('.k-window')].filter(d => d.offsetParent !== null);
  const dlg = wins[wins.length - 1];
  if (!dlg) return { ok: false, reason: 'no-window' };
  const gridEl = dlg.querySelector('.dews-ui-grid');
  if (!gridEl) return { ok: false, reason: 'no-grid' };
  try {
    const g = window.jQuery(gridEl).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const rows = n > 0 ? ds.getJsonRows(0, Math.min(n, 10) - 1) : [];
    return { ok: true, rowCount: n, rows: rows.map(r => ({ PJT_NO: r.PJT_NO, PJT_NM: r.PJT_NM })) };
  } catch (e) { return { ok: false, err: String(e).slice(0, 100) }; }
}"""

SELECT_ROW_JS = r"""(pjtNo) => {
  const wins = [...document.querySelectorAll('.k-window')].filter(d => d.offsetParent !== null);
  const dlg = wins[wins.length - 1];
  if (!dlg) return { ok: false, reason: 'no-window' };
  try {
    const g = window.jQuery(dlg.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const rows = ds.getJsonRows(0, ds.getRowCount() - 1);
    const i = rows.findIndex(r => String(r.PJT_NO) === String(pjtNo));
    if (i < 0) return { ok: false, reason: 'not-found', have: rows.map(r => r.PJT_NO) };
    g.setCurrent({ itemIndex: i, fieldName: 'PJT_NM' });
    g.setSelection({ startRow: i, endRow: i, startColumn: 0, endColumn: 0 });
    return { ok: true, name: rows[i].PJT_NM };
  } catch (e) { return { ok: false, err: String(e).slice(0, 100) }; }
}"""

APPLY_BTN_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window')].filter(d => d.offsetParent !== null);
  const dlg = wins[wins.length - 1];
  if (!dlg) return null;
  const btn = [...dlg.querySelectorAll('button')].find(b => b.offsetParent !== null && c(b.innerText) === '적용');
  if (!btn) return null;
  const r = btn.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

LOOKUP_BTN_JS = r"""() => {
  const b = document.querySelector('button.main-button.lookup');
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

TREEGRID_SAMPLE_JS = r"""(n) => {
  try {
    const el = document.querySelector('.dews-ui-treegrid');
    const g = window.jQuery(el).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const count = ds.getRowCount();
    const fields = ['ITEM_CD', 'ITEM_NM', 'WBS_NM'];
    const out = [];
    const levelCounts = {};
    for (let i = 0; i < count; i++) {
      let level = null;
      try { level = ds.getLevel(i); } catch (e) { level = -1; }
      levelCounts[level] = (levelCounts[level] || 0) + 1;
      if (i < n) {
        const row = { i, level };
        for (const f of fields) { try { row[f] = g.getValue(i, f); } catch (e) { row[f] = 'ERR'; } }
        out.push(row);
      }
    }
    return { count, levelCounts, sample: out };
  } catch (e) { return { err: String(e).slice(0, 200) }; }
}"""


async def _shot(page: Page, name: str) -> None:
    try:
        p = str(ARTIFACTS / f"purchase_order_apply_{name}.png")
        await page.screenshot(path=p, full_page=True)
        print(f"[shot] {p}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[shot] skipped {name}: {exc!r}", flush=True)


async def _dump(name: str, data) -> None:
    path = ARTIFACTS / f"purchase_order_apply_{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[dump] {path}", flush=True)


async def _open_and_search_once(page: Page, box: dict, keyword: str, *, retries: int = 2) -> dict:
    """팝업당 검색 1회 완화책 — 검색 후 결과 미확보(팝업 소멸 포함)면 재오픈 재시도(상한 retries)."""
    for attempt in range(1, retries + 1):
        await page.mouse.click(box["x"], box["y"])
        await page.wait_for_timeout(1_000)
        win_before = await page.evaluate(WIN_STATE_JS)
        if not win_before:
            continue  # 오픈 자체 실패 — 재시도
        await page.evaluate(SET_KEYWORD_JS, keyword)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(1_500)
        win_after = await page.evaluate(WIN_STATE_JS)
        if win_after:
            grid = await page.evaluate(READ_POPUP_GRID_JS)
            return {"ok": True, "attempt": attempt, "grid": grid}
        print(f"[search] '{keyword}' attempt {attempt} — 팝업 소멸, 재오픈 재시도", flush=True)
    return {"ok": False, "attempt": retries, "reason": "팝업이 검색 후 계속 소멸(재시도 상한 도달)"}


async def _apply_project(page: Page, box: dict, keyword: str, pjt_no: str) -> dict:
    result: dict = {"keyword": keyword, "pjt_no": pjt_no}
    search = await _open_and_search_once(page, box, keyword)
    result["search"] = search
    if not search.get("ok"):
        return result
    await _shot(page, f"01_{pjt_no}_searched")

    sel = await page.evaluate(SELECT_ROW_JS, pjt_no)
    result["select"] = sel
    if not sel.get("ok"):
        return result

    apply_box = await page.evaluate(APPLY_BTN_JS)
    result["apply_box"] = apply_box
    if not apply_box:
        return result
    await page.mouse.click(apply_box["x"], apply_box["y"])

    # 팝업 닫힘 폴링(적용 후 정상 종료 확인).
    t0 = time.monotonic()
    closed = False
    while (time.monotonic() - t0) < 3.0:
        wins = await page.evaluate(WIN_STATE_JS)
        if not wins:
            closed = True
            break
        await page.wait_for_timeout(150)
    result["popup_closed_after_apply"] = closed
    await _shot(page, f"02_{pjt_no}_after_apply")

    field_val = await page.evaluate(js_lib.FIELD_DISPLAY_JS, "프로젝트")
    result["main_field_value"] = field_val

    lookup_box = await page.evaluate(LOOKUP_BTN_JS)
    if lookup_box:
        await page.mouse.click(lookup_box["x"], lookup_box["y"])
        await page.wait_for_timeout(2_500)
    await _shot(page, f"03_{pjt_no}_after_lookup")

    bom = await page.evaluate(TREEGRID_SAMPLE_JS, 8)
    result["bom_after_query"] = bom
    return result


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
        await navigate_menu(page, DEEPLINK, base, label="test", grids_required=1)
        await page.wait_for_timeout(1_500)

        box = await page.evaluate(js_lib.PROJECT_PICKER_BOX_JS)
        results["picker_box"] = box
        if not box:
            results["error"] = "프로젝트 피커 버튼 미발견"
            await _dump("results", results)
            return

        print("[cycle] CX85-137(2297) — 기존 값과 동일, 무해 확인 사이클", flush=True)
        r_cx85 = await _apply_project(page, box, "CX85-137", "2297")
        results["cx85"] = r_cx85
        print(f"[cx85] search_ok={r_cx85['search'].get('ok')} select={r_cx85.get('select')} "
              f"popup_closed={r_cx85.get('popup_closed_after_apply')} field={r_cx85.get('main_field_value')} "
              f"bom_levelCounts={(r_cx85.get('bom_after_query') or {}).get('levelCounts')}", flush=True)

        print("[cycle] ZJ90-130(2261) — 신규 선택 사이클", flush=True)
        r_zj90 = await _apply_project(page, box, "ZJ90-130", "2261")
        results["zj90"] = r_zj90
        print(f"[zj90] search_ok={r_zj90['search'].get('ok')} select={r_zj90.get('select')} "
              f"popup_closed={r_zj90.get('popup_closed_after_apply')} field={r_zj90.get('main_field_value')} "
              f"bom_levelCounts={(r_zj90.get('bom_after_query') or {}).get('levelCounts')}", flush=True)

        await _dump("results", results)
        print("\n===== PROJECT APPLY + BOM LOAD VERIFICATION COMPLETE =====", flush=True)

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
