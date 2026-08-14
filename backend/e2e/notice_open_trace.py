"""공지창이 **어떻게 열리는지** 추적 — window.open 호출 인자/스택을 그대로 기록한다.

`notice_block_verify.py` 결과: 차단 스크립트를 깔아도 공지창이 떴다. 원인 후보는
  (1) open 시점 url 에 공지 마커가 없다(빈 url·베이스 url 로 열고 나중에 location/hash 를 채움),
  (2) window.open 경로가 아니다(a[target=_blank] 클릭, form target 등),
  (3) 우리 스크립트가 그 문서에 설치되기 전에 호출된다.
이 프로브는 (1)/(2)/(3) 을 가르기 위해 **모든 open 호출을 통과시키면서 인자만 기록**한다.

⚠ 완전 읽기전용(로그인만). 차단하지 않으므로 화면 동작에 영향 없음.

Usage:
    cd <repo>/backend && .venv/bin/python e2e/notice_open_trace.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.async_api import async_playwright  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(errors="ignore").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))

USERID = os.environ.get("E2E_USERID") or ""
PASSWORD = os.environ.get("E2E_PASSWORD") or ""
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
SETTLE_MS = int(os.environ.get("E2E_SETTLE_MS", "8000"))

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
OUT = ARTIFACTS / "notice_open_trace.json"

# 통과시키되 기록만 하는 계측 스크립트 — 문서 로드 전(add_init_script)에 설치된다.
TRACE_JS = r"""() => {
  try {
    if (window.__openTraceInstalled) return;
    window.__openTraceInstalled = true;
    window.__openCalls = [];
    var native = window.open;
    window.open = function (url, name, features) {
      var rec = {
        url: String(url == null ? '(undefined)' : url),
        name: String(name == null ? '' : name),
        features: String(features == null ? '' : features),
        href: location.href,
        t: Date.now(),
      };
      try { rec.stack = String(new Error().stack || '').split('\n').slice(1, 6).join(' | '); }
      catch (e) { rec.stack = '(stack 없음)'; }
      window.__openCalls.push(rec);
      return native.apply(window, arguments);
    };
    // target=_blank 앵커 클릭도 별도 창을 만든다 — 그 경로인지 함께 본다.
    document.addEventListener('click', function (ev) {
      try {
        var a = ev.target && ev.target.closest ? ev.target.closest('a[target]') : null;
        if (a && a.target && a.target !== '_self') {
          window.__openCalls.push({ url: String(a.href || ''), name: '(anchor)',
            features: 'target=' + a.target, href: location.href, t: Date.now() });
        }
      } catch (e) {}
    }, true);
  } catch (e) {}
}"""


async def main() -> int:
    if not (USERID and PASSWORD):
        print("E2E_USERID / E2E_PASSWORD 를 .env 에 채우고 실행하세요.", file=sys.stderr)
        return 2
    base = get_settings().erp_base
    report: dict = {"erp_base": base}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        ctx = await browser.new_context(viewport=LIVE_VIEWPORT)
        await ctx.add_init_script(TRACE_JS)
        seen: list[dict] = []

        def _on_page(p) -> None:
            async def _rec() -> None:
                for _ in range(15):
                    u = p.url or ""
                    if u and not u.startswith("about:"):
                        seen.append({"url": u, "opener_known": True})
                        return
                    await asyncio.sleep(0.1)
                seen.append({"url": p.url or "(미확정)", "opener_known": True})

            try:
                asyncio.create_task(_rec())
            except RuntimeError:
                pass

        ctx.on("page", _on_page)
        page = await ctx.new_page()
        try:
            await ensure_logged_in(page, USERID, PASSWORD, base)
            await page.wait_for_timeout(SETTLE_MS)
            # 메인 페이지 + 남아있는 모든 페이지에서 호출 기록을 회수한다.
            calls: list[dict] = []
            frames_scanned = 0
            for p in list(ctx.pages):
                # ⚠ 최상위 문서만 읽으면 **iframe 안에서 부른 open 을 통째로 놓친다**(ERP SPA 는
                #   모듈을 iframe 에 얹는 경우가 많다). 모든 프레임을 훑는다.
                for fr in list(p.frames):
                    frames_scanned += 1
                    try:
                        got = await fr.evaluate("() => window.__openCalls || []")
                        for c in got or []:
                            c["from_page"] = p.url
                            c["from_frame"] = fr.url
                            calls.append(c)
                    except Exception as exc:  # noqa: BLE001 — 닫힌/교차출처 프레임은 건너뛴다.
                        calls.append({"error": str(exc)[:120], "from_frame": fr.url})
            report["open_calls"] = calls
            report["frames_scanned"] = frames_scanned
            report["frame_urls"] = [fr.url for p in list(ctx.pages) for fr in list(p.frames)]
            # 도착한 창에 opener 가 있는가 — 있으면 window.open/target=_blank 계열, 없으면 다른 축.
            openers = []
            for p in list(ctx.pages):
                try:
                    op = await p.opener()
                    openers.append({"url": p.url, "opener": (op.url if op else None)})
                except Exception as exc:  # noqa: BLE001
                    openers.append({"url": getattr(p, "url", "?"), "opener_error": str(exc)[:100]})
            report["openers"] = openers
            report["arrived_pages"] = seen
        finally:
            OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            await ctx.close()
            await browser.close()

    print(f"결과 — {OUT}\n")
    print(f"도착한 창 {len(report.get('arrived_pages') or [])}개:")
    for s in report.get("arrived_pages") or []:
        print(f"  - {s['url'][:130]}")
    calls = report.get("open_calls") or []
    print(f"\n기록된 window.open/anchor 호출 {len(calls)}건:")
    for c in calls:
        if c.get("error"):
            print(f"  - (회수 실패) {c['error']}")
            continue
        print(f"  - url={c.get('url')[:110]!r} name={c.get('name')!r} features={c.get('features')[:40]!r}")
        print(f"      호출한 문서: {str(c.get('href'))[:90]}")
        print(f"      stack: {str(c.get('stack'))[:160]}")
    if not calls:
        print("  (없음) → window.open 경로가 아니거나, 스크립트 설치 전에 호출됐다.")
    print(f"\n훑은 프레임 {report.get('frames_scanned')}개:")
    for u in (report.get("frame_urls") or [])[:12]:
        print(f"  - {str(u)[:120]}")
    print("\n창별 opener(있으면 open/target 계열, None 이면 다른 축):")
    for o in report.get("openers") or []:
        print(f"  - {str(o.get('url'))[:100]}\n      opener={str(o.get('opener'))[:100]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
