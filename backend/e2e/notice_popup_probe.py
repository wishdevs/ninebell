"""HEADLESS(headed) 읽기전용 프로브 — 로그인 직후 공지 레이어 팝업 실측.

⚠ 안전 규칙: 저장/삭제/상신 없음. 팝업의 "하루동안 보지 않기" 체크 + "닫기" 클릭만
(사용자 스크린샷에 나온 정상 조작) 수행. 다른 쓰기 액션 없음.

⚠ 동시성 주의: 같은 테스트 계정(이트라이브2)으로 다른 스모크가 동시에 돌고 있을 수 있다.
세션 강제종료·중복로그인 경고가 감지되면 즉시 중단하고 그 사실을 결과 JSON 에 기록한다.

목적:
  1. 로그인 직후(user_type 전환 전/후) 공지 팝업이 뜨는지 확인.
  2. DOM 전량 스캔으로 컨테이너 종류(.k-window vs 커스텀)·체크박스 셀렉터·닫기버튼 셀렉터/좌표 확정.
  3. 체크→닫기 시퀀스 후 재출현 여부(user_type 전환 reload, 메뉴 진입) 확인.
  4. 화면 blocking 여부(팝업 뒤 요소를 elementFromPoint 로 가로막는지).

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/notice_popup_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import async_playwright  # noqa: E402

from app.config import get_settings  # noqa: E402
from nbkit.browser.detection import is_authenticated  # noqa: E402
from nbkit.omnisol import selectors  # noqa: E402
from nbkit.omnisol.menu_schemas import EXPENSE_CARD  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "0") != "0"  # 기본 headed(사용자 요청)
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

# ── 신규 작성(공지팝업 고유) — 부작용 없는 발견용 JS ────────────────────────────
# 1차 실측(2026-07-21 run1): 광범위 '공지' 텍스트 매칭은 포털 홈 위젯(공지사항 링크 등)까지
# 오탐지해 잘못된 root 를 골랐다. 실제 팝업은 기존 selectors.DIALOG(".k-window.dialog") 와
# 동일 클래스("k-widget k-window k-window-titleless dialog")였다 — 그래서 **더 좁힌** 필터
# (텍스트에 '공지' AND '닫기' AND '하루' 동시 포함)로 재정의. 그래도 못 찾으면 selectors.DIALOG
# 셀렉터 자체로 폴백(아래 main() 참조).
NOTICE_ROOTS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const all = [...document.querySelectorAll('body *')];
  const cands = all.filter(el => {
    if (el.offsetParent === null) return false;
    const txt = c(el.innerText || '');
    return txt.includes('공지') && txt.includes('닫기') && txt.includes('하루') && txt.length < 4000;
  });
  const roots = cands.filter(el => !cands.some(other => other !== el && other.contains(el)));
  return roots.map(el => {
    const r = el.getBoundingClientRect();
    return {
      tag: el.tagName, id: el.id || null,
      cls: el.className && typeof el.className === 'string' ? el.className : null,
      rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
      text: c(el.innerText).slice(0, 300),
    };
  });
}"""

