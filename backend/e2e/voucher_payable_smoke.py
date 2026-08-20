"""외상매입금(voucher-payable) 라이브 스모크 — **제품 경로**(대시보드 폼 → 실행)로 실행한다.

형제 스모크 `e2e/voucher_receivable_smoke.py` 와 동일 구조이며 전표유형만 **내수구매**
(SYSDEF_CD=31, `DOCU_TYPES_PAYABLE`)로 다르다 — 공유 백본(`build_voucher_graph`)이 매입에도
제품 경로로 종단 동작하는지 확인한다. 매출과 동일한 **배치 결재**(2026-08-07 확대: 하위
200건 기준 단독/묶음)라 결제창 개봉 수 = 묶음 수(≤ 처리 건수)다.

전환 배경·관측 경로(agent_runs.logs + SSE 탭)·기간 선별(phase0)은 `e2e/voucher_product.py`
모듈 docstring 참조. ERP 삭제 단계는 없다(전표 미생성 아키타입).

D2 검증: 전표유형 내수구매가 조회폼에 세팅됐는지 — set_query 스텝 상태 + "조회 조건 세팅
완료(…전표유형 내수구매)" 로그.
D3 검증: 조회 rowcount. **0건도 정상**(내수구매 미결·저장 전표가 선별 기간에 없을 수 있음) —
그 경우 결제창 loop 는 스킵되고 정상 종료된다.

⚠⚠ 정책 전환(2026-08-07) ⚠⚠ 이 스모크는 **실제 상신**을 수행한다(allow_submit 게이트 개방).
상신된 전표는 e2e/eap_approval_cancel_probe.py(결재취소→상신취소→삭제)로 회수한다.
보관은 여전히 절대 미클릭(그래프가 보장 — 여기선 관찰만).

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/voucher_payable_smoke.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")

from app.agents.voucher_receivable import steps as v_steps  # noqa: E402
from e2e.product_cycle import run_product  # noqa: E402
from e2e.voucher_product import (  # noqa: E402
    ART,
    MAX_TARGET_ROWS,
    SSE_TAP_JS,
    count_in_window,
    db_run_logs,
    fill_period,
    iso,
    log_messages,
    loop_window,
    parse_common,
    pick_period,
    print_checks,
    read_tap,
    save_data_url_png,
    step_status,
)

# 병합(2026-08-20): 외상매입금 에이전트는 '유형별 전표조회 승인'(voucher-by-type)으로 통합됐다.
# 이 스모크는 그 에이전트를 **내수구매만 선택**해 실행하는 시나리오다 — 실행 전 폼에
# 전표유형 다중 선택이 생겼으므로, fill 단계에서 내수구매를 선택해야 한다(아래 TODO).
AGENT_ID = "voucher-by-type"
WORKFLOW_ID = "voucher-by-type"
TAG = "voucher_payable_product"
DOCU_TYPES = v_steps.DOCU_TYPES_PAYABLE  # ("내수구매",)


async def main() -> int:
    print("[SMOKE] 외상매입금 — 제품 경로(대시보드 폼 → 실행). ERP 삭제 단계 없음(전표 미생성).",
          flush=True)
    print("[SMOKE] ⚠ 실제 상신 수행(정책 전환 2026-08-07) — 종료 후 eap_approval_cancel_probe 로 회수할 것.", flush=True)

    # ── phase0 — 읽기 전용 기간 선별(결재 버튼 미클릭 → EAP draft 0건) ──────────────
    scan = await pick_period(DOCU_TYPES, tag=TAG)
    if scan.get("error"):
        print(f"[ABORT] 기간 선별 실패 — {scan['error']}", flush=True)
        return 2
    if not scan.get("picked_from"):
        print(f"[ABORT] 최근 {len(scan['windows'])}개월에 대상 전표가 없습니다 — {scan['windows']}",
              flush=True)
        return 2
    p_from, p_to = iso(scan["picked_from"]), iso(scan["picked_to"])
    print(f"[SMOKE] 선별 기간 {p_from} ~ {p_to} (대상 {scan['target_rows']}건)", flush=True)

    # ── phase1 — 제품 UI 완주 ────────────────────────────────────────────────────
    async def fill(page) -> None:
        await fill_period(page, p_from, p_to)
        # TODO(voucher-by-type 병합 2026-08-20): 실행 전 폼의 전표유형 다중 선택에서 **내수구매만**
        # 선택하는 스텝을 프론트 폼 셀렉터 확정 후 추가할 것 — 미선택 실행은 폼 기본 선택으로
        # 돌아 이 스모크의 '내수구매 한정' 시나리오가 깨진다(파라미터 계약: params.voucher.docu_types).

    run = await run_product(
        agent_id=AGENT_ID,
        workflow_id=WORKFLOW_ID,
        fill=fill,
        tag=TAG,
        init_script=SSE_TAP_JS,
        on_page_done=read_tap,
    )
    tap = run.get("page_probe") or {}
    run_id = (run.get("run_after") or {}).get("id")
    logs = db_run_logs(run_id) if run.get("run_recorded") and run_id else []
    msgs = log_messages(logs)
    steps = step_status(logs)
    obs = parse_common(msgs)

    win = loop_window(tap)
    child_shot_in_loop = count_in_window(tap.get("childShotSeqs"), win)
    child_closed_in_loop = count_in_window(tap.get("childClosedSeqs"), win)

    if tap.get("lastParentShot"):
        save_data_url_png(tap["lastParentShot"], ART / f"{TAG}_parent.png")
    if tap.get("lastChildShot"):
        save_data_url_png(tap["lastChildShot"], ART / f"{TAG}_child.png")

    rowcount = obs["rowcount"]
    processed = obs["processed_docu_nos"]

    # ── 어설션 ──────────────────────────────────────────────────────────────────
    checks: dict[str, bool] = {}
    checks["product_path_run_recorded"] = bool(run.get("run_recorded"))
    checks["db_status_succeeded"] = run.get("db_status") == "succeeded"
    checks["ui_terminal_reached"] = bool(run.get("terminal")) and run.get("ui_status") == "succeeded"
    checks["sse_stream_observed"] = int(tap.get("connects") or 0) >= 1
    checks["form_period_applied"] = bool(
        obs["params_log"] and p_from in obs["params_log"] and p_to in obs["params_log"]
    )
    # D2 — 전표유형 내수구매가 실제로 세팅됐다(공유 코드가 이 값을 썼다는 증거).
    checks["docu_type_naesugumae_set_ok"] = (
        steps.get("set_query") == "done"
        and obs["set_query_ok_log"] is not None
        and "내수구매" in obs["set_query_ok_log"]
    )
    # D3 — 조회(F2)가 실행돼 rowcount 를 읽었다(0건도 정상).
    checks["rowcount_observed"] = rowcount is not None
    checks["final_result_success_no_error"] = (
        bool(run.get("result_text") or tap.get("result")) and not (tap.get("errors") or [])
    )
    result_text = str(tap.get("result") or run.get("result_text") or "")
    checks["result_declares_submit_done"] = (
        "전자결재 상신 완료" in result_text or "대상 전표가 없어" in result_text
    )
    checks["no_archive_clicked_logged"] = not any("보관 클릭" in m for m in msgs)
    checks["d7_no_confirmed_mismatch"] = len(obs["d7_mismatch"]) == 0
    checks["draft_budget_respected"] = obs["approval_opens"] <= MAX_TARGET_ROWS

    if rowcount == 0:
        # 0건 경로 — 결제창을 한 번도 열지 않고 정상 종료한다.
        checks["zero_rows_no_loop_attempted"] = (
            child_shot_in_loop == 0 and child_closed_in_loop == 0 and not processed
        )
    else:
        checks["child_screenshot_emitted"] = child_shot_in_loop >= 1
        checks["child_closed_frame_emitted"] = child_closed_in_loop >= 1
        checks["submit_log_with_docu_no"] = bool(obs["virtual_submit_logs"]) and bool(processed)
        # 배치 결재 — 묶음 수와 무관하게 **처리 전표 수** = 조회 건수(전량 커버).
        checks["processed_matches_rowcount"] = len(processed) == rowcount
        checks["processed_docu_nos_distinct"] = len(set(processed)) == len(processed)
        checks["closed_child_matches_opens"] = child_closed_in_loop == obs["approval_opens"]

    ok = print_checks(checks)

    print("\n===== 관측 상세 =====", flush=True)
    print(f"기간 선별      = {scan['picked_from']}~{scan['picked_to']} (실측 {scan['target_rows']}건) "
          f"· 월스캔 {scan['windows']} · 이분탐색 {scan['queries']}", flush=True)
    print(f"agent_runs     = id={run_id} status={run.get('db_status')} "
          f"logs={len(logs)}줄 (SSE 로그 {len(tap.get('logs') or [])}줄)", flush=True)
    print(f"steps          = {steps}", flush=True)
    print(f"set_query_log  = {obs['set_query_ok_log']!r}", flush=True)
    print(f"rowcount       = {rowcount} · 결제창 개봉(=EAP draft) {obs['approval_opens']}회", flush=True)
    print(f"opened/processed = {obs['opened_docu_nos']} / {processed}", flush=True)
    print(f"child(loop 구간) shot={child_shot_in_loop} closed={child_closed_in_loop} "
          f"· 전역 shot={tap.get('shotChild')} closed={tap.get('childClosed')}", flush=True)
    print(f"d7_ok={len(obs['d7_ok'])} soft={len(obs['d7_soft'])} mismatch={len(obs['d7_mismatch'])} "
          f"checked_ok={len(obs['d7_checked_ok'])} checked_soft={len(obs['d7_checked_soft'])}",
          flush=True)
    print(f"result         = {result_text!r}", flush=True)
    if run.get("error") or run.get("fail_reason"):
        print(f"run.error      = {run.get('error')} / {run.get('fail_reason')}", flush=True)

    report = ART / f"{TAG}.json"
    report.write_text(
        json.dumps(
            {"scan": scan, "run": {k: v for k, v in run.items() if k != "page_probe"},
             "checks": checks, "observed": obs, "steps": steps,
             "child": {"shot_in_loop": child_shot_in_loop, "closed_in_loop": child_closed_in_loop,
                       "global_shot": tap.get("shotChild"), "global_closed": tap.get("childClosed")},
             "db_logs": logs},
            ensure_ascii=False, indent=1,
        ),
        encoding="utf-8",
    )
    print(f"\n리포트: {report}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
