"""HEADLESS 읽기 위주 프로브 — 사용자유형 선택기(드롭다운) 실제 DOM 구조 실측.

목적: `switch_user_type(target='회계')` 가 "회계사용자로 전환하지 못했습니다(현재 유형
미반영)" 로 실패하는 원인 확정. 사용자 증언: 종전 `회계사용자(예외)`·`인사사용자(예외)`
2개에 `SCM-구매` 가 추가됨.

가설(코드 근거, backend/nbkit/omnisol/js_lib.py):
  H1 — UT_DROPDOWN_BOX_JS/UT_DISPLAY_JS 는 `.k-dropdown` 중 innerText 가 /사용자/ 매치하는
       것만 찾는다. 현재 선택이 'SCM-구매'(접미사 '사용자' 없음)면 그 자체가 안 잡혀 드롭다운을
       못 열거나 표시값을 못 읽는다.
  H2 — 옵션이 2→3개로 늘어 리스트 레이아웃/스크롤이 바뀌어 li 좌표가 어긋난다.
  (부가, 실측 중 발견) H0 — `switch_user_type()` 첫 줄이 무조건 `open_user_panel()` 을 호출한다.
       그런데 로그인 직후 `ensure_logged_in()`→`read_profile()` 이 이미 패널을 **열어 놓은
       상태로 남긴다** — 이 상태에서 `open_user_panel()` 을 한 번 더 부르면 아바타 재클릭이
       패널을 **닫는다**(실측: `.user-info-box` rect 가 실값→0/0/0/0). attempt=1 은 이 때문에
       패널이 닫힌 채로 실패하고, attempt=2(`attempt>1` 재오픈)가 패널은 되살리지만 H1 은
       그대로 남아 있어 결국 두 시도 모두 실패한다.

── 실측 결론(2026-08-01) 및 반영 상태 ─────────────────────────────────────────────
  * H1 **확정** — 옵션 3개(`회계사용자(예외)`/`인사사용자(예외)`/`SCM-구매`), 기본 선택은
    `SCM-구매`. `UT_DROPDOWN_BOX_JS`→null, `UT_DISPLAY_JS`→'' 인데 위젯은 정상 렌더.
    `UT_OPTION_BOX_JS('SCM-구매')`→null(정규식 삽입 `target+'사용자'` 가 li `'SCM-구매 3'`
    과 매칭 불가).
  * H2 **반증** — li 3개 전부 visible·inViewport, 25px 등간격, 스크롤 없음.
  * H0 **확정** — `read_profile()` 이 패널을 연 채로 남기고, `open_user_panel()`(토글)이 그것을
    닫아 attempt 1 을 낭비.
  * → 재설계 반영 완료: `js_lib` 리더는 select(#ch_group) 기준 **kendo 위젯 역참조**(아래
    DIAG_DROPDOWN_LOCATOR_JS 의 원리)로 바뀌었고, `auth` 는 옵션 목록 기반 별칭 해석 +
    idempotent `open_user_panel` 을 쓴다. 이 프로브는 **재검증 도구로 유지**한다 — 리더 3종을
    다시 돌려 box/display 가 non-null 로 나오면 회복 확인.

⚠ 읽기 위주. 사용자유형 전환은 세션 컨텍스트 변경일 뿐 ERP 데이터 변경이 아니라 1회 실동작까지만
허용(미션 지시) — 저장/상신/F7 절대 금지.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/user_type_selector_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import async_playwright  # noqa: E402

from app.config import get_settings  # noqa: E402
from nbkit.browser.actions import mouse_click, safe_evaluate  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.omnisol.auth import (  # noqa: E402
    _wait_reload_after_apply,
    open_user_panel,
    read_current_user_type,
)
from nbkit.omnisol.modals import dismiss_notice_popup  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)


# ── 신규 진단 JS(이 프로브 전용 — js_lib.py 는 건드리지 않는다) ────────────────────

# 사용자 패널(.user-info-box) 자체가 열려있는지 — H0(패널 토글) 검증용.
USER_PANEL_STATE_JS = r"""() => {
  const box = document.querySelector('.user-info-box');
  if (!box) return { found: false };
  const r = box.getBoundingClientRect();
  return { found: true, visible: box.offsetParent !== null, rect: { x: r.x, y: r.y, width: r.width, height: r.height } };
}"""

# 페이지의 모든 select 전량 덤프 — id/name/class/selectedIndex/옵션 전부, USER_TYPE_READ_JS
# 탐색조건(옵션 중 '사용자' 포함)에 걸리는지.
DUMP_ALL_SELECTS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  return [...document.querySelectorAll('select')].map((s, i) => ({
    i,
    id: s.id || '',
    name: s.name || '',
    cls: (s.className || '').toString().slice(0, 150),
    selectedIndex: s.selectedIndex,
    visible: s.offsetParent !== null,
    matchesUserTypeReadCond: [...s.options].some(o => /사용자/.test(o.text || '')),
    options: [...s.options].map(o => ({ text: o.text, value: o.value })),
  }));
}"""

