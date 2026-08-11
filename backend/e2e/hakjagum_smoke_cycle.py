"""학자금신청서 실저장 사이클 스모크 — **제품 경로**(대시보드 폼→실행)로 작성 → ERP 에서 삭제.

전환(사용자 지시 2026-08-03): 종전에는 `build_hakjagum_grant_graph()` 를 스크립트가 직접
`ainvoke` 해서 ERP 에서 작성하고 ERP 에서 지웠다 — 프론트 pre-run 폼·`runs.py` collect 의 서버
권위 params 주입(department·cost_type)·러너·agent_runs 기록이 전부 미검증이었다. 이제
`e2e/product_cycle.py` 공통 모듈을 통해 법인카드 e2e 와 같은 2페이즈로 돈다.

학자금 델타(경조금 대비): 결의구분 56 · **근속<1년 50% 규칙 없음**(정액이 그대로 공급가액) ·
단건. 상대계정거래처 스텝이 없어 **스트레이 빈 행이 없어야 한다** — detail 행수 정확히 1 로 검증.
거래처·적요는 작성자 본인으로 자동 지정된다(PARTNER_NM 검증).

⚠ 안전 수칙
  - **삭제까지가 한 사이클** · **상신(결재) 절대 금지**(F7 저장·F6 삭제만).
  - 삭제 3중 가드: 결의자(WRT_EMP_NM)=로그인계정 + 결의구분(ABDOCU_FG_CD)=56 + 미결(DOCU_NO 공백).
    **완화 금지** — 하나라도 안 맞으면 삭제 중단·보고.
  - **cycle 1 안전 게이트**: 첫 사이클에서 금액 불일치·스트레이 빈 행이 보이면 나머지 중단.

Usage: cd backend && HAKJAGUM_SMOKE_CYCLES=1 .venv/bin/python e2e/hakjagum_smoke_cycle.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")

from e2e.product_cycle import (  # noqa: E402
    TODAY,
    USERID,
    as_int,
    erp_verify_and_delete,
    pick_combo,
    run_cycles,
    run_product,
    set_date,
    summarize_run,
)

AGENT_ID = "scholarship"  # 대시보드 에이전트 상세 URL(/agents/<id>)
WORKFLOW_ID = "hakjagum-grant"  # agent_runs.agent_id (제품 경로 증거 조회 키)
TAG = "hakjagum_product_cycle"
CYCLES = int(os.environ.get("HAKJAGUM_SMOKE_CYCLES", "1"))

# 결의구분 학자금신청서 코드 — hakjagum_probe.py 실측(2026-07-15): 라벨 "학자금신청서"=value "56"
# (경조금신청서 55 바로 다음). 삭제 가드레일이 이 코드로 우리 전표를 식별한다.
HAKJAGUM_FG = "56"
GUBUN_LABEL = "학자금신청서"

PROJECT_NAME = "포장개선"  # 1310|1310 — 코드피커 검색이 라이브 검증된 유일 코드(사이클 공용)

# 사이클별 baseAmount 정액 표 — 학자금은 근속 감액 규칙이 없어 정액이 그대로 저장돼야 한다
# (expected=base). 경조금 _CYCLE_PLAN 의 금액 축을 유지하되 under1Year 축은 없다.
_CYCLE_PLAN: list[int] = [
    100001,
    84000,
    300001,
    125000,
    250001,
    99999,
    71001,
    200002,
    133333,
    64001,
]


def _plan(cycle: int) -> dict:
    """`_CYCLE_PLAN` 표에서 baseAmount 결정 — 표보다 사이클이 많으면 순환."""
    base_amount = _CYCLE_PLAN[(cycle - 1) % len(_CYCLE_PLAN)]
    return {
        "date": TODAY,
        "baseAmount": base_amount,
        "expected_supply": base_amount,  # 감액 규칙 없음 — 정액 그대로 공급가액
    }


async def _fill(page, plan: dict) -> None:
    """실행 전 입력 폼을 **실제 위젯 조작**으로 채운다(코드 주입 없음)."""
    await set_date(page, "회계일", plan["date"])
    await page.locator("#hj-base-amount").fill(str(plan["baseAmount"]))
    await pick_combo(page, page.locator("body"), 0, PROJECT_NAME, PROJECT_NAME)
    print(f"[P1] 학자금={plan['baseAmount']} → 기대 공급가액={plan['expected_supply']}", flush=True)


def _verify(plan: dict, vd: dict) -> dict:
    """저장 결과 대조 — 단건 행수(=1)·공급가액(정액 그대로)·거래처(본인)·합계."""
    det = vd.get("detail") or {}
    rows = det.get("rows") or []
    actual_supply = as_int(rows[0].get("SPPRC_AMT2")) if rows else None
    actual_partner = str(rows[0].get("PARTNER_NM") or "").strip() if rows else ""
    actual_note = str(rows[0].get("NOTE_DC") or "").strip() if rows else ""
    total = as_int((vd.get("master") or {}).get("DETAIL_SUM_AMT"))
    rows_clean = det.get("n") == 1
    return {
        "detail_rowcount": det.get("n"),
        "rows_clean": rows_clean,
        "expected_supply": plan["expected_supply"], "actual_supply": actual_supply,
        "amount_match": rows_clean and actual_supply == plan["expected_supply"],
        "expected_partner": USERID, "actual_partner": actual_partner,
        "partner_match": rows_clean and actual_partner == USERID,
        "actual_note": actual_note,  # 적요는 서버가 본인 이름으로 자동 지정 — 관측만 남긴다.
        "expected_total": plan["expected_supply"], "actual_total": total,
        "total_match": total == plan["expected_supply"],
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
        gubun_label=GUBUN_LABEL, fg_code=HAKJAGUM_FG, tag=f"{TAG}_c{cycle}",
        pick_master=lambda rows: _pick_master(rows, plan["expected_supply"]), want_detail=saved,
    )
    checks = _verify(plan, vd) if saved else {}
    ok = bool(
        saved and run.get("run_recorded") and run.get("db_status") == "succeeded"
        and vd.get("deleted") and checks.get("rows_clean") and checks.get("amount_match")
        and checks.get("partner_match") and checks.get("total_match")
    )
    return {"cycle": cycle, "ok": ok, "run_ms": run_ms, "plan": plan,
            "run": run, "delete": vd, "checks": checks}


def _report(i: int, c: dict) -> None:
    p = c.get("plan") or {}
    k = c.get("checks") or {}
    mark = "PASS" if c.get("ok") else "FAIL"
    print(f"[CYCLE {i}] {mark} run={c.get('run_ms', 0) / 1000:.1f}s | "
          f"학자금={p.get('baseAmount')} 기대공급가액={p.get('expected_supply')}", flush=True)
    print(f"  {summarize_run(c)}", flush=True)
    if k:
        print(f"  checks: rows={k.get('detail_rowcount')}/1 clean={k.get('rows_clean')} "
              f"amount={k.get('amount_match')}(기대 {k.get('expected_supply')}·실제 {k.get('actual_supply')}) "
              f"partner={k.get('partner_match')}(실제 {k.get('actual_partner')!r}) "
              f"note={k.get('actual_note')!r} "
              f"total={k.get('total_match')}(기대 {k.get('expected_total')}·실제 {k.get('actual_total')})", flush=True)
    if (c.get("run") or {}).get("error"):
        print(f"  run error: {c['run']['error']}", flush=True)
    if (c.get("run") or {}).get("fail_reason"):
        print(f"  fail reason: {c['run']['fail_reason']}", flush=True)


async def main() -> None:
    print(f"[SMOKE] 삭제 격리: 결의구분 {HAKJAGUM_FG}(학자금신청서) 전표만 대상 — "
          "국내53·해외54·경조55 는 건드리지 않는다.", flush=True)
    code = await run_cycles(
        title="HAKJAGUM PRODUCT SAVE-CYCLE", cycles=CYCLES, tag=TAG,
        run_one=_run_one, report_line=_report,
    )
    sys.exit(code)


if __name__ == "__main__":
    asyncio.run(main())
