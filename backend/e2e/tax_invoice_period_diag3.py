"""세금계산서 잔존 전표 소재 진단 3차 — 완전 기본값(아무 것도 안 건드림) 조회 베이스라인.

split 녹화(tax_invoice_codegen_split.py) 분석 결과 ACTG_DT(회계일)를 날짜 위젯으로 명시 변경한
흔적이 있다(달력 day-cell 클릭, title="...년 8월 26일..."). 이전 진단들은 결의구분/조회모드/
날짜필드를 JS 로 조작했는데, 그 조작 자체가 조회 컨텍스트를 깨뜨렸을 가능성을 배제하기 위해
**아무 것도 건드리지 않고** 화면 기본값 그대로 조회(F2)만 눌러본다. 읽기 전용.

Usage: cd backend && .venv/bin/python e2e/tax_invoice_period_diag3.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright  # noqa: E402

from app.config import get_settings  # noqa: E402
from e2e.product_cycle import MASTER_DUMP_JS, PASSWORD, USERID, query_master  # noqa: E402
from nbkit.omnisol import selectors  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402


def _dump_rows(dump: dict) -> list[dict]:
    rows = dump.get("rows") or []
    return [
        {"ABDOCU_NO": r.get("ABDOCU_NO"), "ABDOCU_FG_CD": r.get("ABDOCU_FG_CD"),
         "WRT_EMP_NM": r.get("WRT_EMP_NM"), "ACTG_DT": r.get("ACTG_DT"), "WRT_DT": r.get("WRT_DT"),
         "DOCU_NO": r.get("DOCU_NO")}
        for r in rows
    ]


async def main() -> None:
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page(viewport=selectors.VIEWPORT)
    base = get_settings().erp_base
    try:
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await page.goto(f"{base}/FI/GLDDOC00300")
        for _ in range(20):
            if await page.evaluate("(s) => !!document.querySelector(s)", selectors.GUBUN_SELECT):
                break
            await page.wait_for_timeout(1000)
        await page.wait_for_timeout(1500)
        await page.screenshot(path="e2e/artifacts/tax_invoice_period_diag3_untouched.png")

        # 정말 아무 것도 안 건드리고 조회(F2)만.
        rc = await query_master(page)
        dump = await page.evaluate(MASTER_DUMP_JS, 0)
        print(f"[query 완전기본값] rowcount={rc}", flush=True)
        print("[rows]", json.dumps(_dump_rows(dump), ensure_ascii=False), flush=True)
        await page.screenshot(path="e2e/artifacts/tax_invoice_period_diag3_result.png")

        await browser.close()
        await pw.stop()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc!r}", flush=True)
        try:
            await page.screenshot(path="e2e/artifacts/tax_invoice_period_diag3_exception.png")
        except Exception:  # noqa: BLE001
            pass
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