# 페이지의 모든 .k-dropdown 전량 덤프 — UT_DISPLAY_JS/UT_DROPDOWN_BOX_JS 가 왜 잡거나 못
# 잡는지 판별. ⚠ 사용자 패널이 실제로 열린 상태에서 호출해야 의미있는 rect 가 나온다
# (패널이 닫혀있으면 전부 offsetParent=null/rect 0 — 이 자체도 실측 사실로 함께 기록한다).
DUMP_K_DROPDOWNS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  return [...document.querySelectorAll('.k-dropdown')].map((d, i) => {
    const r = d.getBoundingClientRect();
    return {
      i,
      innerText: c(d.innerText).slice(0, 200),
      visible: d.offsetParent !== null,
      matchesUserTypeRegex: /사용자/.test(d.innerText || ''),
      rect: { x: r.x, y: r.y, width: r.width, height: r.height },
    };
  });
}"""

# 사용자유형 select(#ch_group 류 — 옵션 중 '사용자' 포함하는 select) 의 kendo 위젯
# wrapper(.k-dropdown) 좌표 — UT_DROPDOWN_BOX_JS 의 /사용자/ 텍스트 조건과 무관하게(현재
# 선택이 'SCM-구매' 라도) 신뢰성 있게 여는 진단용 로케이터. 패널이 열려있어야 유효한 rect.
DIAG_DROPDOWN_LOCATOR_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const sel = [...document.querySelectorAll('select')].find(s => [...s.options].some(o => /사용자/.test(o.text || '')));
  if (!sel) return { ok: false, reason: 'no-select' };
  let wrapEl = null, via = null;
  try {
    const w = window.jQuery ? window.jQuery(sel).data('kendoDropDownList') : null;
    if (w && w.wrapper && w.wrapper[0]) { wrapEl = w.wrapper[0]; via = 'kendo-widget'; }
  } catch (e) {}
  if (!wrapEl) {
    let node = sel.nextElementSibling;
    for (let i = 0; i < 5 && node; i++) {
      if (node.classList && node.classList.contains('k-dropdown')) { wrapEl = node; via = 'next-sibling'; break; }
      node = node.nextElementSibling;
    }
  }
  if (!wrapEl) {
    let anc = sel.parentElement;
    for (let i = 0; i < 5 && anc; i++) {
      const found = anc.querySelector('.k-dropdown');
      if (found) { wrapEl = found; via = 'ancestor-scan'; break; }
      anc = anc.parentElement;
    }
  }
  if (!wrapEl) return { ok: false, reason: 'no-wrapper', selectId: sel.id || '' };
  const r = wrapEl.getBoundingClientRect();
  return {
    ok: true, via, selectId: sel.id || '',
    wrapperCls: (wrapEl.className || '').toString().slice(0, 150),
    wrapperText: c(wrapEl.innerText).slice(0, 200),
    rect: { x: r.x, y: r.y, width: r.width, height: r.height },
    x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
  };
}"""