# roots 중 하나(css selector 나 좌표로 특정 못 하니 index 로)를 골라 그 안의 상세 구조를 덤프.
# root 는 매번 새로 쿼리(참조 유지 불가) — 동일 로직으로 재탐색 후 index 로 선택.
NOTICE_DETAIL_JS = r"""(idx) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const all = [...document.querySelectorAll('body *')];
  const cands = all.filter(el => {
    if (el.offsetParent === null) return false;
    const txt = c(el.innerText || '');
    return txt.includes('공지') && txt.includes('닫기') && txt.includes('하루') && txt.length < 4000;
  });
  const roots = cands.filter(el => !cands.some(other => other !== el && other.contains(el)));
  const root = roots[idx];
  if (!root) return null;

  const describe = (el) => {
    const r = el.getBoundingClientRect();
    return {
      tag: el.tagName, id: el.id || null, name: el.getAttribute('name'),
      type: el.getAttribute('type'),
      cls: el.className && typeof el.className === 'string' ? el.className : null,
      text: c(el.innerText || el.value || '').slice(0, 60),
      rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
      checked: el.checked === undefined ? null : el.checked,
    };
  };

  const checkboxes = [...root.querySelectorAll('input[type=checkbox]')].map(describe);
  const buttons = [...root.querySelectorAll('button, a, [role=button], .btn, input[type=button]')]
    .filter(b => b.offsetParent !== null).map(describe);
  const tabs = [...root.querySelectorAll('[role=tab], .tab, li a, .nav-item, .k-tabstrip-items li')]
    .filter(t => t.offsetParent !== null).map(describe);
  const labels = [...root.querySelectorAll('label')].map(l => ({
    text: c(l.innerText).slice(0, 40),
    forAttr: l.getAttribute('for'),
    htmlFor_checkbox_inside: !!l.querySelector('input[type=checkbox]'),
  }));

  return {
    root: describe(root),
    outerHTML_snippet: root.outerHTML.slice(0, 6000),
    checkboxes, buttons, tabs, labels,
    computedStyle: (() => {
      const s = getComputedStyle(root);
      return { position: s.position, zIndex: s.zIndex, display: s.display };
    })(),
  };
}"""

