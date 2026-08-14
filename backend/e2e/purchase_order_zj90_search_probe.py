"""HEADLESS 읍기전용 프로브 — '프로젝트 도움창'에서 ZJ90 검색 시 팝업 소멸 원인 격리.

사용자 확인(2026-08-13): **'ZJ90-130, 8CH BS PROCESS' 는 실재 프로젝트다** — 그러니 이전 프로브의
팝업 소멸은 "데이터 없음" 이 아니라 **트리거/타이밍 문제**로 접근한다.

가설(자가수정 루프, 각 attempt 가설 1개만 변경):
  attempt 1 — 기존과 동일(JS 네이티브 setter + Enter, "ZJ90") — 재현 확인(회귀 기준선).
  attempt 2 — 키워드를 더 구체적으로("ZJ90-130") — 부분 키워드가 문제였는지.
  attempt 3 — **JS setter 대신 실제 클릭+키보드 타이핑**(erp-headless-grid-automation 원칙:
              프로그램적 setter 가 real user typing 과 이벤트 시퀀스가 달라 팝업 lifecycle
              핸들러를 다르게 태울 수 있다) — Enter 직후 100ms 간격으로 3초간 .k-window 개수를
              폴링해 소멸 **직전** 프레임을 스크린샷으로 잡는다.
  attempt 4 — Enter 대신 **팝업 내 조회/검색 트리거 버튼**(있다면)을 클릭.
  대조군 — 매 attempt 뒤 "CX85"(known-good) 로 동일 절차를 돌려 회귀 여부 확인.

⚠ 읍기 전용: 결과 그리드 행 선택/적용 클릭 없음(그건 project_apply_probe 담당). 검색만.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/purchase_order_zj90_search_probe.py
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

# 팝업 내부 버튼/아이콘 전량(조회/검색 트리거 후보 찾기).
DUMP_POPUP_ACTIONS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const dlg = wins[wins.length - 1];
  if (!dlg) return [];
  const els = [...dlg.querySelectorAll('button, span.k-icon, i, [role=button]')].filter(e => e.offsetParent !== null);
  return els.map(e => {
    const r = e.getBoundingClientRect();
    return {
      tag: e.tagName, text: c(e.innerText), cls: (e.className||'').toString().slice(0,100),
      x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2), w: Math.round(r.width), h: Math.round(r.height),
    };
  });
}"""

