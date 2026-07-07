"""HEADLESS 읽기전용 프로브 4차 — P4 보충: 거래처 피커의 '카드' 결의구분 문맥 도달성.

카탈로그 sync(code_sync._run_entry_chain)는 결의구분=카드 + 증빙 01(→법인카드 팝업 CARD_WIN)
문맥으로 고정돼 있고, dump_budget_units/dump_projects 는 CARD_WIN 스코프 picker_btn_js 로
일괄적용 폼 코드피커(bg_cd/pjt_cd)를 연다. 이 프로브는 **그 카드 문맥에서 partner_cd(거래처)
코드피커가 존재·도달 가능한지**를 확정해, dump_partners 가 기존 진입 체인을 그대로 재사용할 수
있는지 판정한다.

⚠ F7 저장 절대 금지. 피커 열기/검색/읽기/닫기만. Usage: cd backend && .venv/bin/python e2e/trip_probe4.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import Page, async_playwright  # noqa: E402

from app.agents.common.nodes import (  # noqa: E402 — code_sync._run_entry_chain 과 동일 7노드
    make_add_row_node,
    make_login_node,
    make_menu_nav_node,
    make_open_evdn_node,
    make_select_evdn_node,
    make_set_gubun_node,
    make_user_type_node,
)
from app.config import get_settings  # noqa: E402
from nbkit.omnisol import js_lib  # noqa: E402
from nbkit.omnisol.js_lib import CARD_WIN  # noqa: E402


async def _run_entry_chain(page, userid: str, password: str) -> None:
    """code_sync._run_entry_chain 미러 — 카드결의 진입 7노드(login→…→증빙01→CARD_WIN)."""
    events: asyncio.Queue = asyncio.Queue()

    async def _drain() -> None:
        while True:
            await events.get()

    drainer = asyncio.create_task(_drain())
    state = {"page": page, "events": events, "userid": userid, "password": password, "params": {}}
    try:
        for name, node in [
            ("login", make_login_node()),
            ("user_type", make_user_type_node("회계")),
            ("menu_nav", make_menu_nav_node()),
            ("set_gubun", make_set_gubun_node("카드")),
            ("add_row", make_add_row_node()),
            ("open_evdn", make_open_evdn_node()),
            ("select_evdn", make_select_evdn_node("01")),
        ]:
            out = await node(state)
            state.update(out or {})
            if state.get("error"):
                raise RuntimeError(f"진입 실패({name}): {state['error']}")
    finally:
        drainer.cancel()

import os  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

# CARD_WIN(법인카드 팝업) 안의 코드피커 래퍼 전량 발견(field id + 라벨).
CARD_WIN_PICKERS_JS = f"""() => {{
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const win = {CARD_WIN}; if (!win) return {{ ok:false, reason:'no-card-win' }};
  const out = [];
  for (const wr of win.querySelectorAll('[id$=-wrapper]')) {{
    if (wr.offsetParent === null) continue;
    const btn = wr.querySelector('.dews-codepicker-button, .dews-multicodepicker-button');
    if (!btn) continue;
    out.push({{ field: wr.id.replace(/-wrapper$/, ''), multi: btn.className.includes('multi') }});
  }}
  return {{ ok:true, pickers: out }};
}}"""

# 마지막 열린 non-법인카드 k-window(피커 팝업) 덤프 — card 의 PICKER 규칙과 동일 셀렉터.
PICKER_DUMP_JS = """([fields, limit]) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const p = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];
  if (!p) return { ok:false, reason:'no-pop' };
  const title = c((p.querySelector('.k-window-title')||{}).innerText);
  try {
    const g = window.jQuery(p.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const ds = g.getDataSource(); const n = ds.getRowCount();
    const cols = (g.getColumns ? g.getColumns() : []).map(cc => cc.fieldName || cc.name).filter(Boolean);
    const take = Math.min(n, limit || 10);
    const rows = take > 0 ? ds.getJsonRows(0, take - 1) : [];
    const out = rows.map(r => { const o = {}; for (const f of fields) o[f] = r[f]==null?null:String(r[f]); return o; });
    const kwEl = p.querySelector('#keyword') || p.querySelector('#s_search_key')
      || p.querySelector('#customTextBox') || p.querySelector('[id$=search_key]') || p.querySelector('[id*=keyword]');
    return { ok:true, title, n, cols, searchId: kwEl ? (kwEl.id || '(no-id)') : null, rows: out };
  } catch(e) { return { ok:false, title, reason:String(e).slice(0,120) }; }
}"""


async def main() -> None:
    results: dict = {"userid": USERID, "context": "카드(card) 결의구분 + 증빙01(CARD_WIN open)"}
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS)
    page = await browser.new_page(viewport=js_lib.__dict__.get("VIEWPORT") or {"width": 1600, "height": 1000})
    from nbkit.omnisol import selectors
    await page.set_viewport_size(selectors.VIEWPORT)
    _ = get_settings().erp_base
    try:
        print("[entry] 카드 진입 체인(code_sync._run_entry_chain) 재사용…", flush=True)
        await _run_entry_chain(page, USERID, PASSWORD)
        await page.wait_for_timeout(1_500)
        card_open = await page.evaluate(f"() => !!({CARD_WIN})")
        results["card_win_open"] = card_open
        print(f"[entry] CARD_WIN open={card_open}", flush=True)
        await page.screenshot(path=str(ARTIFACTS / "trip_probe4_entry.png"))

        # 1) CARD_WIN 안의 코드피커 래퍼 전량 — partner_cd 존재 여부.
        wp = await page.evaluate(CARD_WIN_PICKERS_JS)
        results["card_win_pickers"] = wp
        fields = [p.get("field") for p in (wp.get("pickers") or [])]
        print(f"[Q1] CARD_WIN 코드피커 필드들: {fields}", flush=True)
        has_partner = any(f in ("partner_cd", "s_partner_cd") for f in fields)
        results["partner_reachable_in_card"] = has_partner
        print(f"[Q1] partner_cd 카드 문맥 존재 = {has_partner}", flush=True)

        # 2) partner_cd 있으면 열어서 내용 덤프 + 이트라이브2 검색.
        if has_partner:
            pf = ["PARTNER_CD", "PARTNER_NM", "PARTNER_FG_NM", "BIZR_NO"]
            box = await page.evaluate(js_lib.picker_btn_js("partner_cd"))
            print(f"[Q1] partner_cd 버튼 box={box}", flush=True)
            if box:
                await page.mouse.click(box["x"], box["y"])
                await page.wait_for_timeout(1_800)
                empty = await page.evaluate(PICKER_DUMP_JS, [pf, 10])
                results["card_partner_empty"] = empty
                print(f"[Q3] 카드 문맥 거래처 팝업 title={empty.get('title')} n={empty.get('n')} searchId={empty.get('searchId')} cols={empty.get('cols')}", flush=True)
                # 검색 이트라이브2 (card PICKER_SEARCH_JS + Enter)
                s = await page.evaluate(js_lib.PICKER_SEARCH_JS, USERID)
                if s.get("ok"):
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(1_800)
                dumped = await page.evaluate(PICKER_DUMP_JS, [pf, 15])
                exact = [r for r in (dumped.get("rows") or []) if (r.get("PARTNER_NM") or "").strip() == USERID]
                results["card_partner_search_self"] = {"searchField": s.get("field"), "n": dumped.get("n"), "exact": len(exact), "rows": dumped.get("rows")}
                print(f"[Q3] 검색 '{USERID}' searchField={s.get('field')} n={dumped.get('n')} exact={len(exact)}", flush=True)
                await page.screenshot(path=str(ARTIFACTS / "trip_probe4_partner.png"))
                await page.evaluate(js_lib.PICKER_CLOSE_JS)
                await page.wait_for_timeout(600)

        (ARTIFACTS / "trip_probe4_results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print("\n[dump] trip_probe4_results.json", flush=True)
        print("===== PROBE4 COMPLETE (저장 없이 종료) =====", flush=True)
    except Exception as exc:  # noqa: BLE001
        results["error"] = f"probe4 exception: {exc!r}"
        print(f"[ERROR] {results['error']}", flush=True)
        try:
            await page.screenshot(path=str(ARTIFACTS / "trip_probe4_exception.png"))
        except Exception:  # noqa: BLE001
            pass
        (ARTIFACTS / "trip_probe4_results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
