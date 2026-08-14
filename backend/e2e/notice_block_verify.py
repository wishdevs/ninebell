"""공지 시스템 팝업 **차단 기능** 실화면 검증 — 대조군(차단 없음) vs 실험군(차단 설치).

PR #3 에서 미검증으로 남긴 부분을 확인한다: `block_notice_popups(context)` 를 깔면 공지창이
**정말 열리지 않는가**. 로그인 구간에 도착하는 모든 새 Page 를 기록해 두 조건을 비교한다.

⚠ 결제창 보호는 이 프로브로 검증되지 않는다(결재 순회를 하지 않으므로). 여기서 보는 것은
   '공지창이 열리는가'뿐이다.

⚠ 완전 읽기전용 — 로그인만 하고 끝낸다. 메뉴 진입·조회·저장 없음.

Usage:
    cd <repo>/backend
    .venv/bin/python e2e/notice_block_verify.py       # 자격증명은 .env(E2E_USERID/E2E_PASSWORD)
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
from nbkit.browser.popups import install_notice_autoclose, is_notice_window  # noqa: E402
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
OUT = ARTIFACTS / "notice_block_verify.json"


async def _run_once(pw, base: str, *, block: bool) -> dict:
    """한 조건으로 로그인하고, 그 사이 **도착한 모든 창**을 기록한다."""
    browser = await pw.chromium.launch(headless=HEADLESS)
    ctx = await browser.new_context(viewport=LIVE_VIEWPORT)
    arrivals: list[str] = []

    # 도착 즉시 URL 을 남긴다 — 로그인 플로우의 PopupWatcher 가 닫아버려도 '열렸다'는 사실은 남는다.
    def _on_page(p) -> None:
        async def _rec() -> None:
            for _ in range(15):  # about:blank → 목적지 URL 확정 대기.
                u = p.url or ""
                if u and not u.startswith("about:"):
                    arrivals.append(u)
                    return
                await asyncio.sleep(0.1)
            arrivals.append(p.url or "(url 미확정)")

        try:
            asyncio.create_task(_rec())
        except RuntimeError:
            pass

    ctx.on("page", _on_page)
    installed = False
    if block:
        install_notice_autoclose(ctx)
        installed = True
    page = await ctx.new_page()
    try:
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await page.wait_for_timeout(SETTLE_MS)  # 비동기로 늦게 뜨는 창까지 관찰.
    finally:
        # 살아남은(닫히지 않은) 공지창 — 자동닫기가 동작하면 0 이어야 한다.
        alive = []
        for pg in list(ctx.pages):
            try:
                if not pg.is_closed() and is_notice_window(pg.url or ""):
                    alive.append(pg.url)
            except Exception:  # noqa: BLE001
                pass
        result = {
            "block": block,
            "block_installed": installed,
            "arrivals": arrivals,
            "notice_arrivals": [u for u in arrivals if is_notice_window(u)],
            "notice_alive": alive,
        }
        await ctx.close()
        await browser.close()
    return result


async def main() -> int:
    if not (USERID and PASSWORD):
        print("E2E_USERID / E2E_PASSWORD 를 .env 에 채우고 실행하세요.", file=sys.stderr)
        return 2
    base = get_settings().erp_base
    report: dict = {"erp_base": base, "userid": USERID}
    async with async_playwright() as pw:
        print("[1/2] 대조군 — 차단 없이 로그인…", flush=True)
        report["control"] = await _run_once(pw, base, block=False)
        print("[2/2] 실험군 — 차단 설치 후 로그인…", flush=True)
        report["blocked"] = await _run_once(pw, base, block=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    ctl, blk = report["control"], report["blocked"]
    print(f"\n결과 — {OUT}")
    print(f"  대조군(차단 없음): 창 {len(ctl['arrivals'])}개 / 공지창 {len(ctl['notice_arrivals'])}개")
    for u in ctl["arrivals"]:
        print(f"    - {u[:120]}")
    print(f"  실험군(차단 설치={blk['block_installed']}): 창 {len(blk['arrivals'])}개 / 공지창 {len(blk['notice_arrivals'])}개")
    for u in blk["arrivals"]:
        print(f"    - {u[:120]}")
    print(f"\n  대조군 살아남은 공지창: {ctl.get('notice_alive')}")
    print(f"  실험군 살아남은 공지창: {blk.get('notice_alive')}")
    if not ctl["notice_arrivals"]:
        print("\n판정: ⚠ 판단 불가 — 대조군에도 공지창이 뜨지 않아 비교가 성립하지 않는다.")
    elif not blk.get("notice_alive"):
        print("\n판정: ✅ 무시 동작 — 공지창이 열려도 즉시 닫혀 남지 않는다.")
    else:
        print("\n판정: ❌ 실패 — 실험군에 공지창이 살아남았다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
