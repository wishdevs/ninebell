"""HEADLESS 진단 프로브 — 외상매입금(voucher-receivable, DOCU_TYPES_PAYABLE) D7 체크행 0건 재현.

실사용 증상(2026-07-30): "1번째 전표 결재창 처리 실패: 결제 열기 직전 체크된 행 수가 1이 아닙니다
(D7 정합성): []" — checkRow(0) 는 true 를 반환하는데 getCheckedRows() 가 즉시 빈 배열.

⚠⚠ 절대 안전 규칙 ⚠⚠
  - 상신·보관 절대 금지. 결제(결재)창은 **열지 않는다**(steps.open_approval 호출 없음).
  - checkRow/checkAll 토글만 — 끝나면 uncheck_all_rows 로 원복.
  - F7 저장·F6 삭제 없음(조회+체크 읽기전용 진단).

진입·조회조건 세팅은 app.agents.voucher_receivable.steps 를 전부 그대로 재사용한다(신규 로직 없음
— 이 프로브는 순수 진단이며 새 JS 를 만들지 않는다. steps.check_row/uncheck_all_rows/
checked_row_indexes 는 실제 프로덕션 코드와 100% 동일 함수를 그대로 호출한다).

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/voucher_payable_d7_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Page, async_playwright  # noqa: E402

# ── 재사용(신규 작성 아님) ────────────────────────────────────────────────────────
from app.agents.voucher_receivable import steps  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT  # noqa: E402
from nbkit.omnisol.menu_schemas import VOUCHER_RECEIVABLE  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

# 기간 확대 폴백(당월 0건이면 최근 6개월로 넓혀 재조회) — 실측 진단용, 프로덕션 규칙과 무관.
WIDE_PERIOD_START = "20200101"
WIDE_PERIOD_END = "20260730"

# ── 신규 작성분(그리드 전수 식별용 — 발견 목적, 부작용 없음) ──────────────────────
GRID_SURVEY_JS = r"""() => {
  const grids = [...document.querySelectorAll('.dews-ui-grid')];
  return grids.map((el, i) => {
    try {
      const ctrl = window.jQuery(el).data('dewsControl');
      const g = ctrl ? ctrl._grid : null;
      if (!g) return { i, ok:false, reason:'no-dewsControl/_grid' };
      const n = g.getDataSource().getRowCount();
      const cols = (g.getColumns ? g.getColumns() : []).slice(0, 6).map(c => ({
        field: c.fieldName || c.name || null,
        header: (c.header && (c.header.text || c.header.caption)) || c.caption || null,
      }));
      return { i, ok:true, rowCount: n, firstCols: cols, visible: el.offsetParent !== null };
    } catch (e) { return { i, ok:false, err: String(e).slice(0, 120) }; }
  });
}"""


def _dump(name: str, obj) -> Path:
    p = ARTIFACTS / f"voucher_payable_d7_{name}.json"
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
    print(f"[dump] {p}")
    return p


async def run() -> None:
    settings = get_settings()
    base = settings.erp_base
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        page: Page = await (await browser.new_context(viewport=LIVE_VIEWPORT)).new_page()
        try:
            print("[step] login → user_type(회계) → menu_nav(전표조회승인)")
            await ensure_logged_in(page, USERID, PASSWORD, base)
            await ensure_user_type(page, "회계")
            await navigate_schema(page, VOUCHER_RECEIVABLE, base)
            await page.screenshot(path=str(ARTIFACTS / "voucher_payable_d7_1_menu.png"))

            print("[step] 조회조건 세팅 — 작성부서 전체 / 전표상태 미결 / 전자결재상태 저장 / 전표유형 내수구매")
            await steps.expand_condition_panel(page)  # optional-area 패널 확장(전표유형 노출용, production set_query 와 동일 순서)
            r = await steps.set_dept_all(page)
            print("  set_dept_all:", r)
            r = await steps.set_period_this_month(page)
            print("  set_period_this_month:", r)
            r = await steps.clear_writer(page)
            print("  clear_writer:", r)
            # 자가수정: 미결+저장 필터로 0건이라(6.5년 범위로도) 그리드 메커니즘 진단 목적상
            # 전표상태/전자결재상태 필터를 완화해 데이터 존재 여부부터 확인한다(가설: 이 조건
            # 조합 자체가 현재 계정에 해당 데이터가 없을 뿐, D7 재현엔 무관 — grid[0] 메커니즘만
            # 보면 되므로 아무 내수구매 행이나 있으면 충분하다).
            RELAX_STATUS_FILTERS = os.environ.get("RELAX_STATUS", "0") == "1"
            if not RELAX_STATUS_FILTERS:
                r = await steps.set_docu_status(page, "미결")
                print("  set_docu_status:", r)
                r = await steps.set_gwaprvlst(page, "저장")
                print("  set_gwaprvlst:", r)
            else:
                print("  (RELAX_STATUS=1 — 전표상태/전자결재상태 필터 건너뜀)")
            r = await steps.set_docu_types(page, steps.DOCU_TYPES_PAYABLE)
            print("  set_docu_types(내수구매):", r)
            if not r.get("ok"):
                raise RuntimeError(f"전표유형(내수구매) 세팅 실패 — 진단 중단: {r}")

            print("[step] 조회(F2)")
            q = await steps.run_query(page)
            print("  run_query:", q)
            if q.get("ok") and q.get("rowcount") == 0:
                print("  0건 — 기간을 넓혀 재조회")
                pr = await steps.set_period(page, WIDE_PERIOD_START, WIDE_PERIOD_END)
                print("  set_period(넓힘):", pr)
                q = await steps.run_query(page)
                print("  run_query(재조회):", q)
            await page.screenshot(path=str(ARTIFACTS / "voucher_payable_d7_2_query_result.png"))
            if not q.get("ok") or not q.get("rowcount"):
                raise RuntimeError(f"조회 결과 0건 또는 실패 — D7 진단 불가: {q}")

            print("[step] 그리드 전수 서베이(가설1 — grid[0] 오타깃 여부)")
            grids = await page.evaluate(GRID_SURVEY_JS)
            for g in grids:
                print("  grid:", g)
            _dump("grid_survey", grids)

            print("[step] 마스터 상위 5행 덤프(참고)")
            sample = await steps.read_master_rows(page, limit=5)
            print("  read_master_rows:", json.dumps(sample, ensure_ascii=False, default=str)[:1500])
            _dump("master_sample", sample)

            print("[step] D7 재현 — uncheck_all → check_row(0) → checked_row_indexes 즉시/0.5s/2s")
            uc = await steps.uncheck_all_rows(page)
            print("  uncheck_all_rows:", uc)
            cr = await steps.check_row(page, 0)
            print("  check_row(0):", cr)

            immediate = await steps.checked_row_indexes(page)
            print("  checked_row_indexes(즉시):", immediate)
            await page.wait_for_timeout(500)
            after_500 = await steps.checked_row_indexes(page)
            print("  checked_row_indexes(0.5s 후):", after_500)
            await page.wait_for_timeout(1500)
            after_2000 = await steps.checked_row_indexes(page)
            print("  checked_row_indexes(2s 후, 누적 2.0s):", after_2000)
            await page.screenshot(path=str(ARTIFACTS / "voucher_payable_d7_3_after_check.png"))

            # 그리드[0] 이 진짜 마스터인지 재확인 — 서베이 결과의 rowCount 와 대조.
            master_grid_i = next((g["i"] for g in grids if g.get("ok") and g.get("rowCount") == q.get("rowcount")), None)
            print(f"  rowCount({q.get('rowcount')})와 일치하는 그리드 인덱스: {master_grid_i} (grid[0] 이어야 정상)")

            print("\n[cleanup] 체크 원복(checkAll false)")
            await steps.uncheck_all_rows(page)
            final_check = await steps.checked_row_indexes(page)
            print("  cleanup 후 checked_row_indexes:", final_check)

            result = {
                "query": q,
                "grids": grids,
                "master_grid_index_by_rowcount_match": master_grid_i,
                "uncheck_all_result": uc,
                "check_row_result": cr,
                "checked_immediate": immediate,
                "checked_after_500ms": after_500,
                "checked_after_2000ms": after_2000,
                "cleanup_final_check": final_check,
            }
            _dump("result", result)

            print("\n=== SUMMARY ===")
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {exc}")
            try:
                await page.screenshot(path=str(ARTIFACTS / "voucher_payable_d7_FAIL.png"))
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            # ⚠ 결제창 미오픈, 상신/저장 없음 — 조회+체크 토글뿐이라 정리는 브라우저 종료로 충분.
            await browser.close()


if __name__ == "__main__":
    asyncio.run(run())
