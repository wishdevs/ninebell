"""HEADLESS 읽기전용 프로브 2차 — detail 그리드 셀 코드피커(showEditor+돋보기) 확정.

1차(trip_probe.py) 결론: 출장(국내·자차)의 거래처/예산단위/프로젝트/상대계정거래처는 문서 폼
코드피커가 아니라 **detail RealGrid 셀**이다(공급가액 SPPRC_AMT·적요 NOTE_DC 는 setValue 직접
동작 확인). 이 프로브는 각 코드 셀을 showEditor 로 열고 돋보기를 클릭해 피커 팝업 구조를 덤프한다.

⚠ F7 저장 절대 금지. 피커 열기/검색/읽기/닫기만(미영속). 저장류 모달 '예' 금지.
Usage: cd backend && .venv/bin/python e2e/trip_probe2.py
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

# detail 그리드(index 1) 마지막 행의 fieldName 셀 에디터 오픈(showEditor).
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

# 현재 뜬 detail 그리드 에디터 input 의 돋보기 좌표(input 오른쪽 +8px) + input 메타.
CELL_MAGNIFIER_JS = """() => {
  const inp = [...document.querySelectorAll('input')].find(i =>
    /gridDetail_line|gridDetail|_editor/.test(i.id || '') && i.offsetParent !== null);
  if (!inp) {
    // 폴백: 그리드[1] 영역 위에 떠 있는 보이는 input.
    const g = document.querySelectorAll('.dews-ui-grid')[1];
    const gr = g ? g.getBoundingClientRect() : null;
    const cand = [...document.querySelectorAll('input')].find(i => {
      if (i.offsetParent === null || !gr) return false;
      const r = i.getBoundingClientRect();
      return r.top >= gr.top - 5 && r.top <= gr.bottom + 40 && r.width > 20;
    });
    if (!cand) return null;
    const r = cand.getBoundingClientRect();
    return { x: r.right + 8, y: r.top + r.height / 2, id: cand.id || '(no-id)', via: 'fallback' };
  }
  const r = inp.getBoundingClientRect();
  return { x: r.right + 8, y: r.top + r.height / 2, id: inp.id, via: 'gridDetail' };
}"""

# 마지막 열린 k-window(피커) 그리드 덤프 + 검색창 id.
LAST_POPUP_GRID_JS = """(limit) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const p = wins[wins.length - 1];
  if (!p) return { ok: false, reason: 'no-popup' };
  const title = c((p.querySelector('.k-window-title')||{}).innerText);
  try {
    const g = window.jQuery(p.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const cols = (g.getColumns ? g.getColumns() : []).map(cc => cc.fieldName || cc.name).filter(Boolean);
    const take = Math.min(n, limit || 5);
    const sampleRows = take > 0 ? ds.getJsonRows(0, take - 1) : [];
    const kwEl = p.querySelector('#keyword') || p.querySelector('#s_search_key')
      || p.querySelector('[id$=search_key]') || p.querySelector('[id*=keyword]')
      || [...p.querySelectorAll('input')].filter(i => i.offsetParent!==null && (i.type==='text'||!i.type))[0];
    return { ok: true, title, n, cols, searchId: kwEl ? (kwEl.id || '(no-id)') : null, sampleRows };
  } catch (e) { return { ok: false, title, reason: String(e).slice(0, 140) }; }
}"""

POPUP_SEARCH_JS = """(q) => {
  const p = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null).slice(-1)[0];
  if (!p) return { ok: false, reason: 'no-popup' };
  const kw = p.querySelector('#keyword') || p.querySelector('#s_search_key')
    || p.querySelector('[id$=search_key]') || p.querySelector('[id*=keyword]')
    || [...p.querySelectorAll('input')].filter(i => i.offsetParent!==null && (i.type==='text'||!i.type))[0];
  if (!kw) return { ok: false, reason: 'no-keyword' };
  const d = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value'); d.set.call(kw, q);
  ['input','change'].forEach(t => kw.dispatchEvent(new Event(t, { bubbles: true })));
  return { ok: true, field: kw.id || '(no-id)' };
}"""

ANY_POPUP_OPEN_JS = "() => [...document.querySelectorAll('.k-window')].some(w => w.offsetParent !== null)"


async def _dump(name: str, data) -> None:
    (ARTIFACTS / f"trip_probe2_{name}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"[dump] trip_probe2_{name}.json", flush=True)


async def _shot(page: Page, name: str) -> None:
    try:
        await page.screenshot(path=str(ARTIFACTS / f"trip_probe2_{name}.png"))
    except Exception:  # noqa: BLE001
        pass


async def _open_cell_picker(page: Page, field: str, label: str) -> dict:
    """detail 셀 field 를 열고 돋보기 클릭 → 피커 팝업이 뜨는지 판정. 반환 진단 dict."""
    diag: dict = {"field": field, "label": label}
    op = await page.evaluate(OPEN_CELL_JS, field)
    diag["open"] = op
    if not op.get("ok"):
        return diag
    mag = None
    waited = 0
    while waited < 1_500:
        await page.wait_for_timeout(150)
        waited += 150
        mag = await page.evaluate(CELL_MAGNIFIER_JS)
        if mag:
            break
    diag["magnifier"] = mag
    if not mag:
        diag["reason"] = "에디터 input/돋보기 좌표 못 찾음"
        return diag
    await mouse_click(page, mag["x"], mag["y"])
    opened = False
    for _ in range(20):
        await page.wait_for_timeout(300)
        if await page.evaluate(ANY_POPUP_OPEN_JS):
            opened = True
            break
    diag["popup_opened"] = opened
    return diag


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
        # 결의구분 = 출장(국내·자차)
        await page.evaluate(
            js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS,
            {"selector": selectors.GUBUN_SELECT, "text": "출장(국내·자차)"},
        )
        await page.wait_for_timeout(1_800)
        # F3 행추가
        await js_click(page, selectors.BTN_ADD)
        for _ in range(33):
            await page.wait_for_timeout(300)
            if (await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)) > 0:
                break
        await _shot(page, "ready")

        # ── 거래처(PARTNER) 셀 피커 (P4/P5) ──────────────────────────────────────
        print("\n===== 거래처 PARTNER 셀 피커 =====", flush=True)
        for fld in ("PARTNER_NM", "PARTNER_CD"):
            d = await _open_cell_picker(page, fld, "거래처")
            print(f"[partner] field={fld} open={d.get('open',{}).get('ok')} mag={bool(d.get('magnifier'))} popup={d.get('popup_opened')}", flush=True)
            if d.get("popup_opened"):
                await page.wait_for_timeout(600)
                d["empty_search"] = await page.evaluate(LAST_POPUP_GRID_JS, 5)
                print(f"[partner] popup title={d['empty_search'].get('title')} n={d['empty_search'].get('n')} searchId={d['empty_search'].get('searchId')} cols={d['empty_search'].get('cols')}", flush=True)
                await _shot(page, f"partner_{fld}")
                # P5: 본인이름 검색
                await page.evaluate(POPUP_SEARCH_JS, USERID)
                await page.wait_for_timeout(1_500)
                d["search_self"] = await page.evaluate(LAST_POPUP_GRID_JS, 10)
                print(f"[partner/P5] '{USERID}' -> n={d['search_self'].get('n')} rows={d['search_self'].get('sampleRows')}", flush=True)
                # 공공기관 예시 검색(통행료 거래처)
                await page.evaluate(POPUP_SEARCH_JS, "한국도로공사")
                await page.wait_for_timeout(1_500)
                d["search_toll"] = await page.evaluate(LAST_POPUP_GRID_JS, 10)
                print(f"[partner] '한국도로공사' -> n={d['search_toll'].get('n')} rows={d['search_toll'].get('sampleRows')}", flush=True)
                await _shot(page, f"partner_{fld}_search")
                await page.evaluate(js_lib.PICKER_CLOSE_JS)
                await page.wait_for_timeout(600)
                results["P4_P5_partner"] = d
                break
            results.setdefault("P4_attempts", []).append(d)
        await _dump("results", results)

        # ── 예산단위(BG_CD) 셀 피커 (P6) ─────────────────────────────────────────
        print("\n===== 예산단위 BG 셀 피커 =====", flush=True)
        for fld in ("BG_NM", "BG_CD"):
            d = await _open_cell_picker(page, fld, "예산단위")
            print(f"[budget] field={fld} open={d.get('open',{}).get('ok')} popup={d.get('popup_opened')}", flush=True)
            if d.get("popup_opened"):
                await page.wait_for_timeout(600)
                d["empty_search"] = await page.evaluate(LAST_POPUP_GRID_JS, 5)
                print(f"[budget] popup title={d['empty_search'].get('title')} n={d['empty_search'].get('n')} searchId={d['empty_search'].get('searchId')} cols={d['empty_search'].get('cols')}", flush=True)
                for kw in ("여비교통비", "국내출장"):
                    await page.evaluate(POPUP_SEARCH_JS, kw)
                    await page.wait_for_timeout(1_500)
                    g = await page.evaluate(LAST_POPUP_GRID_JS, 40)
                    d[f"search_{kw}"] = g
                    print(f"[budget] '{kw}' -> n={g.get('n')}", flush=True)
                    await _shot(page, f"budget_{kw}")
                await page.evaluate(js_lib.PICKER_CLOSE_JS)
                await page.wait_for_timeout(600)
                results["P6_budget"] = d
                break
            results.setdefault("P6_attempts", []).append(d)
        await _dump("results", results)

        # ── 프로젝트(PJT_CD) 셀 피커 (참고, card 와 동일 예상) ────────────────────
        print("\n===== 프로젝트 PJT 셀 피커 =====", flush=True)
        for fld in ("PJT_NM", "PJT_CD"):
            d = await _open_cell_picker(page, fld, "프로젝트")
            print(f"[project] field={fld} open={d.get('open',{}).get('ok')} popup={d.get('popup_opened')}", flush=True)
            if d.get("popup_opened"):
                await page.wait_for_timeout(600)
                d["empty_search"] = await page.evaluate(LAST_POPUP_GRID_JS, 5)
                print(f"[project] popup title={d['empty_search'].get('title')} n={d['empty_search'].get('n')} searchId={d['empty_search'].get('searchId')} cols={d['empty_search'].get('cols')}", flush=True)
                await _shot(page, f"project_{fld}")
                await page.evaluate(js_lib.PICKER_CLOSE_JS)
                await page.wait_for_timeout(600)
                results["project"] = d
                break
            results.setdefault("project_attempts", []).append(d)
        await _dump("results", results)

        # ── 상대계정거래처(BFC_PARTNER_CD) 셀 (P8) ───────────────────────────────
        print("\n===== 상대계정거래처 BFC_PARTNER 셀 =====", flush=True)
        for fld in ("BFC_PARTNER_CD", "BFC_PARTNER_NM"):
            d = await _open_cell_picker(page, fld, "상대계정거래처")
            print(f"[bfc] field={fld} open={d.get('open',{}).get('ok')} mag={bool(d.get('magnifier'))} popup={d.get('popup_opened')}", flush=True)
            if d.get("popup_opened"):
                await page.wait_for_timeout(600)
                d["empty_search"] = await page.evaluate(LAST_POPUP_GRID_JS, 5)
                print(f"[bfc] popup title={d['empty_search'].get('title')} n={d['empty_search'].get('n')} searchId={d['empty_search'].get('searchId')}", flush=True)
                await page.evaluate(POPUP_SEARCH_JS, USERID)
                await page.wait_for_timeout(1_500)
                d["search_self"] = await page.evaluate(LAST_POPUP_GRID_JS, 10)
                print(f"[bfc/P8] '{USERID}' -> n={d['search_self'].get('n')} rows={d['search_self'].get('sampleRows')}", flush=True)
                await _shot(page, f"bfc_{fld}")
                await page.evaluate(js_lib.PICKER_CLOSE_JS)
                await page.wait_for_timeout(600)
                results["P8_bfc"] = d
                break
            results.setdefault("P8_attempts", []).append(d)
            # 팝업이 안 뜨면 텍스트 입력 셀일 수 있음 → setValue 시도.
            if not d.get("popup_opened") and fld == "BFC_PARTNER_CD":
                sv = await page.evaluate(
                    "({field, value}) => { try { const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1])"
                    ".data('dewsControl')._grid; const n=g.getDataSource().getRowCount(); const row=Math.max(0,n-1);"
                    " const before=g.getValue(row,field); g.setValue(row,field,value); return {ok:true, before:String(before), after:String(g.getValue(row,field))}; }"
                    " catch(e){ return {ok:false, reason:String(e).slice(0,100)}; } }",
                    {"field": "BFC_PARTNER_NM", "value": USERID},
                )
                d["setvalue_bfc_nm"] = sv
                print(f"[bfc] setValue BFC_PARTNER_NM -> {sv}", flush=True)
        await _dump("results", results)

        print("\n===== PROBE2 COMPLETE (저장 없이 종료) =====", flush=True)
    except Exception as exc:  # noqa: BLE001
        results["error"] = f"probe2 exception: {exc!r}"
        print(f"[ERROR] {results['error']}", flush=True)
        await _shot(page, "exception")
        await _dump("results", results)
    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
