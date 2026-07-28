"""진입 구간(로그인 → 사용자유형 → 메뉴) 단계별 소요 실측 — 재고 나서 손댄다.

사용자가 체감하는 '로그인 속도'는 `ensure_logged_in` 하나가 아니라 에이전트가 화면에 도달하기
까지다: login → user_type(회계) → menu_nav. 각 단계와, 그 안에서 **공지 레이어 팝업을 기다리는
시간**을 따로 잰다(같은 팝업을 여러 단계가 각자 기다리는 중복이 있는지 보려는 것).

⚠ 완전 읽기전용 — 조회(F2)도 누르지 않는다.

Usage:
    cd <repo>/backend && .venv/bin/python e2e/login_timing_probe.py
    E2E_RUNS=3 .venv/bin/python e2e/login_timing_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.async_api import async_playwright  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT  # noqa: E402
from nbkit.omnisol import auth as _auth  # noqa: E402
from nbkit.omnisol import modals as _modals  # noqa: E402
from nbkit.omnisol import navigator as _nav  # noqa: E402
from nbkit.omnisol.menu_schemas import VOUCHER_RECEIVABLE  # noqa: E402
from nbkit.patterns import login_flow, menu_navigate_flow, user_type_flow  # noqa: E402

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
RUNS = int(os.environ.get("E2E_RUNS", "2"))

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
OUT = ARTIFACTS / "login_timing_probe.json"

# 공지 레이어 팝업 존재 여부(고유 앵커) — 등장 시각 관찰용.
NOTICE_PRESENT_JS = "() => !!document.querySelector('#close-today-chk')"


def _add(marks: dict, key: str, val: int) -> None:
    marks.setdefault(key, []).append(val)


def _instrument(marks: dict) -> list:
    """단계 함수와 공지 dismiss 를 감싸 실시간 소요(ms)를 적재한다. 원복용 리스트 반환."""
    originals: list = []

    def wrap(module, name: str, label: str) -> None:
        fn = getattr(module, name)
        originals.append((module, name, fn))

        async def timed(*a, **kw):
            t0 = time.monotonic()
            try:
                return await fn(*a, **kw)
            finally:
                _add(marks, label, int((time.monotonic() - t0) * 1000))

        setattr(module, name, timed)

    wrap(login_flow, "omnisol_login", "1_로그인(goto+폼+제출폴링)")
    wrap(login_flow, "read_profile", "3_프로필 읽기")

    # 공지 dismiss 는 여러 모듈이 각자 호출한다 — 호출부별로 나눠 잰다(중복 대기 확인).
    orig_dismiss = _modals.dismiss_notice_popup
    for mod, label in (
        (login_flow, "2_공지대기(로그인 단계)"),
        (_auth, "4_공지대기(사용자유형 단계)"),
        (_nav, "5_공지대기(메뉴 도착 후)"),
    ):
        fn = getattr(mod, "dismiss_notice_popup", None)
        if fn is None:
            continue
        originals.append((mod, "dismiss_notice_popup", fn))

        def make(inner, key):
            async def timed(*a, **kw):
                t0 = time.monotonic()
                try:
                    return await inner(*a, **kw)
                finally:
                    _add(marks, key, int((time.monotonic() - t0) * 1000))

            return timed

        setattr(mod, "dismiss_notice_popup", make(fn, label))
    del orig_dismiss
    return originals


def _restore(originals: list) -> None:
    for module, name, fn in originals:
        setattr(module, name, fn)


async def _watch_notice(page, t0: float, marks: dict) -> None:
    """공지 레이어 팝업이 DOM 에 붙는 시각(진입 시작 기준 ms)을 기록한다(관찰만)."""
    for _ in range(200):
        try:
            if await page.evaluate(NOTICE_PRESENT_JS):
                _add(marks, "P_공지팝업 등장시각", int((time.monotonic() - t0) * 1000))
                return
        except Exception:  # noqa: BLE001 — 네비게이션 중 평가 실패는 무시.
            pass
        await asyncio.sleep(0.1)


async def _one_run(pw, base: str, marks: dict) -> None:
    """콜드 컨텍스트로 로그인 → 사용자유형(회계) → 메뉴 진입까지 1회."""
    browser = await pw.chromium.launch(headless=HEADLESS)
    ctx = await browser.new_context(viewport=LIVE_VIEWPORT)
    page = await ctx.new_page()
    t0 = time.monotonic()
    watcher = asyncio.create_task(_watch_notice(page, t0, marks))
    try:
        await login_flow.ensure_logged_in(page, USERID, PASSWORD, base)
        _add(marks, "A_로그인 구간 합계", int((time.monotonic() - t0) * 1000))

        t1 = time.monotonic()
        await user_type_flow.ensure_user_type(page, "회계")
        _add(marks, "B_사용자유형 전환", int((time.monotonic() - t1) * 1000))

        t2 = time.monotonic()
        await menu_navigate_flow.navigate_schema(page, VOUCHER_RECEIVABLE, base)
        _add(marks, "C_메뉴 진입", int((time.monotonic() - t2) * 1000))
    finally:
        _add(marks, "0_총계(진입 완료까지)", int((time.monotonic() - t0) * 1000))
        watcher.cancel()
        await ctx.close()
        await browser.close()


async def main() -> int:
    if not (USERID and PASSWORD):
        print("E2E_USERID / E2E_PASSWORD 를 .env 에 채우고 실행하세요.", file=sys.stderr)
        return 2
    base = get_settings().erp_base
    marks: dict = {}
    originals = _instrument(marks)
    try:
        async with async_playwright() as pw:
            for i in range(RUNS):
                await _one_run(pw, base, marks)
                print(f"[{i + 1}/{RUNS}] 총 {marks['0_총계(진입 완료까지)'][-1]}ms", flush=True)
    finally:
        _restore(originals)
    OUT.write_text(json.dumps(marks, ensure_ascii=False, indent=2))

    tot = marks.get("0_총계(진입 완료까지)") or [1]
    tot_avg = sum(tot) // len(tot)
    print(f"\n단계별 소요(ms) — {RUNS}회, {OUT}")
    for label in sorted(marks):
        vals = marks[label]
        avg = sum(vals) // len(vals)
        share = "" if label.startswith(("0_", "P_")) else f"  ({avg * 100 // max(tot_avg, 1)}%)"
        print(f"  {label:26s} 평균 {avg:6d}  각 {vals}{share}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
