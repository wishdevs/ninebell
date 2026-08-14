"""HEADLESS 프로브 — 구매요청/이동요청 체크박스 ↔ 조회(F2) 필터 연동 확인.

team-lead 지시(2026-08-13): 진입 시 둘 다 체크 상태(기실측). (a) 이동요청 해제→조회, (b) 구매요청
해제·이동요청만→조회. '다시 조회(초기화)' 확인 다이얼로그 존재/처리 방법 확정. 체크박스 셀렉터/
조작법 기록.

⚠ 체크박스 클릭·조회(F2)는 조회조건 확정 동작(데이터 생성 아님) — 저장(F7)·행 데이터 변경 없음.

베이스라인: CX85-137(2297) 프로젝트로 고정(검증된 `purchase_order_project_apply_probe.py` 사이클
재사용) 후 체크박스만 바꿔 3-way 비교(둘다체크/구매요청만/이동요청만).

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/purchase_order_checkbox_filter_probe.py
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

from app.agents.purchase_order.js import SUBMIT_KEYWORD_JS  # noqa: E402
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

SET_KEYWORD_JS = r"""(q) => {
  const i = document.querySelector('#keyword');
  if (!i) return false;
  const s = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(i), 'value').set;
  s.call(i, q); i.dispatchEvent(new Event('input', { bubbles: true })); i.focus();
  return true;
}"""

WIN_STATE_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  return wins.map(w => ({ title: c((w.querySelector('.k-window-title')||{}).innerText) }));
}"""

SELECT_ROW_JS = r"""(pjtNo) => {
  const wins = [...document.querySelectorAll('.k-window')].filter(d => d.offsetParent !== null);
  const dlg = wins[wins.length - 1];
  if (!dlg) return { ok: false };
  const g = window.jQuery(dlg.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
  const ds = g.getDataSource();
  const rows = ds.getJsonRows(0, ds.getRowCount() - 1);
  const i = rows.findIndex(r => String(r.PJT_NO) === String(pjtNo));
  if (i < 0) return { ok: false };
  g.setCurrent({ itemIndex: i, fieldName: 'PJT_NM' });
  g.setSelection({ startRow: i, endRow: i, startColumn: 0, endColumn: 0 });
  return { ok: true };
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

# 라벨 기준 체크박스 rect+checked — 구매요청/이동요청 공용.
# ⚠ 실측(2026-08-13): 두 체크박스는 <li> 없이 같은 <span> 안에 나란히 있고, 각 <label for="…">
#   이 대응 <input id="…"> 를 직접 가리킨다(구매요청=#s_pu_chk, 이동요청=#s_move_chk). 이전
#   버전은 closest('li')가 없어 closest('div')로 과확장 → 두 라벨이 같은 컨테이너를 가리켜
#   li.querySelector('input[type=checkbox]')가 항상 첫 체크박스(#s_pu_chk)만 찾는 버그였다
#   (셀렉터 드리프트/과확장 — 진단: purchase_order_checkbox_dom_diag). label[for] 직결로 수정.
CHECKBOX_RECT_JS = r"""(label) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const lbl = [...document.querySelectorAll('label[for]')].find(e => e.offsetParent !== null && c(e.innerText) === label);
  if (!lbl) return null;
  const cb = document.getElementById(lbl.getAttribute('for'));
  if (!cb) return null;
  const r = cb.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2), checked: cb.checked, id: cb.id };
}"""

# 조회 직후 뜰 수 있는 확인 다이얼로그(예/아니오·확인/취소 등) 전량 스캔 — 결과그리드 팝업과 구분.
CONFIRM_DIALOG_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window, .k-dialog, [role=alertdialog]')].filter(w => w.offsetParent !== null);
  return wins.map(w => {
    const title = c((w.querySelector('.k-window-title')||{}).innerText);
    const text = c(w.innerText).slice(0, 200);
    const buttons = [...w.querySelectorAll('button')].filter(b => b.offsetParent !== null).map(b => c(b.innerText));
    const r = w.getBoundingClientRect();
    return { title, text, buttons, rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) } };
  });
}"""

