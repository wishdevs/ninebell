"""동시 세션 병렬화 실측 — 같은 계정(이트라이브2)으로 독립 브라우저 컨텍스트 3개가
동시에 살아남는지 확인한다. 구매발주일괄입력(PUOORD02000) 병렬화(브라우저 3개, PRQ 단위
분담) 타당성의 게이트.

읽기 전용(화면 진입·팝업 열닫만). 저장·상신·거래처변경·적용 일절 없음.

절차:
  1. 컨텍스트 3개를 순차 생성 → 각각 로그인(ensure_logged_in) → SCM 유저타입
     (ensure_user_type) → 구매발주일괄입력[나인벨](PURCHASE_PO_BATCH) 진입(navigate_schema).
  2. 3번째 로그인 직후 3세션 모두 살아있는지(다이얼로그·그리드 상태) 확인.
  3. 동시(asyncio.gather) 조작: ensure_po_type → open_request_popup → 스크린샷 → 닫기.
  4. 보너스: page1 팝업을 열어둔 채 page2 메인화면을 동시 조작해도 간섭 없는지 1회 확인.
  5. 정리: 컨텍스트 3개 모두 닫고, 단일 새 컨텍스트로 재로그인해 정상 동작을 확인.

Usage:
    cd backend && .venv/bin/python e2e/concurrent_session_probe.py
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

from app.agents.purchase_order import js_screen3 as j3  # noqa: E402
from app.agents.purchase_order import steps_screen3 as s3  # noqa: E402
from app.config import get_settings  # noqa: E402
from nbkit.browser.detection import detect_dialog, selector_count  # noqa: E402
from nbkit.omnisol import selectors  # noqa: E402
from nbkit.omnisol.menu_schemas import PURCHASE_PO_BATCH  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
ARTIFACTS = Path(__file__).resolve().parent / "artifacts" / "concurrent_session_probe"
ARTIFACTS.mkdir(parents=True, exist_ok=True)
BASE = get_settings().erp_base


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


async def _screenshot(page, name: str) -> str:
    path = ARTIFACTS / f"{name}.png"
    try:
        await page.screenshot(path=str(path))
    except Exception as exc:  # noqa: BLE001
        _log(f"  screenshot 실패 {name}: {exc}")
        return ""
    return str(path)


async def _login_session(idx: int, context) -> dict:
    """세션 하나를 로그인→SCM 전환→PUOORD02000 진입까지 진행. 타이밍·상태를 반환."""
    page = await context.new_page()
    result: dict = {"idx": idx, "page": page}
    t0 = time.monotonic()
    try:
        await ensure_logged_in(page, USERID, PASSWORD, BASE)
        result["login_ms"] = int((time.monotonic() - t0) * 1000)
        t1 = time.monotonic()
        await ensure_user_type(page, "SCM")
        result["user_type_ms"] = int((time.monotonic() - t1) * 1000)
        t2 = time.monotonic()
        active = await navigate_schema(page, PURCHASE_PO_BATCH, BASE)
        if active is not None:
            page = active
            result["page"] = page
        result["menu_nav_ms"] = int((time.monotonic() - t2) * 1000)
        result["total_ms"] = int((time.monotonic() - t0) * 1000)
        result["ok"] = True
    except Exception as exc:  # noqa: BLE001
        result["ok"] = False
        result["error"] = str(exc)[:300]
        result["total_ms"] = int((time.monotonic() - t0) * 1000)
    dlg = await detect_dialog(page)
    grid_n = await selector_count(page, selectors.GRID)
    result["dialog_after_login"] = dlg
    result["grid_count_after_login"] = grid_n
    await _screenshot(page, f"session{idx}_after_login")
    return result


async def _probe_op(idx: int, page) -> dict:
    """동시 조작: 구매발주유형 지정 → 구매요청 팝업 열기 → 스크린샷 → 닫기."""
    out: dict = {"idx": idx}
    try:
        r_type = await s3.ensure_po_type(page)
        out["ensure_po_type"] = r_type
        r_popup = await s3.open_request_popup(page)
        out["open_request_popup"] = r_popup
        dlg = await detect_dialog(page)
        out["dialog_during_op"] = dlg
        await _screenshot(page, f"session{idx}_popup_open")
        popup_present = await page.evaluate(j3.POPUP_PRESENT_JS)
        out["popup_present"] = popup_present
        out["ok"] = bool(r_type.get("ok")) and bool(r_popup.get("ok"))
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["error"] = str(exc)[:300]
    return out


async def _close_popup(idx: int, page) -> dict:
    out: dict = {"idx": idx}
    try:
        await page.keyboard.press("Escape")
        closed = await s3._wait_popup(page, False, cap_ms=5_000)  # noqa: SLF001
        out["closed"] = closed
        await _screenshot(page, f"session{idx}_popup_closed")
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)[:300]
    return out


async def main() -> None:
    report: dict = {"userid": USERID, "base": BASE, "sessions": [], "concurrent_ops": [], "closes": []}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        contexts = [await browser.new_context(viewport={"width": 1600, "height": 1000}) for _ in range(3)]

        # ── 1. 순차 로그인 3세션 ──
        sessions = []
        for i, ctx in enumerate(contexts, start=1):
            _log(f"세션 {i} 로그인 시작…")
            r = await _login_session(i, ctx)
            sessions.append(r)
            status = "OK" if r.get("ok") else f"FAIL({r.get('error')})"
            _log(
                f"세션 {i} 결과={status} total={r.get('total_ms')}ms "
                f"login={r.get('login_ms')}ms user_type={r.get('user_type_ms')}ms "
                f"menu_nav={r.get('menu_nav_ms')}ms grid_count={r.get('grid_count_after_login')} "
                f"dialog={r.get('dialog_after_login')}"
            )

        report["sessions"] = [
            {k: v for k, v in s.items() if k != "page"} for s in sessions
        ]

        # ── 2. 3번째 로그인 직후 전 세션 생존 재확인 ──
        _log("3세션 생존 재확인(그리드/다이얼로그)…")
        survive = []
        for s in sessions:
            page = s["page"]
            dlg = await detect_dialog(page)
            grid_n = await selector_count(page, selectors.GRID)
            survive.append({"idx": s["idx"], "dialog": dlg, "grid_count": grid_n})
            _log(f"  세션{s['idx']} 재확인: grid_count={grid_n} dialog={dlg}")
        report["survive_after_3rd_login"] = survive

        # ── 3. 동시 조작(asyncio.gather) ──
        alive_sessions = [s for s in sessions if s.get("ok")]
        if len(alive_sessions) < 2:
            _log("⚠ 살아있는 세션이 2개 미만 — 동시 조작 스킵.")
        else:
            _log(f"동시 조작 시작 — {len(alive_sessions)}개 세션 asyncio.gather…")
            t0 = time.monotonic()
            ops = await asyncio.gather(
                *[_probe_op(s["idx"], s["page"]) for s in alive_sessions],
                return_exceptions=True,
            )
            gather_ms = int((time.monotonic() - t0) * 1000)
            ops_clean = []
            for s, op in zip(alive_sessions, ops):
                if isinstance(op, Exception):
                    op = {"idx": s["idx"], "ok": False, "error": str(op)[:300]}
                ops_clean.append(op)
                _log(f"  세션{s['idx']} 동시조작: ok={op.get('ok')} {op}")
            report["concurrent_ops"] = ops_clean
            report["concurrent_ops_wall_ms"] = gather_ms

            # 세션 간 상태 오염 확인 — 다른 세션에서 팝업이 안 열렸는데 present=True 로 나오면 오염.
            popup_titles = {op.get("idx"): (op.get("popup_present") or {}).get("title") for op in ops_clean}
            report["popup_titles_by_session"] = popup_titles

            # ── 3번째 로그인 이후 선행 세션(1,2)이 죽었는지 별도 판정 ──
            forced_logout = [
                op for op in ops_clean if not op.get("ok") and "error" in op
            ]
            report["forced_logout_suspects"] = forced_logout

            # ── 닫기 ──
            closes = await asyncio.gather(
                *[_close_popup(s["idx"], s["page"]) for s in alive_sessions],
                return_exceptions=True,
            )
            closes_clean = []
            for s, c in zip(alive_sessions, closes):
                if isinstance(c, Exception):
                    c = {"idx": s["idx"], "error": str(c)[:300]}
                closes_clean.append(c)
                _log(f"  세션{s['idx']} 팝업닫기: {c}")
            report["closes"] = closes_clean

        # ── 4. 보너스: page1 팝업 열어둔 채 page2 메인화면 동시 조작 ──
        if len(alive_sessions) >= 2:
            _log("보너스: 세션1 팝업 열기 + 세션2 메인화면 grid 카운트 동시 확인…")
            p1, p2 = alive_sessions[0]["page"], alive_sessions[1]["page"]

            async def _reopen_and_hold(page):
                r = await s3.open_request_popup(page)
                await _screenshot(alive_sessions[0]["idx"], "held_open") if False else None
                return r

            async def _touch_main(page):
                return await selector_count(page, selectors.GRID)

            bonus = await asyncio.gather(
                _reopen_and_hold(p1), _touch_main(p2), return_exceptions=True
            )
            report["bonus_hold_open_vs_main_touch"] = [
                (str(x) if isinstance(x, Exception) else x) for x in bonus
            ]
            await _screenshot(p1, "bonus_session1_popup_held")
            await _screenshot(p2, "bonus_session2_main_touched")
            # 정리 — 세션1 팝업 닫기
            await _close_popup(alive_sessions[0]["idx"], p1)
            _log(f"보너스 결과: {report['bonus_hold_open_vs_main_touch']}")

        # ── 정리: 컨텍스트 전부 닫기 ──
        for ctx in contexts:
            try:
                await ctx.close()
            except Exception:  # noqa: BLE001
                pass

        # ── 최종: 단일 새 컨텍스트로 재로그인해 정상 동작 확인 ──
        _log("정리 후 단일 세션 재로그인 확인…")
        final_ctx = await browser.new_context(viewport={"width": 1600, "height": 1000})
        final_page = await final_ctx.new_page()
        t0 = time.monotonic()
        try:
            await ensure_logged_in(final_page, USERID, PASSWORD, BASE)
            final_ok = True
            final_err = None
        except Exception as exc:  # noqa: BLE001
            final_ok = False
            final_err = str(exc)[:300]
        final_ms = int((time.monotonic() - t0) * 1000)
        await _screenshot(final_page, "final_relogin")
        report["final_relogin"] = {"ok": final_ok, "ms": final_ms, "error": final_err}
        _log(f"최종 재로그인: ok={final_ok} ms={final_ms} err={final_err}")
        await final_ctx.close()

        await browser.close()

    report_path = ARTIFACTS / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    _log(f"리포트 저장: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
