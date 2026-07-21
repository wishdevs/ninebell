"""HEADLESS 읽기전용(부작용 0) 프로브 — 총계정원장>전표관리>전표조회승인 **menu_id/deeplink 발견**.

voucher_receivable(PROCESS.md D1) menu_id 는 아직 미확정(❓) — GLDDOC00300 처럼 알려진 딥링크가
없다. 이 스크립트는 클릭조차 하지 않고 **좌측 사이드바/GNB DOM 구조를 전량 덤프**해 "총계정원장"
"전표관리" "전표조회승인" 텍스트를 가진 요소와 그 좌표/속성(href/data-*)을 찾는다. 딥링크 후보가
안 보이면 다음 프로브에서 아이콘 사이드바 플라이아웃을 클릭해 실제 URL 전이를 관찰한다
(OMNISOL_NOTES.md §9 폴백 절차).

⚠ 안전: 클릭 없음(순수 텍스트/속성 스캔) — 부작용 0.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/voucher_receivable_discover_probe.py
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
from nbkit.omnisol import selectors  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

KEYWORDS = ["총계정원장", "전표관리", "전표조회승인", "전표조회", "전표", "GNB", "메뉴검색"]

# 지정 키워드를 텍스트/title/alt 로 가진 보이거나 숨겨진(사이드바 접힘 포함) 요소 전량 스캔.
# 옴니솔 사이드바 플라이아웃은 접혀 있어도 DOM 엔 존재할 수 있어(org_probe 선례) 가시성
# 필터를 걸지 않고 태그/텍스트/속성/좌표(0,0 이면 숨김 추정)까지 함께 반환한다.
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
        return (t === kw || title === kw || alt === kw);
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

# 좌측 아이콘 사이드바 전체 후보(제목·텍스트 없이 아이콘만 있는 1뎁스 메뉴들도 좌표 확보).
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

# 검색형 메뉴 입력(돋보기/메뉴검색) 후보.
SEARCH_BOX_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const inputs = [...document.querySelectorAll('input')].filter(i => i.offsetParent !== null);
  return inputs.map(i => ({
    id: i.id || '', placeholder: i.placeholder || '', cls: (i.className||'').toString().slice(0,80),
  })).filter(i => /검색|search|메뉴/i.test(i.placeholder + i.id + i.cls));
}"""


async def _dump(name: str, data) -> None:
    path = ARTIFACTS / f"voucher_receivable_discover_{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[dump] {path}", flush=True)


async def _shot(page: Page, name: str) -> None:
    try:
        p = str(ARTIFACTS / f"voucher_receivable_discover_{name}.png")
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
        print("[entry] login + user_type(회계)…", flush=True)
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await ensure_user_type(page, "회계")
        await page.wait_for_timeout(1_500)
        await _shot(page, "landing")

        scan = await page.evaluate(SCAN_MENU_JS, KEYWORDS)
        results["scan"] = scan
        print(f"[scan] {len(scan)}개 후보:", flush=True)
        for s in scan:
            print(f"   - kw={s['kw']!r} tag={s['tag']} text={s['text']!r} visible={s['visible']} "
                  f"href={s['href']!r} @({s['x']},{s['y']}) data={s['dataAttrs']}", flush=True)

        sidebar = await page.evaluate(SIDEBAR_ICONS_JS)
        results["sidebar_candidates"] = sidebar
        print(f"[sidebar] {len(sidebar)}개 컨테이너 후보", flush=True)

        search_box = await page.evaluate(SEARCH_BOX_JS)
        results["search_box"] = search_box
        print(f"[search_box] {search_box}", flush=True)

        # 현재 URL(랜딩) 기록 — 이후 클릭 프로브에서 전이 diff 참고용.
        results["landing_url"] = raw_page.url
        print(f"[landing_url] {raw_page.url}", flush=True)

        await _dump("results", results)
        print("\n===== DISCOVER COMPLETE (클릭 없음, 부작용 0) =====", flush=True)

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
