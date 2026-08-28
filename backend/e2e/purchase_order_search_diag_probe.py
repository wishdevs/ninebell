"""HEADLESS 진단 프로브 — 프로젝트 도움창 검색 실패('ETRIBE ERP TEST 001') 원인 규명.

읽기 + 조회조건 확정(도움창 열기/검색)만. 적용·저장·결재 없음.

  1. 도움창 열고 팝업 내부 컨트롤(입력·버튼) 덤프 — '조회' 버튼 존재 여부
  2. 운영 코드 steps.open_and_search_once 를 키워드별로 실행하며 DEBUG 로그·결과 기록
  3. 실패 키워드는 팝업 안 '조회' 버튼 실클릭 대안도 실측

Usage:
    cd backend && .venv/bin/python e2e/purchase_order_search_diag_probe.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright  # noqa: E402

from app.agents.purchase_order import js, steps  # noqa: E402
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
KEYWORDS = [k for k in os.environ.get("E2E_KEYWORDS", "ETRIBE ERP TEST 001|ETRIBE|ZJ90-130").split("|") if k]
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
DEEPLINK = "/PU/PUOPRQ00200_X20616"

POPUP_CONTROLS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const kw = document.querySelector('#keyword');
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const dlg = kw ? wins.find(w => w.contains(kw)) : wins[wins.length-1];
  if (!dlg) return null;
  const vis = e => e.offsetParent !== null;
  return {
    title: c((dlg.querySelector('.k-window-title')||{}).innerText),
    inputs: [...dlg.querySelectorAll('input,select')].filter(vis).map(i => ({id:i.id, name:i.name, type:i.type, value:i.value, placeholder:i.placeholder})),
    buttons: [...dlg.querySelectorAll('button,a.k-button,[role=button],.btn')].filter(vis).map(b => ({id:b.id, cls:c(b.className).slice(0,60), text:c(b.innerText||b.value||b.title)})),
    form: kw && kw.form ? {action: kw.form.action, method: kw.form.method, hasOnsubmit: !!kw.form.onsubmit} : null,
  };
}"""

POPUP_BUTTON_BOX_JS = r"""(label) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const kw = document.querySelector('#keyword');
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const dlg = kw ? wins.find(w => w.contains(kw)) : null;
  if (!dlg) return null;
  const b = [...dlg.querySelectorAll('button,a.k-button,[role=button]')].filter(e => e.offsetParent !== null).find(e => c(e.innerText||e.title) === label);
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return { x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2) };
}"""


async def main() -> None:
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    for noisy in ("asyncio", "urllib3", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    h = logging.StreamHandler(sys.stdout); h.setFormatter(logging.Formatter("[steps] %(message)s"))
    steps.logger.addHandler(h); steps.logger.setLevel(logging.DEBUG); steps.logger.propagate = False
    results: dict = {"userid": USERID, "keywords": {}}
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS)
    raw_page = await browser.new_page(viewport=LIVE_VIEWPORT)
    page = _ScaledPage(raw_page, DELAY_SCALE)
    base = get_settings().erp_base
    try:
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await ensure_user_type(page, "SCM")
        await navigate_menu(page, DEEPLINK, base, label="diag", grids_required=1)
        await page.wait_for_timeout(1_500)

        # 1. 팝업 컨트롤 덤프
        box = await page.evaluate(js_lib.PROJECT_PICKER_BOX_JS)
        await page.mouse.click(box["x"], box["y"])
        st = await steps._poll(page, js.POPUP_STATE_JS, lambda s: bool(s and s.get("present") and s.get("gridReady")), steps.POPUP_OPEN_CAP_MS)
        await page.wait_for_timeout(1_000)
        results["popup_controls"] = await page.evaluate(POPUP_CONTROLS_JS)
        results["popup_state"] = st
        results["popup_pre_grid"] = await page.evaluate(js.READ_POPUP_GRID_JS, 5)
        print("[controls]", json.dumps(results["popup_controls"], ensure_ascii=False), flush=True)
        await steps.close_popup(page)
        await page.wait_for_timeout(800)

        # 2. 운영 코드 경로 — 키워드별
        for kw in KEYWORDS:
            t0 = time.monotonic()
            r = await steps.open_and_search_once(page, kw)
            r["ms"] = int((time.monotonic() - t0) * 1000)
            r["rows"] = (r.get("rows") or [])[:5]
            r["popup_state_after"] = await page.evaluate(js.POPUP_STATE_JS)
            r["keyword_value_after"] = await page.evaluate(js.KEYWORD_VALUE_JS)
            results["keywords"][kw] = {"prod": r}
            print(f"[prod] {kw!r} → ok={r.get('ok')} attempt={r.get('attempt')} rows={len(r.get('rows') or [])} ms={r['ms']} reason={r.get('reason')} state_after={r['popup_state_after']}", flush=True)
            await steps.close_popup(page)
            await page.wait_for_timeout(800)

        # 3. 대안 — 팝업 안 '조회' 버튼 실클릭 (첫 키워드)
        kw = KEYWORDS[0]
        await page.mouse.click(box["x"], box["y"])
        st = await steps._poll(page, js.POPUP_STATE_JS, lambda s: bool(s and s.get("present") and s.get("gridReady")), steps.POPUP_OPEN_CAP_MS)
        await page.wait_for_timeout(1_000)
        typed = await steps._type_keyword(page, kw)
        bbox = await page.evaluate(POPUP_BUTTON_BOX_JS, "조회")
        alt = {"typed": typed, "button_box": bbox}
        if bbox:
            await page.mouse.click(bbox["x"], bbox["y"])
            await page.wait_for_timeout(2_000)
            alt["state_after"] = await page.evaluate(js.POPUP_STATE_JS)
            g = await page.evaluate(js.READ_POPUP_GRID_JS, 5)
            alt["grid_after"] = g
        results["keywords"][kw]["click_button"] = alt
        print(f"[alt-click] {kw!r} → {json.dumps(alt, ensure_ascii=False)[:600]}", flush=True)
        await steps.close_popup(page)
    except Exception as exc:  # noqa: BLE001
        results["error"] = repr(exc)
        print("[ERROR]", results["error"], flush=True)
    finally:
        out = ARTIFACTS / "po_search_diag.json"
        out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print("[dump]", out, flush=True)
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