TREEGRID_DIST_JS = r"""() => {
  try {
    const el = document.querySelector('.dews-ui-treegrid');
    if (!el) return { ok: false, reason: 'no-treegrid' };
    const g = window.jQuery(el).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const count = ds.getRowCount();
    const levelCounts = {};
    const purFg = { Y: 0, N: 0, other: 0 };
    const mvFg = { Y: 0, N: 0, other: 0 };
    for (let i = 0; i < count; i++) {
      let level = -1;
      try { level = ds.getLevel(i); } catch (e) {}
      levelCounts[level] = (levelCounts[level] || 0) + 1;
      let pf = null, mf = null;
      try { pf = g.getValue(i, 'PUR_FG'); } catch (e) {}
      try { mf = g.getValue(i, 'MV_FG'); } catch (e) {}
      if (pf === 'Y') purFg.Y++; else if (pf === 'N') purFg.N++; else purFg.other++;
      if (mf === 'Y') mvFg.Y++; else if (mf === 'N') mvFg.N++; else mvFg.other++;
    }
    return { ok: true, count, levelCounts, purFg, mvFg };
  } catch (e) { return { ok: false, err: String(e).slice(0, 150) }; }
}"""


async def _shot(page: Page, name: str) -> None:
    try:
        p = str(ARTIFACTS / f"purchase_order_checkbox_{name}.png")
        await page.screenshot(path=p, full_page=True)
        print(f"[shot] {p}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[shot] skipped {name}: {exc!r}", flush=True)


async def _dump(name: str, data) -> None:
    path = ARTIFACTS / f"purchase_order_checkbox_{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[dump] {path}", flush=True)


async def _set_checkbox(page: Page, label: str, want_checked: bool) -> dict:
    """체크박스를 want_checked 상태로 보장 — 현재 상태 읽고 다르면 클릭, 재확인."""
    rect = await page.evaluate(CHECKBOX_RECT_JS, label)
    if not rect:
        return {"ok": False, "reason": f"{label} 체크박스 미발견"}
    if rect["checked"] != want_checked:
        await page.mouse.click(rect["x"], rect["y"])
        await page.wait_for_timeout(400)
        rect2 = await page.evaluate(CHECKBOX_RECT_JS, label)
        return {"ok": rect2 and rect2["checked"] == want_checked, "rect": rect, "after": rect2}
    return {"ok": True, "rect": rect, "unchanged": True}


