"""HEADLESS 게이트 프로브 — voucher 백본 set_query 무결성 반복 실측(수정 전/후 실패율 비교).

무엇: 프로덕션 set_query 노드와 동일한 순서로 조회조건 세팅 → 조회(F2)까지를 N회 반복하며
스텝별 ok/reason/warn/소요(ms)를 수집한다. DB 실증상 런 실패의 63%가 set_query 에 몰린
간헐 타이밍 레이스의 전/후 실패율을 정량 비교하는 게이트다(계획 C0).

⚠⚠ 절대 안전 규칙 ⚠⚠
  - 결제(결재)창을 **열지 않는다**(open_approval 호출 없음) — EAP 임시문서 잔존 이슈 회피.
  - 마스터 그리드 checkRow/checkAll 없음, F7 저장·F6 삭제·상신 없음. 조회조건 세팅+조회뿐.
  - 진입·조회조건 세팅은 app.agents.voucher_receivable.steps 프로덕션 코드를 100% 그대로
    재사용한다(신규 조작 JS 없음 — 이 프로브는 순수 계측).

프로덕션 재현 충실도:
  - 매 회 **새 브라우저 컨텍스트 + 로그인**(로그인 직후 공지 팝업 비동기 렌더 레이스 포함 재현).
  - page 는 프로덕션 등록값과 동일한 delay_scale(기본 0.4, env CARD_DELAY_SCALE 우선)로 감싼다
    — 명목 카운터 관찰창 붕괴(delay_scale 취약성)까지 그대로 겪게 한다.
  - 회계일은 실패 런과 동일한 임의 기간(당월 아님)을 세팅해 set_period range 분기를 지난다.

Usage:
    cd backend
    GATE_TAG=r1-baseline .venv/bin/python e2e/voucher_setquery_gate_probe.py   # N=20, payable
    GATE_N=10 GATE_DOCU=receivable GATE_TAG=r2 .venv/bin/python e2e/voucher_setquery_gate_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import async_playwright  # noqa: E402

# ── 재사용(신규 작성 아님) ────────────────────────────────────────────────────────
from app.agents.voucher_receivable import steps  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT, _maybe_scale_page  # noqa: E402
from nbkit.omnisol.menu_schemas import VOUCHER_RECEIVABLE  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
N = int(os.environ.get("GATE_N", "20"))
DOCU = os.environ.get("GATE_DOCU", "payable")  # payable | receivable
TAG = os.environ.get("GATE_TAG", "run")
# 프로덕션 voucher 계열 등록값과 동일(app/agents/__init__.py delay_scale=0.4).
PROD_DELAY_SCALE = float(os.environ.get("GATE_DELAY_SCALE", "0.4"))
# 실패 런(08-03·08-06)과 동일한 '당월 아님' 임의 기간 — set_period range 분기를 지나게 한다.
PERIOD_FROM = os.environ.get("GATE_PERIOD_FROM", "20260701")
PERIOD_TO = os.environ.get("GATE_PERIOD_TO", "20260831")
ITER_TIMEOUT_S = int(os.environ.get("GATE_ITER_TIMEOUT_S", "300"))

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

DOCU_TYPES = steps.DOCU_TYPES_PAYABLE if DOCU == "payable" else steps.DOCU_TYPES_RECEIVABLE


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


async def _run_iter(browser: Any, base: str, idx: int) -> dict:
    """1회 = 새 컨텍스트 로그인 → 회계 전환 → 메뉴 진입 → set_query 순서 그대로 → 조회.
    스텝 하나라도 실패하면 그 지점에서 중단하고 실패 스텝을 기록한다(프로덕션 단락과 동일)."""
    ctx = await browser.new_context(viewport=LIVE_VIEWPORT)
    raw = await ctx.new_page()
    page = _maybe_scale_page(raw, PROD_DELAY_SCALE)
    rec: dict = {"iter": idx, "ok": False, "failed_step": None, "steps": {}}
    t_iter = time.monotonic()

    async def step(name: str, coro: Any, *, contract: bool = True) -> bool:
        """스텝 실행+기록. contract=False 는 워밍(expand 등 — 실패해도 진행)."""
        t0 = time.monotonic()
        try:
            r = await coro
        except Exception as exc:  # noqa: BLE001 — 프로브는 죽지 않고 기록한다.
            r = {"ok": False, "reason": f"exception: {exc!r:.300}"}
        if not isinstance(r, dict):
            r = {"ok": True, "returned": r}
        rec["steps"][name] = {**r, "ms": _ms(t0)}
        if contract and not r.get("ok"):
            rec["failed_step"] = name
            try:
                await raw.screenshot(path=str(ARTIFACTS / f"gate_{TAG}_i{idx:02d}_{name}_FAIL.png"))
            except Exception:  # noqa: BLE001
                pass
            return False
        return True

    try:
        t0 = time.monotonic()
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await ensure_user_type(page, "회계")
        await navigate_schema(page, VOUCHER_RECEIVABLE, base)
        rec["entry_ms"] = _ms(t0)

        # ── 프로덕션 nodes/query.py make_set_query_node 와 동일 순서 ──
        await step("expand", steps.expand_condition_panel(page), contract=False)
        if not await step("set_dept_all", steps.set_dept_all(page)):
            return rec
        if not await step("set_period", steps.set_period(page, PERIOD_FROM, PERIOD_TO)):
            return rec
        if not await step("clear_writer", steps.clear_writer(page)):
            return rec
        if not await step("set_docu_status", steps.set_docu_status(page)):
            return rec
        if not await step("set_gwaprvlst", steps.set_gwaprvlst(page)):
            return rec
        if not await step("set_docu_types", steps.set_docu_types(page, DOCU_TYPES)):
            return rec
        if not await step("run_query", steps.run_query(page)):
            return rec
        rec["ok"] = True
        return rec
    finally:
        rec["total_ms"] = _ms(t_iter)
        try:
            await ctx.close()
        except Exception:  # noqa: BLE001
            pass


async def run() -> None:
    settings = get_settings()
    base = settings.erp_base
    results: list[dict] = []
    print(f"[gate] tag={TAG} N={N} docu={DOCU}{DOCU_TYPES} period={PERIOD_FROM}~{PERIOD_TO} "
          f"delay_scale={PROD_DELAY_SCALE} headless={HEADLESS}")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        try:
            for i in range(1, N + 1):
                try:
                    rec = await asyncio.wait_for(_run_iter(browser, base, i), timeout=ITER_TIMEOUT_S)
                except asyncio.TimeoutError:
                    rec = {"iter": i, "ok": False, "failed_step": "TIMEOUT", "steps": {},
                           "total_ms": ITER_TIMEOUT_S * 1000}
                except Exception as exc:  # noqa: BLE001 — 진입 실패 등도 기록하고 계속.
                    rec = {"iter": i, "ok": False, "failed_step": "ENTRY",
                           "steps": {}, "entry_error": f"{exc!r:.300}"}
                results.append(rec)
                warns = [k for k, v in rec.get("steps", {}).items() if v.get("warn")]
                print(f"[iter {i:02d}/{N}] {'OK' if rec['ok'] else 'FAIL@' + str(rec['failed_step'])}"
                      f" total={rec.get('total_ms', '?')}ms"
                      f"{' warn=' + ','.join(warns) if warns else ''}", flush=True)
        finally:
            await browser.close()

    # ── 집계 ──
    n_ok = sum(1 for r in results if r["ok"])
    fail_by_step: dict[str, int] = {}
    warn_by_step: dict[str, int] = {}
    for r in results:
        if not r["ok"]:
            fail_by_step[str(r.get("failed_step"))] = fail_by_step.get(str(r.get("failed_step")), 0) + 1
        for k, v in r.get("steps", {}).items():
            if v.get("warn"):
                warn_by_step[k] = warn_by_step.get(k, 0) + 1
    summary = {
        "tag": TAG, "n": N, "docu": DOCU, "docu_types": list(DOCU_TYPES),
        "period": f"{PERIOD_FROM}~{PERIOD_TO}", "delay_scale": PROD_DELAY_SCALE,
        "ok": n_ok, "fail": N - n_ok, "fail_rate": round((N - n_ok) / N, 3) if N else None,
        "fail_by_step": fail_by_step, "warn_by_step": warn_by_step,
    }
    out = {"summary": summary, "results": results}
    p = ARTIFACTS / f"voucher_setquery_gate_{TAG}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    print("\n=== GATE SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[dump] {p}")


if __name__ == "__main__":
    asyncio.run(run())
