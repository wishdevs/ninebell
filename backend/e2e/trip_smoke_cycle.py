"""출장(국내/자차) 실저장 사이클 스모크 — **제품 경로**(대시보드 폼→실행)로 작성 → ERP 에서 삭제.

전환(사용자 지시 2026-08-03): 종전에는 스크립트가 `build_trip_domestic_graph()` 를 직접
`ainvoke` 해서 **ERP 에서 작성하고 ERP 에서 지웠다** — 프론트 pre-run 폼·`runs.py` collect 의
서버 권위 params 주입(department·cost_type·fuel_*)·러너(세마포어·SSE·스크린캐스트·시간예산
워치독)·agent_runs 기록이 전부 미검증이었다. 게다가 스크립트가 params 를 손으로 조립하다
프로덕션 계약과 어긋나 **3주간 로그인조차 못 했다**(행별 invoiceDate 누락).

이제 법인카드 e2e(`e2e/e2e_smoke.py`)와 같은 2페이즈다:
  phase1 — 대시보드(:3101) 로그인 → /agents/trip-domestic → **실행 전 입력 폼을 실제 DOM 으로
           채우고**(행 추가·유형 셀렉트·달력·거래처/프로젝트 콤보박스) 실행 → 종료 대기.
           ⚠ params 를 코드로 주입하지 않는다. department·cost_type·fuel_unit_price·
           fuel_classes 는 **서버(runs.py)가 채우는 권위 키**라 스크립트가 넘기지 않는다.
  phase2 — 별도 브라우저로 ERP 직접 로그인 → GLDDOC00300 → 결의구분 '출장(국내·자차)' 조회 →
           3중 가드 → 상세 대조 → F6 → 잔존 0.

폼이 넣는 값은 종전 `_cycle_params` 와 업무적으로 동등하다(통행료 1~2행 + 유류비 1행,
거래처 한국도로공사, 프로젝트 포장개선, 적요 기본 문구).

⚠ 안전 수칙
  - **삭제까지가 한 사이클** — 삭제 검증(잔존 0) 없이는 다음 사이클 진행 금지.
  - **상신(결재) 절대 금지** — F7(저장)·F6(삭제)만.
  - 삭제 3중 가드: 결의자(WRT_EMP_NM)=로그인계정 + 결의구분(ABDOCU_FG_CD)=53 + 미결(DOCU_NO 공백).
    **완화 금지** — 하나라도 안 맞으면 삭제 중단·보고.

Usage: cd backend && TRIP_SMOKE_CYCLES=1 .venv/bin/python e2e/trip_smoke_cycle.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

# 진단 로그 가시화 — 독립 실행 e2e 는 root 기본값(WARNING)이라 INFO 진단이 통째로 유실된다.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")

from app.agents.trip_domestic.params import fuel_support_amount  # noqa: E402
from app.services.agent_settings import effective_settings  # noqa: E402
from e2e.product_cycle import (  # noqa: E402
    TODAY,
    USERID,
    add_row,
    as_int,
    erp_verify_and_delete,
    pick_combo,
    row_scope,
    run_cycles,
    run_product,
    set_date,
    set_select,
    summarize_run,
)

AGENT_ID = "trip-domestic"  # 대시보드 에이전트 상세 URL(/agents/<id>)
WORKFLOW_ID = "trip-domestic"  # agent_runs.agent_id (제품 경로 증거 조회 키)
TAG = "trip_product_cycle"
CYCLES = int(os.environ.get("TRIP_SMOKE_CYCLES", "10"))

TRIP_FG = "53"  # 결의구분 출장(국내·자차) 코드(P1 실측)
GUBUN_LABEL = "출장(국내·자차)"  # 가운뎃점 `·` — 슬래시 아님

PROJECT_NAME = "포장개선"  # 1310|1310 — 코드피커 검색이 라이브 검증된 유일 코드(사이클 공용)
PARTNER_NAME = "한국도로공사"  # 10512 — 이 계정 '자주쓰는' 거래처
TOLL_NOTE = "통행료(현금)"
FUEL_NOTE = "국내출장 자차 유류비 지원"

# 차량종류·유류단가는 **서버 권위 키**라 params 로 넘기지 않는다. 다만 기대 금액을 계산해야 하므로
# 서버와 동일한 실효 설정(DB 저장값 없음 → 스키마 기본값)을 미러로 읽는다(주입 아님, 대조용).
_SETTINGS: dict = effective_settings(WORKFLOW_ID, None)
_CAR_CLASSES = [(str(c["id"]), str(c["label"])) for c in _SETTINGS["fuel_classes"]]


def _plan(cycle: int) -> dict:
    """사이클별 입력 계획 — 종전 `_cycle_params` 와 업무적으로 동등(통행료 1~2행 + 유류비 1행)."""
    toll_n = 1 + (cycle % 2)
    tolls = [
        {"amount": 12000 + cycle * 500 + j * 3300, "note": TOLL_NOTE} for j in range(toll_n)
    ]
    car_id, car_label = _CAR_CLASSES[cycle % len(_CAR_CLASSES)]
    km = 50 + (cycle * 25) % 251
    fuel_amount = fuel_support_amount(km, car_id, _SETTINGS)
    amounts = [t["amount"] for t in tolls] + [fuel_amount]
    return {
        "date": TODAY,
        "toll_n": toll_n,
        "tolls": tolls,
        "car_id": car_id,
        "car_label": car_label,
        "km": km,
        "fuel_amount": fuel_amount,
        "rows": toll_n + 1,
        "amounts": amounts,
        "notes": [t["note"] for t in tolls] + [FUEL_NOTE],
        # 통행료 행은 카탈로그 거래처, 유류비 행은 작성자 본인(런타임 본인이름 검색).
        "partners": [PARTNER_NAME] * toll_n + [USERID],
        "total": sum(amounts),
    }


async def _fill(page, plan: dict) -> None:
    """실행 전 입력 폼을 **실제 위젯 조작**으로 채운다(코드 주입 없음)."""
    rows = plan["rows"]
    for _ in range(rows - 1):
        await add_row(page)  # 새 행은 직전 행과 같은 유형(통행료)으로 추가된다
    # 유형 전환은 금액·적요·거래처를 초기화하므로 **채우기 전에** 마지막 행을 유류비로 바꾼다.
    await set_select(page, row_scope(page, rows), "행 유형", "유류비 지원")

    for i, toll in enumerate(plan["tolls"], start=1):
        scope = row_scope(page, i)
        await set_date(page, f"{i}행 계산서일", plan["date"])
        await pick_combo(page, scope, 0, PROJECT_NAME, PROJECT_NAME)  # 프로젝트
        await pick_combo(page, scope, 1, PARTNER_NAME, PARTNER_NAME)  # 거래처
        await scope.get_by_label(f"{i}행 금액(공급가액)").fill(str(toll["amount"]))
        await scope.get_by_label(f"{i}행 적요").fill(toll["note"])
        print(f"[P1] {i}행(통행료) amount={toll['amount']}", flush=True)

    i = plan["rows"]
    scope = row_scope(page, i)
    await set_date(page, f"{i}행 계산서일", plan["date"])
    await pick_combo(page, scope, 0, PROJECT_NAME, PROJECT_NAME)
    await set_select(page, scope, "차량종류", plan["car_label"])
    await scope.get_by_label(f"{i}행 주행거리").fill(str(plan["km"]))
    await scope.get_by_label(f"{i}행 적요").fill(FUEL_NOTE)
    print(f"[P1] {i}행(유류비) {plan['car_label']}/{plan['km']}km → 기대 {plan['fuel_amount']}원", flush=True)


def _verify(plan: dict, vd: dict) -> dict:
    """저장 결과 대조 — 행수·행별 금액·거래처·적요·합계(기존 스크립트 검증 수준 유지·강화)."""
    det = (vd.get("detail") or {})
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


async def _run_one(cycle: int) -> dict:
    plan = _plan(cycle)
    t0 = time.monotonic()
    run = await run_product(
        agent_id=AGENT_ID,
        workflow_id=WORKFLOW_ID,
        fill=lambda page: _fill(page, plan),
        tag=f"{TAG}_c{cycle}",
    )
    run_ms = int((time.monotonic() - t0) * 1000)
    saved = bool(run.get("terminal") and run.get("ui_status") == "succeeded")
    # 실패해도 phase2 는 반드시 돈다 — 반쯤 저장된 전표가 남지 않았는지 확인해야 한다.
    vd = await erp_verify_and_delete(
        gubun_label=GUBUN_LABEL,
        fg_code=TRIP_FG,
        tag=f"{TAG}_c{cycle}",
        pick_master=lambda rows: _pick_master(rows, plan["total"]),
        want_detail=saved,
    )
    checks = _verify(plan, vd) if saved else {}
    ok = bool(
        saved
        and run.get("run_recorded")
        and run.get("db_status") == "succeeded"
        and vd.get("deleted")
        and checks.get("rows_clean")
        and checks.get("amount_match")
        and checks.get("note_match")
        and checks.get("partner_match")
        and checks.get("total_match")
    )
    return {"cycle": cycle, "ok": ok, "run_ms": run_ms, "plan": plan,
            "run": run, "delete": vd, "checks": checks}


def _pick_master(rows: list[dict], expected_total: int) -> int:
    """방금 저장한 문서의 마스터 인덱스 — 합계가 일치하는 행 우선, 없으면 마지막 행."""
    for i, r in enumerate(rows):
        if as_int(r.get("DETAIL_SUM_AMT")) == expected_total:
            return i
    return len(rows) - 1


def _report(i: int, c: dict) -> None:
    p = c.get("plan") or {}
    k = c.get("checks") or {}
    mark = "PASS" if c.get("ok") else "FAIL"
    print(f"[CYCLE {i}] {mark} run={c.get('run_ms', 0) / 1000:.1f}s | 통행료{p.get('toll_n')}행"
          f"+유류비({p.get('car_id')}/{p.get('km')}km) 합계={p.get('total')}", flush=True)
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
    code = await run_cycles(
        title="TRIP(국내·자차) PRODUCT SAVE-CYCLE",
        cycles=CYCLES,
        tag=TAG,
        run_one=_run_one,
        report_line=_report,
    )
    sys.exit(code)


if __name__ == "__main__":
    asyncio.run(main())
