"""HEADLESS 읽기전용(부작용 0) 프로브 — 구매발주 ❓1·❓2 최초 실측.

purchase_order(PROCESS.md D2·D3) 확인 대상:
  ❓1 — 이트라이브2 계정이 'SCM-구매' 사용자유형을 보유하는가, `ensure_user_type(page, "SCM")`
       (기존 인사/회계 전환 프리미티브) 로 전환 가능한가.
  ❓2 — '프로젝트BOM구매요청[나인벨]' 메뉴 후보(딥링크/사이드바 요소) DOM 스캔.

근거(사전 조사): `nbkit/omnisol/menu_schemas.py` 에 이미 `USER_TYPE_SCM = register_user_type("SCM")`
(→ 'SCM-구매', 2026-08-01 라이브 실측으로 확인된 3번째 유형)가 등록돼 있고,
`e2e/user_type_selector_probe.py` 실측 결론에 "이트라이브2 계정 기본 선택이 이미 SCM-구매"라는
기록이 있다 — 이 프로브가 그 사실을 **이 미션의 목적(메뉴 진입)으로 재확인**한다.

클릭 없음(사용자유형 전환의 실클릭 1회는 세션 컨텍스트 변경일 뿐 ERP 데이터 변경이 아니므로
허용 — user_type_selector_probe.py 선례와 동일 판단) + DOM 스캔만. 저장/적용/행 데이터 변경 없음.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/purchase_order_discover_probe.py
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
from nbkit.omnisol.auth import read_current_user_type  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

KEYWORDS = [
    "프로젝트BOM구매요청[나인벨]",
    "프로젝트BOM구매요청",
    "구매요청처리[나인벨]",
    "구매발주일괄입력[나인벨]",
    "구매관리",
    "SCM",
    "메뉴검색",
]

# voucher_receivable_discover_probe.py 의 SCAN_MENU_JS 그대로 재사용(가시성 무관 전량 스캔).
SCAN_MENU_JS = r"""(keywords) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const out = [];
  const seen = new Set();
  for (const kw of keywords) {
    const els = [...document.querySelectorAll('a,button,span,div,li,td,i,img,[role=menuitem],[role=treeitem]')]
      .filter(e => {
        const t = c(e.innerText || e.textContent || '');
        const title = c(e.getAttribute && e.getAttribute('title'));
        const alt = c(e.getAttribute && e.getAttribute('alt'));
        return (t === kw || title === kw || alt === kw || t.includes(kw));
      });
    for (const e of els) {
      if (seen.has(e)) continue;
      seen.add(e);
      const r = e.getBoundingClientRect();
      out.push({
        kw,
        tag: e.tagName,
        text: c(e.innerText || e.textContent || '').slice(0, 60),
        id: e.id || '',
        cls: (e.className || '').toString().slice(0, 120),
        href: e.getAttribute ? (e.getAttribute('href') || '') : '',
        dataAttrs: e.attributes ? [...e.attributes].filter(a => a.name.startsWith('data-')).map(a => `${a.name}=${a.value}`).slice(0, 8) : [],
        visible: e.offsetParent !== null,
        x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
        w: Math.round(r.width), h: Math.round(r.height),
      });
    }
  }
  return out;
}"""

SIDEBAR_ICONS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const cands = [...document.querySelectorAll('nav, aside, [class*=sidebar], [class*=gnb], [class*=lnb]')]
    .filter(e => e.offsetParent !== null);
  return cands.map(e => ({
    tag: e.tagName, cls: (e.className || '').toString().slice(0, 120),
    childCount: e.children.length,
    sampleText: c(e.innerText).slice(0, 200),
  }));
}"""

SEARCH_BOX_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const inputs = [...document.querySelectorAll('input')].filter(i => i.offsetParent !== null);
  return inputs.map(i => ({
    id: i.id || '', placeholder: i.placeholder || '', cls: (i.className||'').toString().slice(0,80),
  })).filter(i => /검색|search|메뉴/i.test(i.placeholder + i.id + i.cls));
}"""


async def _dump(name: str, data) -> None:
    path = ARTIFACTS / f"purchase_order_discover_{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[dump] {path}", flush=True)


async def _shot(page: Page, name: str) -> None:
    try:
        p = str(ARTIFACTS / f"purchase_order_discover_{name}.png")
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
        print("[entry] login…", flush=True)
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await _shot(page, "00_after_login")

        # ❓1 — SCM-구매 전환(기존 별칭 "SCM" → 'SCM-구매' 해석, 2026-08-01 실측 등록됨).
        print("[user_type] SCM 전환 시도…", flush=True)
        try:
            await ensure_user_type(page, "SCM")
            cur = await read_current_user_type(page)
            results["user_type_switch"] = {"ok": True, "current": cur}
            print(f"[user_type] 전환 성공 — 현재 유형={cur!r}", flush=True)
        except Exception as exc:  # noqa: BLE001
            results["user_type_switch"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            print(f"[user_type] 전환 실패: {exc!r}", flush=True)
        await _shot(page, "01_after_user_type")

        # ❓2 — 메뉴 후보 DOM 스캔(클릭 없음).
        scan = await page.evaluate(SCAN_MENU_JS, KEYWORDS)
        results["scan"] = scan
        print(f"[scan] {len(scan)}개 후보:", flush=True)
        for s in scan:
            print(
                f"   - kw={s['kw']!r} tag={s['tag']} text={s['text']!r} visible={s['visible']} "
                f"href={s['href']!r} @({s['x']},{s['y']}) data={s['dataAttrs']}",
                flush=True,
            )

        sidebar = await page.evaluate(SIDEBAR_ICONS_JS)
        results["sidebar_candidates"] = sidebar
        print(f"[sidebar] {len(sidebar)}개 컨테이너 후보", flush=True)

        search_box = await page.evaluate(SEARCH_BOX_JS)
        results["search_box"] = search_box
        print(f"[search_box] {search_box}", flush=True)

        results["landing_url"] = raw_page.url
        print(f"[landing_url] {raw_page.url}", flush=True)

        await _dump("results", results)
        print("\n===== DISCOVER COMPLETE (클릭=사용자유형 전환 1회만, 나머지 부작용 0) =====", flush=True)

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