READ_GRID_JS = r"""() => {
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


async def _shot(page: Page, name: str) -> None:
    try:
        p = str(ARTIFACTS / f"purchase_order_zj90_{name}.png")
        await page.screenshot(path=p, full_page=True)
        print(f"[shot] {p}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[shot] skipped {name}: {exc!r}", flush=True)


async def _dump(name: str, data) -> None:
    path = ARTIFACTS / f"purchase_order_zj90_{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[dump] {path}", flush=True)


async def _poll_window_state(page: Page, *, label: str, cap_ms: int = 3_000, interval_ms: int = 150) -> list[dict]:
    """검색 트리거 직후 .k-window 상태를 조밀 폴링(소멸 직전 프레임을 잡기 위함)."""
    log: list[dict] = []
    t0 = time.monotonic()
    shot_idx = 0
    while (time.monotonic() - t0) * 1_000 < cap_ms:
        wins = await page.evaluate(WIN_STATE_JS)
        entry = {"t_ms": int((time.monotonic() - t0) * 1_000), "win_count": len(wins), "titles": wins}
        log.append(entry)
        if not wins and log[-2:][0].get("win_count", 0) > 0 if len(log) >= 2 else False:
            pass  # 소멸 감지는 아래 요약에서
        await page.wait_for_timeout(interval_ms)
    print(f"[{label}] 폴링 로그: {log}", flush=True)
    return log


async def _try_search(
    page: Page, *, method: str, keyword: str, label: str
) -> dict:
    """검색 1회 시도 — method: 'js_enter' | 'type_enter' | 'action_click'. 반환 진단 dict."""
    result: dict = {"method": method, "keyword": keyword}
    before = await page.evaluate(WIN_STATE_JS)
    result["win_before"] = before

    if method == "js_enter":
        ok = await page.evaluate(SET_KEYWORD_JS, keyword)
        result["set_ok"] = ok
        await page.keyboard.press("Enter")
    elif method == "type_enter":
        try:
            await page.click("#keyword")
            await page.locator("#keyword").select_text()
            await page.keyboard.press_sequentially(keyword, delay=60)
            result["set_ok"] = True
        except Exception as exc:  # noqa: BLE001
            result["set_ok"] = False
            result["set_err"] = str(exc)
        await page.keyboard.press("Enter")
    elif method == "action_click":
        ok = await page.evaluate(SET_KEYWORD_JS, keyword)
        result["set_ok"] = ok
        actions = await page.evaluate(DUMP_POPUP_ACTIONS_JS)
        result["actions_available"] = actions
        # 조회/검색 유사 아이콘 후보(검색 관련 클래스명) 탐색.
        cand = next((a for a in actions if "search" in a["cls"].lower() or "magnif" in a["cls"].lower()), None)
        result["click_candidate"] = cand
        if cand:
            await page.mouse.click(cand["x"], cand["y"])
        else:
            await page.keyboard.press("Enter")  # 후보 없으면 폴백

    # 조밀 폴링(소멸 시점 격리) — 실시간 3s.
    poll_log = await _poll_window_state(page, label=f"{label}_{method}_{keyword}", cap_ms=3_000, interval_ms=150)
    result["poll_log"] = poll_log
    vanished_at = next((e["t_ms"] for e in poll_log if e["win_count"] == 0), None)
    result["vanished_at_ms"] = vanished_at

    after = await page.evaluate(WIN_STATE_JS)
    result["win_after"] = after
    if after:
        grid = await page.evaluate(READ_GRID_JS)
        result["grid_after"] = grid
    await _shot(page, f"{label}_{method}_{keyword}_after")
    return result


async def main() -> None:
    results: dict = {"userid": USERID, "attempts": []}
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
        if not box:
            results["error"] = "프로젝트 피커 버튼 미발견"
            await _dump("results", results)
            return

        # ── attempt 1: 기존과 동일(JS setter + Enter, "ZJ90") — 재현 확인 ──
        await page.mouse.click(box["x"], box["y"])
        await page.wait_for_timeout(1_000)
        actions0 = await page.evaluate(DUMP_POPUP_ACTIONS_JS)
        results["popup_actions_initial"] = actions0
        print(f"[actions] 팝업 내 클릭가능 요소 {len(actions0)}개: {actions0}", flush=True)
        await _shot(page, "00_popup_open")

        r1 = await _try_search(page, method="js_enter", keyword="ZJ90", label="attempt1")
        results["attempts"].append(r1)
        print(f"[attempt1] vanished_at_ms={r1['vanished_at_ms']}", flush=True)

        # 팝업이 닫혔으면 다시 연다(다음 attempt 를 위해).
        cur = await page.evaluate(WIN_STATE_JS)
        if not cur:
            await page.mouse.click(box["x"], box["y"])
            await page.wait_for_timeout(1_000)

        # ── attempt 2: 더 구체적 키워드("ZJ90-130") ──
        r2 = await _try_search(page, method="js_enter", keyword="ZJ90-130", label="attempt2")
        results["attempts"].append(r2)
        print(f"[attempt2] vanished_at_ms={r2['vanished_at_ms']}", flush=True)

        cur = await page.evaluate(WIN_STATE_JS)
        if not cur:
            await page.mouse.click(box["x"], box["y"])
            await page.wait_for_timeout(1_000)

        # ── attempt 3: 실제 클릭+키보드 타이핑(JS setter 대신) ──
        r3 = await _try_search(page, method="type_enter", keyword="ZJ90-130", label="attempt3")
        results["attempts"].append(r3)
        print(f"[attempt3] vanished_at_ms={r3['vanished_at_ms']}", flush=True)

        cur = await page.evaluate(WIN_STATE_JS)
        if not cur:
            await page.mouse.click(box["x"], box["y"])
            await page.wait_for_timeout(1_000)

        # ── attempt 4: "8CH" 키워드(다른 부분 문자열) ──
        r4 = await _try_search(page, method="js_enter", keyword="8CH", label="attempt4")
        results["attempts"].append(r4)
        print(f"[attempt4] vanished_at_ms={r4['vanished_at_ms']}", flush=True)

        cur = await page.evaluate(WIN_STATE_JS)
        if not cur:
            await page.mouse.click(box["x"], box["y"])
            await page.wait_for_timeout(1_000)

        # ── 대조군: CX85(known-good) 동일 절차 회귀 확인 ──
        rc = await _try_search(page, method="js_enter", keyword="CX85", label="control")
        results["attempts"].append(rc)
        print(f"[control CX85] vanished_at_ms={rc['vanished_at_ms']} grid_after={rc.get('grid_after')}", flush=True)

        await _dump("results", results)
        print("\n===== ZJ90 SEARCH VANISH ISOLATION COMPLETE =====", flush=True)

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
