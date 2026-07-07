"""HEADLESS 읽기전용 프로브 3차 — 셀 피커 검색 트리거(Enter) + 예산 조합행/거래처 매칭 확정.

2차 결론: 거래처(customTextBox)·예산단위(keyword) 셀 피커는 값 세팅만으론 필터 안 됨 →
card `_picker_search` 처럼 **Enter** 로 서버 재조회해야 한다. 이 프로브는 Enter 트리거로
P5(본인 단건 매칭)·P6(여비교통비-국내출장 조합행) 을 확정한다.

⚠ F7 저장 절대 금지. 검색/읽기/닫기만. Usage: cd backend && .venv/bin/python e2e/trip_probe3.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import Page, async_playwright  # noqa: E402

from app.config import get_settings  # noqa: E402
from nbkit.browser.actions import js_click, mouse_click  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.omnisol.menu_schemas import EXPENSE_CARD  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

import os  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

OPEN_CELL_JS = """(fieldName) => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
    const n = g.getDataSource().getRowCount();
    const idx = Math.max(0, n - 1);
    g.setCurrent({ itemIndex: idx, fieldName });
    g.showEditor();
    return { ok: true, idx, rows: n };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 120) }; }
}"""

CELL_MAGNIFIER_JS = """() => {
  const inp = [...document.querySelectorAll('input')].find(i =>
    /gridDetail_line|gridDetail|_editor/.test(i.id || '') && i.offsetParent !== null);
  if (!inp) return null;
  const r = inp.getBoundingClientRect();
  return { x: r.right + 8, y: r.top + r.height / 2, id: inp.id };
}"""

# 검색창에 값 세팅 + 포커스(Enter 는 page.keyboard 로 별도 발화).
POPUP_SEARCH_FOCUS_JS = """(q) => {
  const p = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null).slice(-1)[0];
  if (!p) return { ok: false, reason: 'no-popup' };
  const kw = p.querySelector('#keyword') || p.querySelector('#s_search_key')
    || p.querySelector('#customTextBox') || p.querySelector('[id$=search_key]')
    || p.querySelector('[id*=keyword]') || p.querySelector('[id*=customText]')
    || [...p.querySelectorAll('input')].filter(i => i.offsetParent!==null && (i.type==='text'||!i.type))[0];
  if (!kw) return { ok: false, reason: 'no-keyword' };
  const d = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value'); d.set.call(kw, q);
  ['input','change'].forEach(t => kw.dispatchEvent(new Event(t, { bubbles: true })));
  kw.focus();
  return { ok: true, field: kw.id || '(no-id)' };
}"""

# 마지막 팝업 그리드 전체행 덤프(필드 지정).
POPUP_DUMP_JS = """([fields, limit]) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const p = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null).slice(-1)[0];
  if (!p) return { ok: false, reason: 'no-popup' };
  const title = c((p.querySelector('.k-window-title')||{}).innerText);
  try {
    const g = window.jQuery(p.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const ds = g.getDataSource(); const n = ds.getRowCount();
    const take = Math.min(n, limit || 60);
    const rows = take > 0 ? ds.getJsonRows(0, take - 1) : [];
    const out = rows.map(r => { const o = {}; for (const f of fields) o[f] = r[f]==null?null:String(r[f]); return o; });
    return { ok: true, title, n, rows: out };
  } catch (e) { return { ok: false, title, reason: String(e).slice(0, 120) }; }
}"""

ANY_POPUP_OPEN_JS = "() => [...document.querySelectorAll('.k-window')].some(w => w.offsetParent !== null)"


async def _shot(page: Page, name: str) -> None:
    try:
        await page.screenshot(path=str(ARTIFACTS / f"trip_probe3_{name}.png"))
    except Exception:  # noqa: BLE001
        pass


async def _open_cell_and_picker(page: Page, field: str) -> bool:
    op = await page.evaluate(OPEN_CELL_JS, field)
    if not op.get("ok"):
        return False
    mag = None
    waited = 0
    while waited < 1_500:
        await page.wait_for_timeout(150)
        waited += 150
        mag = await page.evaluate(CELL_MAGNIFIER_JS)
        if mag:
            break
    if not mag:
        return False
    await mouse_click(page, mag["x"], mag["y"])
    for _ in range(20):
        await page.wait_for_timeout(300)
        if await page.evaluate(ANY_POPUP_OPEN_JS):
            return True
    return False


async def _search_enter(page: Page, q: str) -> dict:
    s = await page.evaluate(POPUP_SEARCH_FOCUS_JS, q)
    if s.get("ok"):
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(1_800)
    return s


async def main() -> None:
    results: dict = {"userid": USERID}
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS)
    page = await browser.new_page(viewport=selectors.VIEWPORT)
    base = get_settings().erp_base
    try:
        print("[entry] login/회계/GLDDOC00300…", flush=True)
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

        # ── P5: 거래처 본인이름 + 공공기관 검색(Enter 트리거) ───────────────────
        print("\n===== P5: 거래처 검색(Enter) =====", flush=True)
        pf = ["PARTNER_CD", "PARTNER_NM", "PARTNER_FG_NM", "BIZR_NO"]
        if await _open_cell_and_picker(page, "PARTNER_NM"):
            for q in (USERID, "한국도로공사", "도로공사"):
                s = await _search_enter(page, q)
                dump = await page.evaluate(POPUP_DUMP_JS, [pf, 20])
                results.setdefault("P5_partner", {})[q] = {"search": s, "n": dump.get("n"), "rows": dump.get("rows")}
                exact = [r for r in (dump.get("rows") or []) if (r.get("PARTNER_NM") or "").strip() == q]
                print(f"[P5] '{q}' searchField={s.get('field')} n={dump.get('n')} exact={len(exact)} first={(dump.get('rows') or [{}])[0].get('PARTNER_NM')}", flush=True)
                await _shot(page, f"p5_{q}")
            await page.evaluate(js_lib.PICKER_CLOSE_JS)
            await page.wait_for_timeout(600)
        else:
            results["P5_partner"] = {"error": "거래처 셀 피커 열기 실패"}

        # ── P6: 예산단위 조합행(Enter 트리거) ────────────────────────────────────
        print("\n===== P6: 예산단위 검색(Enter) =====", flush=True)
        bf = ["BG_CD", "BG_NM", "BIZPLAN_CD", "BIZPLAN_NM", "BGACCT_CD", "BGACCT_NM"]
        if await _open_cell_and_picker(page, "BG_NM"):
            for q in ("여비교통비", "국내출장", "여비"):
                s = await _search_enter(page, q)
                dump = await page.evaluate(POPUP_DUMP_JS, [bf, 60])
                rows = dump.get("rows") or []
                results.setdefault("P6_budget", {})[q] = {"search": s, "n": dump.get("n"), "rows": rows}
                print(f"[P6] '{q}' searchField={s.get('field')} n={dump.get('n')}", flush=True)
                for r in rows[:12]:
                    print(f"     BG={r.get('BG_NM')} | BIZPLAN={r.get('BIZPLAN_NM')} | BGACCT={r.get('BGACCT_NM')}", flush=True)
                await _shot(page, f"p6_{q}")
            await page.evaluate(js_lib.PICKER_CLOSE_JS)
            await page.wait_for_timeout(600)
        else:
            results["P6_budget"] = {"error": "예산단위 셀 피커 열기 실패"}

        (ARTIFACTS / "trip_probe3_results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print("\n[dump] trip_probe3_results.json", flush=True)
        print("===== PROBE3 COMPLETE (저장 없이 종료) =====", flush=True)
    except Exception as exc:  # noqa: BLE001
        results["error"] = f"probe3 exception: {exc!r}"
        print(f"[ERROR] {results['error']}", flush=True)
        await _shot(page, "exception")
        (ARTIFACTS / "trip_probe3_results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
