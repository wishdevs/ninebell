"""읽기전용 프로브 — 로그인 직후 **계정별로 뜨는 창/팝업**의 정체를 확인한다.

배경(사용자 리포트 2026-07-27): 특정 계정(석대현)으로 로그인하면 **회사 홈페이지가 시스템
팝업으로** 뜬다. 지금의 공지 팝업 닫기(`dismiss_notice_popup`)는 **인페이지 레이어**(고유 앵커
`#close-today-chk`/`#notice-dialog-close`)만 다루므로, 이게 별도 브라우저 창(window.open)이면
전혀 다른 처리(자식 Page 닫기)가 필요하다. 그 구분을 실측한다.

수집(전부 읽기 전용):
  - `context.on("page")` 로 잡히는 **새 Page**(=시스템 팝업)의 URL·타이틀·opener 여부.
  - 메인 페이지의 보이는 `.k-window`/dialog 목록(=인페이지 모달).
  - 두 경우 모두 스크린샷.

⚠ 절대 안전: 로그인만 하고 아무 버튼도 누르지 않는다(저장·상신·삭제 없음). 자격증명은 **환경
   변수로만** 받는다(소스·아티팩트에 비밀번호를 남기지 않는다 — 아이디만 기록).

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    E2E_USERID='...' E2E_PASSWORD='...' .venv/bin/python e2e/login_popup_probe.py
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
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402

USERID = os.environ.get("E2E_USERID") or ""
PASSWORD = os.environ.get("E2E_PASSWORD") or ""
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
SETTLE_MS = int(os.environ.get("E2E_SETTLE_MS", "8000"))  # 로그인 후 관찰 시간(비동기 팝업 대기).

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
OUT = ARTIFACTS / "login_popup_probe.json"

# 메인 페이지의 보이는 다이얼로그/레이어 목록(클래스·id·텍스트 앞부분) — 인페이지 모달 판별용.
_DIALOGS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const out = [];
  const sels = ['.k-window', '.k-dialog', '[role=dialog]', '.modal', '.layer-popup'];
  const seen = new Set();
  for (const sel of sels) {
    for (const el of document.querySelectorAll(sel)) {
      if (el.offsetParent === null || seen.has(el)) continue;
      seen.add(el);
      const r = el.getBoundingClientRect();
      out.push({
        sel, id: el.id || null, cls: (el.className || '').toString().slice(0, 120),
        w: Math.round(r.width), h: Math.round(r.height), text: c(el.innerText).slice(0, 200),
      });
    }
  }
  return out;
}"""


async def main() -> int:
    if not USERID or not PASSWORD:
        print("E2E_USERID / E2E_PASSWORD 환경변수가 필요합니다(비밀번호는 소스에 두지 않는다).")
        return 2
    settings = get_settings()
    report: dict = {"userid": USERID, "erp_base": settings.erp_base, "settle_ms": SETTLE_MS}
    popups: list = []
    stamps: dict = {}  # id(page) → 로그인 완료 기준 상대 출현 시각(ms)
    t_login = {"done": None}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        ctx = await browser.new_context(viewport={"width": 1600, "height": 1000})
        # 로그인 **전에** 리스너를 건다 — 팝업이 로그인 도중/직후에 뜨므로 놓치면 안 된다.
        def _on_page(p):
            popups.append(p)
            base_t = t_login["done"]
            stamps[id(p)] = None if base_t is None else int((time.monotonic() - base_t) * 1000)

        ctx.on("page", _on_page)
        page = await ctx.new_page()
        try:
            t0 = time.monotonic()
            await ensure_logged_in(page, USERID, PASSWORD, settings.erp_base)
            t_login["done"] = time.monotonic()
            report["login_ms"] = int((t_login["done"] - t0) * 1000)
            print(f"[ok] 로그인 완료({report['login_ms']}ms) — 관찰 {SETTLE_MS}ms 시작")
            await page.wait_for_timeout(SETTLE_MS)  # 비동기 지연 팝업까지 관찰.

            extra = [p for p in popups if p is not page]
            report["popup_count"] = len(extra)
            report["popups"] = []
            for i, p in enumerate(extra):
                info = {
                    "index": i,
                    "closed": p.is_closed(),
                    "appeared_ms_after_login": stamps.get(id(p)),
                }
                if not p.is_closed():
                    try:
                        info["url"] = p.url
                        info["title"] = await p.title()
                        shot = ARTIFACTS / f"login_popup_{i}.png"
                        await p.screenshot(path=str(shot))
                        info["screenshot"] = str(shot)
                    except Exception as exc:  # noqa: BLE001 — 팝업이 곧바로 닫히는 경우 방어.
                        info["error"] = str(exc)[:160]
                report["popups"].append(info)
                print(
                    f"[popup {i}] closed={info['closed']} "
                    f"t={info['appeared_ms_after_login']}ms {info.get('url')} / {info.get('title')}"
                )

            report["main_url"] = page.url
            report["main_dialogs"] = await page.evaluate(_DIALOGS_JS)
            main_shot = ARTIFACTS / "login_popup_main.png"
            await page.screenshot(path=str(main_shot), full_page=False)
            report["main_screenshot"] = str(main_shot)
            print(f"[main] {page.url}")
            print(f"[main dialogs] {json.dumps(report['main_dialogs'], ensure_ascii=False)[:600]}")
        finally:
            await ctx.close()
            await browser.close()

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[artifact] {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