# 팝업이 화면을 막는지: 뷰포트 여러 지점에서 elementFromPoint 최상위 요소가 팝업(공지 텍스트
# 포함 조상) 내부인지, 아니면 별도 k-overlay 백드롭에 막히는지 확인.
BLOCKING_CHECK_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const all = [...document.querySelectorAll('body *')];
  const cands = all.filter(el => {
    if (el.offsetParent === null) return false;
    const txt = c(el.innerText || '');
    return txt.includes('공지') && txt.includes('닫기') && txt.includes('하루') && txt.length < 4000;
  });
  const roots = cands.filter(el => !cands.some(other => other !== el && other.contains(el)));
  const pts = [
    [200, 200], [800, 100], [100, 500], [1400, 500], [800, 900],
  ];
  return pts.map(([x, y]) => {
    const top = document.elementFromPoint(x, y);
    const blockedByNotice = roots.some(r => r.contains(top));
    const blockedByOverlay = !!(top && typeof top.className === 'string' && top.className.includes('k-overlay'));
    return {
      x, y, topTag: top ? top.tagName : null,
      topCls: top && typeof top.className === 'string' ? top.className.slice(0, 60) : null,
      blockedByNotice, blockedByOverlay,
    };
  });
}"""

STORAGE_SCAN_JS = r"""() => {
  const grep = (store) => {
    const out = {};
    try {
      for (let i = 0; i < store.length; i++) {
        const k = store.key(i);
        if (/notice|popup|팝업|공지|day|dontshow|hide/i.test(k)) out[k] = store.getItem(k);
      }
    } catch (e) { out.__error = String(e); }
    return out;
  };
  return {
    localStorage: grep(window.localStorage),
    sessionStorage: grep(window.sessionStorage),
    cookies: document.cookie,
  };
}"""


async def _shot(page, name: str) -> str:
    p = ARTIFACTS / f"notice_{name}.png"
    try:
        await page.screenshot(path=str(p))
        print(f"[shot] {p}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[shot] skipped {name}: {exc!r}", flush=True)
    return str(p)


def _dump(name: str, data) -> str:
    p = ARTIFACTS / f"notice_{name}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[dump] {p}", flush=True)
    return str(p)


async def scan_notice(page) -> list[dict]:
    return await page.evaluate(NOTICE_ROOTS_JS) or []


async def main() -> None:
    results: dict = {"userid": USERID, "headless": HEADLESS}
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=0)
    page = await browser.new_page(viewport=selectors.VIEWPORT)
    base = get_settings().erp_base

    try:
        # ── 1) 로그인 직후(user_type 전환 전) ────────────────────────────────
        print("[entry] login…", flush=True)
        await ensure_logged_in(page, USERID, PASSWORD, base)
        if not await is_authenticated(page, login_selector=selectors.LOGIN_USERID):
            results["concurrency_alert"] = "로그인 직후 인증 판정 실패(세션 경합 의심)"
            print("[ALERT] 로그인 후 미인증 상태 — 세션 경합 의심, 중단", flush=True)
            _dump("results", results)
            return

        await page.wait_for_timeout(1500)  # 공지 API 비동기 렌더 대비(고정 관찰창)
        await _shot(page, "01_after_login")
        roots_a = await scan_notice(page)
        results["stage_after_login"] = {"roots_found": len(roots_a), "roots": roots_a}
        print(f"[after_login] notice roots={len(roots_a)}", flush=True)

        if not roots_a:
            dialog_present = await page.evaluate(
                "(sel) => !!document.querySelector(sel)", selectors.DIALOG
            )
            results["dialog_selector_fallback_check"] = dialog_present
            if dialog_present:
                print(
                    "[WARN] 텍스트 필터(공지/닫기/하루) 로는 못 찾았지만 selectors.DIALOG"
                    f"({selectors.DIALOG}) 는 존재 — 문구가 다를 수 있음. 계속 진행 못 함(수동 확인 필요).",
                    flush=True,
                )
            print(
                "[INFO] 로그인 직후 공지 팝업 미출현 — '하루동안 보지 않기'가 오늘자로 이미 "
                "설정돼 있을 가능성. storage/cookie 스캔으로 확인.",
                flush=True,
            )
            storage = await page.evaluate(STORAGE_SCAN_JS)
            results["storage_scan_no_popup"] = storage
            _dump("results", results)
            print(json.dumps(storage, ensure_ascii=False, indent=2), flush=True)
            return

        # ── 2) 상세 DOM 덤프(첫 번째 root 기준) ──────────────────────────────
        detail = await page.evaluate(NOTICE_DETAIL_JS, 0)
        results["detail"] = detail
        _dump("detail_after_login", detail)
        print(json.dumps(detail, ensure_ascii=False, indent=2)[:3000], flush=True)

        # k-window 여부(기존 dismiss_blocking_modals 커버 대상인지)
        kwindow_present = await page.evaluate(
            "(sel) => !!document.querySelector(sel)", selectors.KWINDOW
        )
        root_is_kwindow = bool(detail and detail["root"].get("cls") and "k-window" in (detail["root"]["cls"] or ""))
        results["container_kind"] = {
            "root_class": detail["root"]["cls"] if detail else None,
            "any_kwindow_on_page": kwindow_present,
            "root_is_kwindow": root_is_kwindow,
        }

        # ── 3) blocking 여부(닫기 전에 측정) ────────────────────────────────
        blocking = await page.evaluate(BLOCKING_CHECK_JS)
        results["blocking_check"] = blocking
        print(f"[blocking] {blocking}", flush=True)

        # ── 4) storage 스캔(닫기 전) ─────────────────────────────────────────
        storage_before = await page.evaluate(STORAGE_SCAN_JS)
        results["storage_before_close"] = storage_before

        # ── 5) 체크박스 체크 + 닫기 클릭(실좌표 클릭) ────────────────────────
        cbs = (detail or {}).get("checkboxes") or []
        target_cb = None
        for cb in cbs:
            if not cb.get("checked"):
                target_cb = cb
                break
        if not target_cb and cbs:
            target_cb = cbs[0]
        results["checkbox_chosen"] = target_cb

        if target_cb:
            r = target_cb["rect"]
            cx, cy = r["x"] + r["w"] / 2, r["y"] + r["h"] / 2
            print(f"[action] 체크박스 실클릭 @ ({cx},{cy})", flush=True)
            await page.mouse.click(cx, cy)
            await page.wait_for_timeout(400)
            await _shot(page, "02_after_checkbox")
            detail2 = await page.evaluate(NOTICE_DETAIL_JS, 0)
            results["checkbox_state_after_click"] = (
                next((c for c in (detail2 or {}).get("checkboxes") or [] if c["rect"] == r), None)
            )
        else:
            print("[WARN] 체크박스를 찾지 못함", flush=True)

        buttons = (detail or {}).get("buttons") or []
        close_btn = next((b for b in buttons if b.get("text") == "닫기"), None)
        if not close_btn:
            close_btn = next((b for b in buttons if "닫기" in (b.get("text") or "")), None)
        results["close_button_chosen"] = close_btn

        if close_btn:
            r = close_btn["rect"]
            cx, cy = r["x"] + r["w"] / 2, r["y"] + r["h"] / 2
            print(f"[action] 닫기 버튼 실클릭 @ ({cx},{cy})", flush=True)
            await page.mouse.click(cx, cy)
        else:
            print("[WARN] '닫기' 버튼을 텍스트로 못 찾음 — X 버튼 좌표 폴백 시도", flush=True)
            # X 버튼 후보: root 내 close/icon 클래스 또는 root 우상단 근처 작은 클릭가능 요소
            x_candidates = [b for b in buttons if any(
                k in (b.get("cls") or "").lower() for k in ("close", "x-btn", "icon-close")
            )]
            results["x_button_candidates"] = x_candidates
            if x_candidates:
                r = x_candidates[0]["rect"]
                cx, cy = r["x"] + r["w"] / 2, r["y"] + r["h"] / 2
                await page.mouse.click(cx, cy)

        await page.wait_for_timeout(800)
        await _shot(page, "03_after_close")
        roots_after_close = await scan_notice(page)
        results["roots_after_close"] = len(roots_after_close)
        print(f"[after_close] notice roots={len(roots_after_close)}", flush=True)

        storage_after = await page.evaluate(STORAGE_SCAN_JS)
        results["storage_after_close"] = storage_after

        # ── 6) user_type 전환(reload 유발) 후 재출현 확인 ────────────────────
        if not await is_authenticated(page, login_selector=selectors.LOGIN_USERID):
            results["concurrency_alert_before_usertype"] = "닫기 이후 미인증 — 세션 경합 의심"
            print("[ALERT] 닫기 이후 미인증 상태 — 세션 경합 의심, 중단", flush=True)
            _dump("results", results)
            return

        print("[stage] user_type(회계) 전환…", flush=True)
        try:
            await ensure_user_type(page, "회계")
        except Exception as exc:  # noqa: BLE001
            results["user_type_error"] = repr(exc)
            print(f"[WARN] user_type 전환 실패(무시하고 진행): {exc!r}", flush=True)

        await page.wait_for_timeout(1000)
        await _shot(page, "04_after_usertype_switch")
        roots_after_ut = await scan_notice(page)
        results["roots_after_usertype_switch"] = len(roots_after_ut)
        print(f"[after_usertype] notice roots={len(roots_after_ut)}", flush=True)

        # ── 7) 메뉴 진입 후 재출현 확인 ───────────────────────────────────────
        if not await is_authenticated(page, login_selector=selectors.LOGIN_USERID):
            results["concurrency_alert_before_menu"] = "user_type 전환 이후 미인증 — 세션 경합 의심"
            print("[ALERT] user_type 전환 이후 미인증 — 세션 경합 의심, 중단", flush=True)
            _dump("results", results)
            return

        print("[stage] 메뉴 진입(GLDDOC00300)…", flush=True)
        try:
            await navigate_schema(page, EXPENSE_CARD, base)
        except Exception as exc:  # noqa: BLE001
            results["menu_nav_error"] = repr(exc)
            print(f"[WARN] 메뉴 진입 실패(무시하고 진행): {exc!r}", flush=True)

        await page.wait_for_timeout(1000)
        await _shot(page, "05_after_menu_nav")
        roots_after_menu = await scan_notice(page)
        results["roots_after_menu_nav"] = len(roots_after_menu)
        print(f"[after_menu_nav] notice roots={len(roots_after_menu)}", flush=True)

        _dump("results", results)
        print("\n===== SUMMARY =====", flush=True)
        print(json.dumps(results, ensure_ascii=False, indent=2)[:4000], flush=True)

    finally:
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
