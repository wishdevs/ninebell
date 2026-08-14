"""읽기전용 프로브 — 전표조회승인 마스터 행별 **하위(계정정보) 그리드 건수** 취득 방법·비용·분포.

배경(사용자 요구 2026-07-27): 외상매출금 결재 순회를 "한 건씩"에서 **건수 기반 배치**로 바꾼다.
  - 하위 그리드 건수가 단독 200 이상인 전표 → 먼저 단독 결재.
  - 나머지는 합계가 200 미만이 되도록 묶어 일괄 결재.
그러려면 순회 **전에** 각 마스터 행의 하위 건수를 알아야 하는데, 마스터 그리드 27개 컬럼에는
건수 컬럼이 없다(실측: e2e/artifacts/voucher_receivable_discover_master_dump.json) — 행을
선택해 디테일 그리드를 읽는 수밖에 없다. 이 프로브가 확정할 것:

  Q1. 디테일 로딩 트리거가 **setCurrent 만으로 되는가**, `checkRow` 까지 필요한가.
      (js_lib.SET_CURRENT_BY_INDEX_JS 주석은 'setCurrent 는 디테일 로딩을 트리거하지 않는다'
       (BOM 화면 기준)인데, approvals.py 주석은 이 화면에서 'check_row(setCurrent)가 디테일
       재조회를 트리거'라 한다 — 화면별로 다르므로 실측으로 가른다.)
  Q2. 행당 소요 시간(ms) — 138건 전수 스캔이 현실적인지.
  Q3. 실제 건수 분포 — 200 이상 단독 대상이 몇 건이나 되는지, 배치가 몇 개로 갈리는지.

⚠ 절대 안전: **읽기 전용**. 결재 버튼 클릭 없음(결제창/EAP draft 생성 없음), 저장(F7)·삭제(F6)·
   상신 없음. 하는 일은 조회조건 세팅 → 조회(F2) → 행 선택(setCurrent/checkRow) → 디테일
   rowcount 읽기뿐이다. 행 선택은 화면 상태만 바꾸며 서버에 아무것도 쓰지 않는다.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/voucher_receivable_detail_count_probe.py          # 기본 25행 샘플
    E2E_SCAN_ROWS=0 .venv/bin/python e2e/voucher_receivable_detail_count_probe.py   # 전수
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

from app.agents.voucher_receivable import js as vjs  # noqa: E402
from app.agents.voucher_receivable import steps as vsteps  # noqa: E402
from app.config import get_settings  # noqa: E402
from nbkit.omnisol import js_lib  # noqa: E402
from nbkit.omnisol.menu_schemas import VOUCHER_RECEIVABLE  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
SCAN_ROWS = int(os.environ.get("E2E_SCAN_ROWS", "25"))  # 0 = 전수
BATCH_LIMIT = int(os.environ.get("E2E_BATCH_LIMIT", "200"))  # 사용자 규칙 임계값

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
OUT = ARTIFACTS / "voucher_receivable_detail_counts.json"

# 디테일 로딩 정착 폴링 — 서버 왕복이라 고정대기 금지(로딩 오버레이 소멸 + rowcount 안정).
_SETTLE_TRIES = 20
_SETTLE_INTERVAL_MS = 150


async def _detail_fingerprint(page) -> list:
    """디테일 그리드 상위 2행의 식별 필드 — **행마다 실제로 재로딩되는지** 검증용(읽기전용).

    같은 건수(예: 매출전표 표준 3분개)만 보면 '안 바뀐 그리드를 반복해서 읽는 것'과 구분되지
    않는다 — 내용 지문이 행마다 달라져야 디테일이 그 행의 것임이 확정된다.
    """
    try:
        rows = await page.evaluate(js_lib.GET_JSON_ROWS_JS, {"index": 1, "start": 0, "end": 1})
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    keep = ("ACCT_NM", "ACCT_CD", "NOTE_DC", "DR_AMT", "CR_AMT", "DOCU_NO")
    return [{k: r.get(k) for k in keep if k in r} for r in rows]


async def _detail_count_after(page, action: str, idx: int) -> tuple[int, int]:
    """행 idx 를 action('setCurrent'|'checkRow') 으로 선택하고 디테일 rowcount 를 읽는다.

    반환 (rowcount, 소요 ms). rowcount -1 = 디테일 그리드 접근 실패.
    """
    t0 = time.monotonic()
    if action == "setCurrent":
        await page.evaluate(js_lib.SET_CURRENT_BY_INDEX_JS, {"index": 0, "itemIndex": idx})
    else:
        await page.evaluate(vjs.UNCHECK_ALL_JS)
        await page.evaluate(vjs.CHECK_ROW_JS, idx)
    # 로딩 오버레이가 사라지고 rowcount 가 안정될 때까지(연쇄 재조회 대응).
    await vsteps.wait_loading_overlay_gone(page)
    last = -1
    for _ in range(_SETTLE_TRIES):
        rc = await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)
        if isinstance(rc, int) and rc >= 0 and rc == last:
            break
        last = rc if isinstance(rc, int) else -1
        await page.wait_for_timeout(_SETTLE_INTERVAL_MS)
    return last, int((time.monotonic() - t0) * 1000)


def _plan_batches(rows: list[dict], limit: int) -> dict:
    """사용자 규칙대로 묶는다: 단독 >=limit 은 먼저 단독 처리, 나머지는 합계 < limit 로 묶음."""
    solo = [r for r in rows if r["count"] >= limit]
    rest = sorted((r for r in rows if 0 <= r["count"] < limit), key=lambda r: -r["count"])
    batches: list[list[dict]] = []
    for r in rest:
        for b in batches:
            if sum(x["count"] for x in b) + r["count"] < limit:
                b.append(r)
                break
        else:
            batches.append([r])
    return {
        "solo": [{"docu_no": r["docu_no"], "count": r["count"]} for r in solo],
        "batches": [
            {
                "n_docs": len(b),
                "sum": sum(x["count"] for x in b),
                "docu_nos": [x["docu_no"] for x in b],
            }
            for b in batches
        ],
        "unreadable": [r["docu_no"] for r in rows if r["count"] < 0],
    }


async def main() -> int:
    settings = get_settings()
    report: dict = {"userid": USERID, "limit": BATCH_LIMIT, "scan_rows": SCAN_ROWS}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        ctx = await browser.new_context(viewport={"width": 1600, "height": 1000})
        page = await ctx.new_page()
        try:
            await ensure_logged_in(page, USERID, PASSWORD, settings.erp_base)
            await ensure_user_type(page, "회계")
            await navigate_schema(page, VOUCHER_RECEIVABLE, settings.erp_base)

            # 조회조건은 노드가 아니라 스텝 조합으로 직접 세팅한다(프로브는 그래프를 타지 않는다).
            await vsteps.expand_condition_panel(page)
            for label, call in (
                ("작성부서", vsteps.set_dept_all(page)),
                ("회계일", vsteps.set_period_this_month(page)),
                ("작성자", vsteps.clear_writer(page)),
                ("전표상태", vsteps.set_docu_status(page)),
                ("전자결재상태", vsteps.set_gwaprvlst(page)),
            ):
                res = await call
                if not res.get("ok"):
                    print(f"[FAIL] 조회조건 {label}: {res.get('reason')}")
                    return 1
                if res.get("warn"):
                    print(f"[warn] 조회조건 {label}: {res['warn']}")
            res = await vsteps.set_docu_types(page, vsteps.DOCU_TYPES_RECEIVABLE)
            if not res.get("ok"):
                print(f"[FAIL] 조회조건 전표유형: {res.get('reason')}")
                return 1

            q = await vsteps.run_query(page)
            if not q.get("ok"):
                print(f"[FAIL] 조회: {q.get('reason')}")
                return 1
            total = int(q["rowcount"])
            report["rowcount"] = total
            print(f"[ok] 조회 완료 — 대상 {total}건")

            # Q1 — 트리거 방식 비교(앞 3행): setCurrent 만으로 디테일이 행마다 바뀌는가?
            probe_a = [await _detail_count_after(page, "setCurrent", i) for i in range(min(3, total))]
            probe_b = [await _detail_count_after(page, "checkRow", i) for i in range(min(3, total))]
            report["trigger_setCurrent"] = probe_a
            report["trigger_checkRow"] = probe_b
            distinct_a = len({c for c, _ in probe_a})
            use_check = distinct_a <= 1 and len({c for c, _ in probe_b}) > 1
            action = "checkRow" if use_check else "setCurrent"
            report["chosen_trigger"] = action
            print(f"[Q1] setCurrent={probe_a} / checkRow={probe_b} → 사용: {action}")

            # Q2·Q3 — 스캔.
            n = total if SCAN_ROWS == 0 else min(SCAN_ROWS, total)
            rows: list[dict] = []
            t0 = time.monotonic()
            for i in range(n):
                key = await vsteps.read_row_key(page, i)
                count, ms = await _detail_count_after(page, action, i)
                fp = await _detail_fingerprint(page)
                rows.append({"idx": i, "docu_no": key, "count": count, "ms": ms, "detail": fp})
                if (i + 1) % 5 == 0:
                    print(f"  … {i + 1}/{n} 스캔(누적 {int((time.monotonic() - t0) * 1000)}ms)")
            report["rows"] = rows
            per_row = [r["ms"] for r in rows]
            report["timing"] = {
                "total_ms": int((time.monotonic() - t0) * 1000),
                "avg_ms": round(sum(per_row) / len(per_row), 1) if per_row else None,
                "min_ms": min(per_row) if per_row else None,
                "max_ms": max(per_row) if per_row else None,
                "projected_full_scan_s": round(
                    (sum(per_row) / len(per_row)) * total / 1000, 1
                ) if per_row else None,
            }
            counts = [r["count"] for r in rows if r["count"] >= 0]
            # 디테일이 행마다 실제로 갱신됐는지 — 지문 distinct 수(1이면 '안 바뀜' 의심).
            fps = [json.dumps(r.get("detail"), ensure_ascii=False, sort_keys=True) for r in rows]
            report["detail_refresh"] = {
                "distinct_fingerprints": len(set(fps)),
                "scanned": len(fps),
                "verdict": "행별 갱신 확인" if len(set(fps)) > 1 else "⚠ 갱신 미확인(같은 디테일 반복 의심)",
            }
            report["distribution"] = {
                "n": len(counts),
                "min": min(counts) if counts else None,
                "max": max(counts) if counts else None,
                "sum": sum(counts),
                "ge_limit": sum(1 for c in counts if c >= BATCH_LIMIT),
                "histogram": {
                    "1": sum(1 for c in counts if c == 1),
                    "2-9": sum(1 for c in counts if 2 <= c <= 9),
                    "10-49": sum(1 for c in counts if 10 <= c <= 49),
                    "50-199": sum(1 for c in counts if 50 <= c <= 199),
                    ">=200": sum(1 for c in counts if c >= 200),
                },
            }
            report["plan_preview"] = _plan_batches(rows, BATCH_LIMIT)
        finally:
            await ctx.close()
            await browser.close()

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: report[k] for k in ("timing", "detail_refresh", "distribution") if k in report},
                     ensure_ascii=False, indent=2))
    pp = report.get("plan_preview", {})
    print(f"[계획 미리보기] 단독 {len(pp.get('solo', []))}건 / 묶음 {len(pp.get('batches', []))}개")
    print(f"[artifact] {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
