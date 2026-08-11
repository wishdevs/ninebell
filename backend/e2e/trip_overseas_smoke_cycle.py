"""출장(해외/정산서) 실저장 사이클 스모크 — **제품 경로**(대시보드 폼→실행)로 작성 → ERP 삭제.

전환(사용자 지시 2026-08-03): 종전에는 `build_trip_overseas_graph()` 를 스크립트가 직접
`ainvoke` 해서 ERP 에서 작성하고 ERP 에서 지웠다 — 프론트 pre-run 폼·`runs.py` collect 의 서버
권위 params 주입(department·cost_type)·러너·agent_runs 기록이 전부 미검증이었다. 이제
`e2e/product_cycle.py` 공통 모듈을 통해 법인카드 e2e 와 같은 2페이즈로 돈다.

해외 델타(국내 대비, PROCESS.md/FLOW.md · 2026-07-09 라이브 실측):
  - 결의구분 **'출장(해외·정산서)' value 54**(국내 53, 경조 55, 학자 56) — 가드도 54 로 격리.
  - 행 유형(통행료/유류비) 구분 없음 — **전 행 동일 형태**(계산서일·공급가액·프로젝트·적요).
  - 거래처 = **전 행 작성자 본인** → detail PARTNER_NM 을 사이클마다 검증.
  - 공급가액 **직접 입력**(계산 규칙 없음) → 입력값이 그대로 SPPRC_AMT2 인지 행별 검증.
  - 적요 **자유 입력** → NOTE_DC 행별 검증.
  - 회계일자 = 계산서일 **최댓값** 파생 → 한 사이클의 행은 같은 달로 유지한다.
  - 부가선택에 상대계정거래처 항목이 없어 스트레이 빈 행이 생기지 않는다 → **detail 행수 =
    입력 행수** 를 사이클마다 검증.

⚠ 안전 수칙
  - **삭제까지가 한 사이클** · **상신(결재) 절대 금지**(F7 저장·F6 삭제만).
  - 삭제 3중 가드: 결의자=로그인계정 + 결의구분=54 + 미결(DOCU_NO 공백). **완화 금지.**
    같은 계정으로 국내53·경조55·학자56 스모크가 돌아도 결의구분 필터+가드로 격리된다.

Usage: cd backend && TRIP_OVERSEAS_SMOKE_CYCLES=1 .venv/bin/python e2e/trip_overseas_smoke_cycle.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from datetime import date as _date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")

from e2e.product_cycle import (  # noqa: E402
    USERID,
    add_row,
    as_int,
    erp_verify_and_delete,
    pick_combo,
    row_scope,
    run_cycles,
    run_product,
    set_date,
    summarize_run,
)

AGENT_ID = "trip-overseas"
WORKFLOW_ID = "trip-overseas"
TAG = "trip_overseas_product_cycle"
CYCLES = int(os.environ.get("TRIP_OVERSEAS_SMOKE_CYCLES", "1"))

TRIP_OVERSEAS_FG = "54"  # 결의구분 출장(해외·정산서) 코드(2026-07-09 라이브 실측)
GUBUN_LABEL = "출장(해외·정산서)"

PROJECT_NAME = "포장개선"  # 1310|1310 — 코드피커 검색이 라이브 검증된 유일 코드(사이클 공용)

# 사이클별 행 금액 표 — 해외는 금액 계산 규칙이 없어 **입력값이 그대로** 공급가액이어야 한다.
# 행수를 1~3으로 흔들어 행 추가·행별 채움 회귀를 함께 본다. 행마다 금액을 달리해 **행 순서까지**
# 대조되게 한다. 표보다 사이클이 많으면 순환.
_CYCLE_PLAN: list[list[int]] = [
    [51000],
    [23000, 47500],
    [12345, 67890, 100000],
    [88800, 15200],
    [99999],
    [31000, 42000, 53000],
    [7000, 8000],
    [123456],
    [64001, 71001],
    [10500, 20500, 30500],
]


def _row_dates(n: int) -> list[str]:
    """행별 계산서일 — 오늘부터 역순 n개, 단 **월을 넘지 않게** 클램프.

    회계일자는 계산서일 최댓값(=오늘)으로 파생된다. 월이 걸치는 건은 결의서를 나눠 상신해야
    하므로(PROCESS.md 상신 주의) 한 사이클의 행은 같은 달로 유지한다 — 월초에는 전부 오늘.
    """
    today = _date.today()
    span = max(1, min(n, today.day))
    return [(today - timedelta(days=i % span)).isoformat() for i in range(n)]


def _plan(cycle: int) -> dict:
    """`_CYCLE_PLAN` 표에서 행 금액 목록 결정 — 종전 `_cycle_params` 와 동일 축(금액·행수)."""
    amounts = list(_CYCLE_PLAN[(cycle - 1) % len(_CYCLE_PLAN)])
    dates = _row_dates(len(amounts))
    notes = [f"해외출장 일비 {cycle}-{i + 1}" for i in range(len(amounts))]
    return {
        "rows": len(amounts),
        "amounts": amounts,
        "dates": dates,
        "notes": notes,
        "partners": [USERID] * len(amounts),
        "total": sum(amounts),
    }


async def _fill(page, plan: dict) -> None:
    """실행 전 입력 폼을 **실제 위젯 조작**으로 채운다(코드 주입 없음)."""
    for _ in range(plan["rows"] - 1):
        await add_row(page)
    for i in range(1, plan["rows"] + 1):
        scope = row_scope(page, i)
        await set_date(page, f"{i}행 계산서일", plan["dates"][i - 1])
        await pick_combo(page, scope, 0, PROJECT_NAME, PROJECT_NAME)  # 프로젝트
        await scope.get_by_label(f"{i}행 공급가액").fill(str(plan["amounts"][i - 1]))
        await scope.get_by_label(f"{i}행 적요").fill(plan["notes"][i - 1])
        print(f"[P1] {i}행 amount={plan['amounts'][i - 1]} date={plan['dates'][i - 1]}", flush=True)


def _verify(plan: dict, vd: dict) -> dict:
    """저장 결과 대조 — 행수(스트레이 빈 행 없음)·행별 금액·거래처(본인)·적요·합계."""
    det = vd.get("detail") or {}
    rows = det.get("rows") or []
    actual_amounts = [as_int(r.get("SPPRC_AMT2")) for r in rows]
    actual_notes = [str(r.get("NOTE_DC") or "").strip() for r in rows]
    actual_partners = [str(r.get("PARTNER_NM") or "").strip() for r in rows]
    total = as_int((vd.get("master") or {}).get("DETAIL_SUM_AMT"))
    rows_clean = det.get("n") == plan["rows"]
    return {
        "detail_rowcount": det.get("n"),
        "rows_clean": rows_clean,
        "expected_amounts": plan["amounts"], "actual_amounts": actual_amounts,
        "amount_match": rows_clean and actual_amounts == plan["amounts"],
        "expected_notes": plan["notes"], "actual_notes": actual_notes,
        "note_match": rows_clean and actual_notes == plan["notes"],
        "expected_partners": plan["partners"], "actual_partners": actual_partners,
        "partner_match": rows_clean and actual_partners == plan["partners"],
        "expected_total": plan["total"], "actual_total": total,
        "total_match": total == plan["total"],
    }


def _pick_master(rows: list[dict], expected_total: int) -> int:
    for i, r in enumerate(rows):
        if as_int(r.get("DETAIL_SUM_AMT")) == expected_total:
            return i
    return len(rows) - 1


async def _run_one(cycle: int) -> dict:
    plan = _plan(cycle)
    t0 = time.monotonic()
    run = await run_product(
        agent_id=AGENT_ID, workflow_id=WORKFLOW_ID,
        fill=lambda page: _fill(page, plan), tag=f"{TAG}_c{cycle}",
    )
    run_ms = int((time.monotonic() - t0) * 1000)
    saved = bool(run.get("terminal") and run.get("ui_status") == "succeeded")
    vd = await erp_verify_and_delete(
        gubun_label=GUBUN_LABEL, fg_code=TRIP_OVERSEAS_FG, tag=f"{TAG}_c{cycle}",
        pick_master=lambda rows: _pick_master(rows, plan["total"]), want_detail=saved,
    )
    checks = _verify(plan, vd) if saved else {}
    ok = bool(
        saved and run.get("run_recorded") and run.get("db_status") == "succeeded"
        and vd.get("deleted") and checks.get("rows_clean") and checks.get("amount_match")
        and checks.get("note_match") and checks.get("partner_match") and checks.get("total_match")
    )
    return {"cycle": cycle, "ok": ok, "run_ms": run_ms, "plan": plan,
            "run": run, "delete": vd, "checks": checks}


def _report(i: int, c: dict) -> None:
    p = c.get("plan") or {}
    k = c.get("checks") or {}
    mark = "PASS" if c.get("ok") else "FAIL"
    print(f"[CYCLE {i}] {mark} run={c.get('run_ms', 0) / 1000:.1f}s | {p.get('rows')}행 "
          f"amounts={p.get('amounts')} 합계={p.get('total')} 계산서일={p.get('dates')}", flush=True)
    print(f"  {summarize_run(c)}", flush=True)
    if k:
        print(f"  checks: rows={k.get('detail_rowcount')}/{p.get('rows')} clean={k.get('rows_clean')} "
              f"amount={k.get('amount_match')} note={k.get('note_match')} partner={k.get('partner_match')} "
              f"total={k.get('total_match')}(기대 {k.get('expected_total')}·실제 {k.get('actual_total')})", flush=True)
        print(f"  amounts expected={k.get('expected_amounts')} actual={k.get('actual_amounts')}", flush=True)
        print(f"  partners actual={k.get('actual_partners')} notes actual={k.get('actual_notes')}", flush=True)
    if (c.get("run") or {}).get("error"):
        print(f"  run error: {c['run']['error']}", flush=True)
    if (c.get("run") or {}).get("fail_reason"):
        print(f"  fail reason: {c['run']['fail_reason']}", flush=True)


async def main() -> None:
    print(f"[SMOKE] 삭제 격리: 결의구분 {TRIP_OVERSEAS_FG}(해외 정산서) 전표만 대상 — "
          "국내53·경조55·학자56 은 건드리지 않는다.", flush=True)
    code = await run_cycles(
        title="TRIP-OVERSEAS PRODUCT SAVE-CYCLE", cycles=CYCLES, tag=TAG,
        run_one=_run_one, report_line=_report,
    )
    sys.exit(code)


if __name__ == "__main__":
    asyncio.run(main())