# 열린 드롭다운의 옵션 li 전량 덤프 — innerText/rect/offsetParent/뷰포트 내부여부 +
# 리스트 컨테이너 scrollHeight/clientHeight(스크롤 발생 여부).
DUMP_LI_OPTIONS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const vw = window.innerWidth, vh = window.innerHeight;
  const lis = [...document.querySelectorAll('li.k-item, .k-list li, ul[role=listbox] li')];
  const items = lis.map((li, i) => {
    const r = li.getBoundingClientRect();
    const visible = li.offsetParent !== null;
    const inViewport = visible && r.top >= 0 && r.left >= 0 && r.bottom <= vh && r.right <= vw;
    return {
      i,
      innerText: c(li.innerText),
      visible,
      rect: { x: r.x, y: r.y, width: r.width, height: r.height },
      inViewport,
    };
  });
  let containerInfo = null;
  if (lis.length) {
    const container = lis[0].closest('.k-list, ul[role=listbox]') || lis[0].parentElement;
    if (container) {
      containerInfo = {
        tag: container.tagName,
        cls: (container.className || '').toString().slice(0, 120),
        scrollHeight: container.scrollHeight,
        clientHeight: container.clientHeight,
        scrollTop: container.scrollTop,
        hasScroll: container.scrollHeight > container.clientHeight,
      };
    }
  }
  return { count: items.length, items, containerInfo };
}"""


class Timeline:
    """단계별 성공/실패 + 소요 ms 기록."""

    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, step: str, ok: bool, ms: int, detail=None) -> None:
        self.entries.append({"step": step, "ok": ok, "ms": ms, "detail": detail})
        status = "OK" if ok else "FAIL"
        print(f"[{status}] {step} ({ms}ms) {'' if detail is None else detail}", flush=True)


async def main() -> None:
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=0)
    page = await browser.new_page(viewport=selectors.VIEWPORT)
    base = get_settings().erp_base

    result: dict = {"userid": USERID, "base": base}
    tl = Timeline()

    async def shot(name: str) -> None:
        try:
            await page.screenshot(path=str(ARTIFACTS / f"user_type_probe_{name}.png"))
        except Exception:  # noqa: BLE001 — 스크린샷 실패는 프로브를 죽이지 않는다
            pass

    try:
        # ── 1) 로그인(재사용: ensure_logged_in — 프로덕션 기본값 그대로 read_profile_after=True) ──
        # ⚠ 이것이 실제 프로덕션 진입 순서다: login 노드가 ensure_logged_in 을 그대로 쓰고,
        # 그 안의 read_profile() 이 사용자 패널을 열고 **닫지 않은 채** 남긴다(H0 재현 전제).
        t0 = time.monotonic()
        await ensure_logged_in(page, USERID, PASSWORD, base)
        tl.record("login_and_profile_read", True, int((time.monotonic() - t0) * 1000))

        panel_after_login = await page.evaluate(USER_PANEL_STATE_JS)
        result["panel_state_after_login_profile_read"] = panel_after_login
        print(f"[H0] read_profile() 후 패널 상태: {panel_after_login!r}", flush=True)
        await shot("00_after_login")

        # ── 2) open_user_panel() 재사용 — switch_user_type() 이 실제로 첫 줄에서 부르는 호출 ──
        t0 = time.monotonic()
        await open_user_panel(page)
        panel_after_call1 = await page.evaluate(USER_PANEL_STATE_JS)
        ok1 = bool(panel_after_call1.get("visible"))
        tl.record(
            "open_user_panel_call1(switch_user_type 첫 줄과 동일)",
            ok1,
            int((time.monotonic() - t0) * 1000),
            f"panel_visible={ok1} (H0: 이미 열려있었다면 이 호출이 닫는다)",
        )
        result["panel_state_after_open_user_panel_call1"] = panel_after_call1
        await shot("01_after_open_user_panel_call1")

        # H0 확정: 이미 열려있던 패널을 닫았다면, switch_user_type() 의 attempt>1 재오픈과
        # 동일하게 한 번 더 열어 진짜 '패널 열림 + 드롭다운 접힘' 상태를 확보한다.
        if not ok1:
            t0 = time.monotonic()
            await open_user_panel(page)
            panel_after_call2 = await page.evaluate(USER_PANEL_STATE_JS)
            ok2 = bool(panel_after_call2.get("visible"))
            tl.record(
                "open_user_panel_call2(attempt>1 재오픈과 동일)",
                ok2,
                int((time.monotonic() - t0) * 1000),
                f"panel_visible={ok2}",
            )
            result["panel_state_after_open_user_panel_call2"] = panel_after_call2
            await shot("02_after_open_user_panel_call2")

        # ── 3) select 전량 덤프(패널이 진짜 열린 지금 상태에서) ────────────────────
        selects = await page.evaluate(DUMP_ALL_SELECTS_JS)
        result["all_selects"] = selects
        ut_selects = [s for s in selects if s["matchesUserTypeReadCond"]]
        print(f"[dump] select 총 {len(selects)}개, 사용자유형 후보 {len(ut_selects)}개", flush=True)
        for s in ut_selects:
            labels = [o["text"] for o in s["options"]]
            print(f"   id={s['id']!r} selectedIndex={s['selectedIndex']} options={labels!r}", flush=True)

        # ── 4) 리더 3종 실측값(패널 열림·드롭다운 접힘 상태 — switch_user_type 이 실제로 보는 상태) ──
        read_current = await safe_evaluate(page, js_lib.USER_TYPE_READ_JS, default="?")
        read_display = await safe_evaluate(page, js_lib.UT_DISPLAY_JS, default="")
        read_dropdown_box = await safe_evaluate(page, js_lib.UT_DROPDOWN_BOX_JS, default=None)
        result["readers_at_panel_open_dropdown_collapsed"] = {
            "USER_TYPE_READ_JS": read_current,
            "UT_DISPLAY_JS": read_display,
            "UT_DROPDOWN_BOX_JS": read_dropdown_box,
        }
        print(
            f"[readers] USER_TYPE_READ_JS={read_current!r} UT_DISPLAY_JS={read_display!r} "
            f"UT_DROPDOWN_BOX_JS={read_dropdown_box!r}",
            flush=True,
        )

        # ── 5) .k-dropdown 전량 덤프 ────────────────────────────────────────────
        kdropdowns = await page.evaluate(DUMP_K_DROPDOWNS_JS)
        result["k_dropdowns"] = kdropdowns
        print(f"[dump] .k-dropdown 총 {len(kdropdowns)}개", flush=True)
        for d in kdropdowns:
            print(
                f"   [{d['i']}] visible={d['visible']} matchesUserTypeRegex={d['matchesUserTypeRegex']} "
                f"text={d['innerText']!r} rect={d['rect']}",
                flush=True,
            )

        # ── 6) 드롭다운 열기(진단 로케이터 — /사용자/ 정규식과 무관하게 신뢰성 있는 좌표) ──
        diag_loc = await page.evaluate(DIAG_DROPDOWN_LOCATOR_JS)
        result["diag_dropdown_locator"] = diag_loc
        print(f"[diag] 드롭다운 로케이터: {diag_loc!r}", flush=True)

        open_coords = read_dropdown_box or (
            {"x": diag_loc["x"], "y": diag_loc["y"]} if diag_loc.get("ok") else None
        )
        li_dump: dict = {"count": 0, "items": [], "containerInfo": None}
        if open_coords:
            t0 = time.monotonic()
            await mouse_click(page, open_coords["x"], open_coords["y"])
            # li 렌더 폴링(최대 ~2s).
            for _ in range(10):
                await page.wait_for_timeout(200)
                li_dump = await page.evaluate(DUMP_LI_OPTIONS_JS)
                visible_count = sum(1 for it in li_dump["items"] if it["visible"])
                if visible_count > 0:
                    break
            visible_items = [it for it in li_dump["items"] if it["visible"]]
            ok = len(visible_items) > 0
            tl.record(
                "open_dropdown_and_dump_li",
                ok,
                int((time.monotonic() - t0) * 1000),
                f"coords_source={'UT_DROPDOWN_BOX_JS' if read_dropdown_box else 'diag_locator'} "
                f"total_li_in_dom={li_dump['count']} visible_li={len(visible_items)}",
            )
        else:
            tl.record("open_dropdown_and_dump_li", False, 0, "좌표 없음(UT_DROPDOWN_BOX_JS·진단 로케이터 모두 실패)")
        result["li_options"] = li_dump
        await shot("03_dropdown_open")
        visible_items = [it for it in li_dump["items"] if it["visible"]]
        print(f"[dump] li 전체 {li_dump['count']}개(DOM, 다른 위젯의 닫힌 목록 포함) 중 visible={len(visible_items)}개", flush=True)
        for it in visible_items:
            print(f"   li[{it['i']}] inViewport={it['inViewport']} rect={it['rect']} text={it['innerText']!r}", flush=True)
        if li_dump["containerInfo"]:
            print(f"[dump] 리스트 컨테이너: {li_dump['containerInfo']}", flush=True)

        # ── 7) UT_OPTION_BOX_JS('회계') / UT_OPTION_BOX_JS('SCM-구매') — H1/H2 판별 ──
        opt_gj = await safe_evaluate(page, js_lib.UT_OPTION_BOX_JS, "회계", default=None)
        opt_scm = await safe_evaluate(page, js_lib.UT_OPTION_BOX_JS, "SCM-구매", default=None)
        result["ut_option_box"] = {"회계": opt_gj, "SCM-구매": opt_scm}
        print(f"[readers] UT_OPTION_BOX_JS('회계')={opt_gj!r}  UT_OPTION_BOX_JS('SCM-구매')={opt_scm!r}", flush=True)

        # ── 8) 전환 실동작 1회: '회계' li 실클릭 → 표시 재독 → 변경적용 → reload → 재독 ──
        switch_tl: list[dict] = []

        def srecord(step: str, ok: bool, ms: int, detail=None) -> None:
            switch_tl.append({"step": step, "ok": ok, "ms": ms, "detail": detail})
            tl.record(f"switch.{step}", ok, ms, detail)

        gj_li = next(
            (it for it in visible_items if "회계" in it["innerText"] and "사용자" in it["innerText"]),
            None,
        )
        if not gj_li:
            srecord("click_gyeogye_li", False, 0, "visible li 목록에서 '회계사용자' 텍스트 요소를 못 찾음")
        else:
            r = gj_li["rect"]
            cx, cy = round(r["x"] + r["width"] / 2), round(r["y"] + r["height"] / 2)
            t0 = time.monotonic()
            await mouse_click(page, cx, cy)
            srecord("click_gyeogye_li", True, int((time.monotonic() - t0) * 1000), f"clicked=({cx},{cy}) text={gj_li['innerText']!r}")

            t0 = time.monotonic()
            disp_after_click = await safe_evaluate(page, js_lib.UT_DISPLAY_JS, default="")
            ok = "회계" in (disp_after_click or "")
            srecord("reread_UT_DISPLAY_JS", ok, int((time.monotonic() - t0) * 1000), f"value={disp_after_click!r}")
            result["display_after_li_click"] = disp_after_click
            await shot("04_after_li_click")

            t0 = time.monotonic()
            apply_box = await safe_evaluate(page, js_lib.UT_APPLY_BOX_JS, default=None)
            srecord("find_UT_APPLY_BOX_JS", bool(apply_box), int((time.monotonic() - t0) * 1000), f"box={apply_box!r}")

            if apply_box:
                await safe_evaluate(page, "() => { window.__nbUtApplyMark = true; return true; }", default=None)
                t0 = time.monotonic()
                await mouse_click(page, apply_box["x"], apply_box["y"])
                srecord("click_apply", True, int((time.monotonic() - t0) * 1000))
                await shot("05_after_apply_click")

                t0 = time.monotonic()
                await _wait_reload_after_apply(page)
                srecord("wait_reload", True, int((time.monotonic() - t0) * 1000))

                t0 = time.monotonic()
                await dismiss_notice_popup(page, appear_cap_ms=2_500)
                srecord("dismiss_notice_after_reload", True, int((time.monotonic() - t0) * 1000))

                t0 = time.monotonic()
                await open_user_panel(page)
                cur_final = await read_current_user_type(page)
                ok = "회계" in (cur_final or "")
                srecord("reread_USER_TYPE_READ_JS_final", ok, int((time.monotonic() - t0) * 1000), f"value={cur_final!r}")
                result["final_user_type"] = cur_final
                await shot("06_final_state")
            else:
                await shot("05_apply_box_not_found")

        result["switch_timeline"] = switch_tl
        result["timeline"] = tl.entries
        result["initial_user_type_before_switch"] = read_current

    except Exception as exc:  # noqa: BLE001 — 프로브라 전체 예외 기록.
        result["error"] = f"{type(exc).__name__}: {exc}"
        print(f"[error] {result['error']}", flush=True)
        await shot("99_error")
        result["timeline"] = tl.entries
    finally:
        out = ARTIFACTS / "user_type_selector_probe.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[done] → {out}", flush=True)
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