async def _query_and_handle_dialog(page: Page, *, label: str) -> dict:
    """조회(F2) 클릭 → 확인 다이얼로그 감지·처리(있으면 첫 버튼 클릭) → 그리드 분포 덤프."""
    result: dict = {"label": label}
    lookup_box = await page.evaluate(LOOKUP_BTN_JS)
    if not lookup_box:
        result["error"] = "조회 버튼 미발견"
        return result
    await page.mouse.click(lookup_box["x"], lookup_box["y"])

    # 확인 다이얼로그 조밀 폴링(최대 2s) — 뜨면 스크린샷+버튼목록 기록 후 첫 확인성 버튼 클릭.
    dialog_seen = None
    t0 = time.monotonic()
    while (time.monotonic() - t0) < 2.0:
        dialogs = await page.evaluate(CONFIRM_DIALOG_JS)
        # 데이터그리드가 있는 프로젝트도움창 등은 제외 — 버튼 2개 이하 + 그리드 없는 소형 팝업만 '확인다이얼로그'로 간주.
        cand = next((d for d in dialogs if d["buttons"] and len(d["buttons"]) <= 3 and "프로젝트" not in d["title"]), None)
        if cand:
            dialog_seen = cand
            break
        await page.wait_for_timeout(150)
    result["dialog_seen"] = dialog_seen
    if dialog_seen:
        await _shot(page, f"{label}_dialog")
        # 확인성 버튼(예/확인) 우선 클릭.
        btn_text = next((b for b in dialog_seen["buttons"] if b in ("예", "확인", "OK", "Yes")), dialog_seen["buttons"][0])
        # 버튼 좌표 재조회(다이얼로그 rect 기준 텍스트 매칭).
        box = await page.evaluate(
            r"""(btnText) => {
              const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
              const wins = [...document.querySelectorAll('.k-window, .k-dialog')].filter(w => w.offsetParent !== null);
              for (const w of wins) {
                const b = [...w.querySelectorAll('button')].find(x => x.offsetParent !== null && c(x.innerText) === btnText);
                if (b) { const r = b.getBoundingClientRect(); return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2) }; }
              }
              return null;
            }""",
            btn_text,
        )
        result["dialog_button_clicked"] = btn_text
        result["dialog_button_box"] = box
        if box:
            await page.mouse.click(box["x"], box["y"])
    await page.wait_for_timeout(2_500)
    await _shot(page, f"{label}_after_query")
    dist = await page.evaluate(TREEGRID_DIST_JS)
    result["distribution"] = dist
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

        # ── 베이스라인: 프로젝트를 CX85-137로 고정(검증+재시도, purchase_order_zj90_search_probe
        #    실측 완화책 그대로 — 팝업당 검색 1회, 실패(팝업소멸 포함)면 재오픈 재시도 상한 2회) ──
        box = await page.evaluate(js_lib.PROJECT_PICKER_BOX_JS)
        baseline_ok = False
        baseline_attempts = []
        for attempt in range(1, 3):
            await page.mouse.click(box["x"], box["y"])
            await page.wait_for_timeout(1_000)
            win_open = await page.evaluate(WIN_STATE_JS)
            if not win_open:
                baseline_attempts.append({"attempt": attempt, "reason": "popup-open-failed"})
                continue
            await page.evaluate(SET_KEYWORD_JS, "CX85-137")
            # trusted Enter 금지 — 네이티브 폼 제출→앱 소프트리셋으로 팝업 영구 소멸(2026-08-14 실측).
            await page.evaluate(SUBMIT_KEYWORD_JS)
            await page.wait_for_timeout(1_500)
            win_after_search = await page.evaluate(WIN_STATE_JS)
            if not win_after_search:
                baseline_attempts.append({"attempt": attempt, "reason": "popup-vanished-after-search"})
                continue
            sel = await page.evaluate(SELECT_ROW_JS, "2297")
            if not sel.get("ok"):
                baseline_attempts.append({"attempt": attempt, "reason": "select-failed", "sel": sel})
                continue
            apply_box = await page.evaluate(APPLY_BTN_JS)
            if not apply_box:
                baseline_attempts.append({"attempt": attempt, "reason": "apply-btn-not-found"})
                continue
            await page.mouse.click(apply_box["x"], apply_box["y"])
            await page.wait_for_timeout(1_000)
            field_val = await page.evaluate(js_lib.FIELD_DISPLAY_JS, "프로젝트")
            baseline_attempts.append({"attempt": attempt, "reason": "ok", "field_val": field_val})
            if field_val and "CX85-137" in field_val:
                baseline_ok = True
                break
        results["baseline_project_select"] = {"ok": baseline_ok, "attempts": baseline_attempts}
        print(f"[baseline] 프로젝트 선택 ok={baseline_ok} attempts={baseline_attempts}", flush=True)
        if not baseline_ok:
            results["error"] = "베이스라인 프로젝트 선택 실패(재시도 상한 도달) — 체크박스 시나리오 신뢰불가, 중단"
            await _shot(page, "baseline_failed")
            await _dump("results", results)
            return

        # ── 초기 체크박스 상태 기록 ──
        cb_purreq_init = await page.evaluate(CHECKBOX_RECT_JS, "구매요청")
        cb_movreq_init = await page.evaluate(CHECKBOX_RECT_JS, "이동요청")
        results["checkbox_initial"] = {"구매요청": cb_purreq_init, "이동요청": cb_movreq_init}
        print(f"[checkbox] 초기상태 구매요청={cb_purreq_init} 이동요청={cb_movreq_init}", flush=True)

        # ── 시나리오 0: 둘다 체크(초기상태) 그대로 조회 — 베이스라인 분포 ──
        r0 = await _query_and_handle_dialog(page, label="both_checked")
        results["scenario_both_checked"] = r0
        print(f"[both_checked] dialog={r0.get('dialog_seen')} dist={r0.get('distribution')}", flush=True)

        # ── 시나리오 (a): 이동요청 해제(구매요청 유지) → 조회 ──
        set_a = await _set_checkbox(page, "이동요청", False)
        results["set_이동요청_off"] = set_a
        print(f"[set] 이동요청 해제 결과={set_a}", flush=True)
        ra = await _query_and_handle_dialog(page, label="a_purreq_only")
        results["scenario_a_purreq_only"] = ra
        print(f"[a_purreq_only] dialog={ra.get('dialog_seen')} dist={ra.get('distribution')}", flush=True)

        # ── 시나리오 (b): 구매요청 해제 + 이동요청 재체크(이동요청만) → 조회 ──
        set_b1 = await _set_checkbox(page, "구매요청", False)
        set_b2 = await _set_checkbox(page, "이동요청", True)
        results["set_구매요청_off"] = set_b1
        results["set_이동요청_on"] = set_b2
        print(f"[set] 구매요청 해제={set_b1} 이동요청 재체크={set_b2}", flush=True)
        rb = await _query_and_handle_dialog(page, label="b_movreq_only")
        results["scenario_b_movreq_only"] = rb
        print(f"[b_movreq_only] dialog={rb.get('dialog_seen')} dist={rb.get('distribution')}", flush=True)

        await _dump("results", results)
        print("\n===== CHECKBOX FILTER PROBE COMPLETE =====", flush=True)

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
