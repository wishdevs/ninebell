"""외상매출금(voucher-receivable) 라이브 스모크 — **제품 경로**(대시보드 폼 → 실행)로 실행한다.

전환(사용자 지시 2026-08-03: "결의서와 동일하게 시스템에서 등록하고 erp에서 제거해야함"):
종전에는 `build_voucher_receivable_graph()` + `run_workflow()` 를 파이썬이 직접 호출해
**러너까지만** 탔다 — 프론트 pre-run 폼(`VoucherPreRunForm`)·`runs.py` collect·세션/SSE/재연결·
`agent_runs` 기록이 전부 미검증이었다. 이제 결의서입력 4종과 같은 구조로 제품 UI 를 몬다.

⚠ 다만 **ERP 에서 제거할 것은 없다** — 이 계열은 전표를 생성하지 않는다(기존 전표 조회·결재
아키타입, 화면에 F6 삭제 자체가 없다: `voucher_receivable/PROCESS.md:29`). 결의서입력의
'작성 → F6 삭제' 사이클을 흉내내면 되돌릴 수단이 없다. 대신 **부작용을 만들지 않는 것**이
정리에 해당한다(아래 phase0).

관측 경로(종전 프레임 직접 수신의 대체 — 자세한 설계는 `e2e/voucher_product.py` 모듈 docstring):
  · 로그 기반 어설션 → `agent_runs.logs`(세션이 영속한 log/step 프레임) 파싱.
  · 스크린샷/자식창 닫힘 → 제품 프론트가 받는 SSE 본문을 tee 해 세는 in-page 탭.

phase0(기간 선별): 제품 폼에는 max_rows 노브가 없고 서버 기본값은 **전체 진행**이라, 기간을
그대로 두면 결제창을 그 건수만큼 열어 EAP 임시문서가 쌓인다(실측: 2026-07~08 매출 177건).
읽기 전용 조회로 기간을 **이분 탐색**해 대상이 1~3건인 부분기간을 실측으로 찾아 폼에 넣는다
(날짜 필드를 추정하지 않는 이유는 `voucher_product.py` docstring 참조).

⚠⚠ 정책 전환(2026-08-07) ⚠⚠ 이 스모크는 **실제 상신**을 수행한다(allow_submit 게이트 개방).
상신된 전표는 e2e/eap_approval_cancel_probe.py(결재취소→상신취소→삭제)로 회수한다.
보관은 여전히 절대 미클릭(그래프가 보장 — 여기선 관찰만). 그래프를 조립하지
않고 제품이 등록한 워크플로우를 제품 UI 로 실행할 뿐이다.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/voucher_receivable_smoke.py
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

# 병합(2026-08-20): 외상매출금 에이전트는 '유형별 전표조회 승인'(voucher-by-type)으로 통합됐다.
# 이 스모크는 그 에이전트를 **국내매출+해외매출 선택**으로 실행하는 시나리오다 — 실행 전 폼에
# 전표유형 다중 선택이 생겼으므로, fill 단계에서 두 유형을 선택해야 한다(아래 TODO).
AGENT_ID = "voucher-by-type"  # 대시보드 에이전트 상세 URL(/agents/<id>)
WORKFLOW_ID = "voucher-by-type"  # agent_runs.agent_id (제품 경로 증거 조회 키)
TAG = "voucher_receivable_product"
DOCU_TYPES = v_steps.DOCU_TYPES_RECEIVABLE  # ("국내매출", "해외매출")


async def main() -> int:
    print("[SMOKE] 외상매출금 — 제품 경로(대시보드 폼 → 실행). ERP 삭제 단계 없음(전표 미생성).",
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
    if scan["target_rows"] > MAX_TARGET_ROWS:
        print(
            f"[ABORT] 가장 적은 하루도 {scan['target_rows']}건(상한 {MAX_TARGET_ROWS}) — "
            f"실행하면 EAP 임시문서가 그만큼 생긴다. 분포={scan['by_day']}",
            flush=True,
        )
        return 2
    p_from, p_to = iso(scan["picked_from"]), iso(scan["picked_to"])
    print(f"[SMOKE] 선별 기간 {p_from} ~ {p_to} (대상 {scan['target_rows']}건)", flush=True)

    # ── phase1 — 제품 UI 완주 ────────────────────────────────────────────────────
    async def fill(page) -> None:
        await fill_period(page, p_from, p_to)
        # TODO(voucher-by-type 병합 2026-08-20): 실행 전 폼의 전표유형 다중 선택에서
        # **국내매출+해외매출**을 선택하는 스텝을 프론트 폼 셀렉터 확정 후 추가할 것 —
        # 미선택 실행은 폼 기본 선택으로 돈다(파라미터 계약: params.voucher.docu_types).

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

    # 자식창 회계는 loop_approvals 구간으로 한정 — 결제창이 아닌 코드도우미 팝업이
    # '결제창을 열었다'로 오판되지 않게 한다(종전 하네스의 in_loop_approvals 게이팅과 동일).
    win = loop_window(tap)
    child_shot_in_loop = count_in_window(tap.get("childShotSeqs"), win)
    child_closed_in_loop = count_in_window(tap.get("childClosedSeqs"), win)

    # ── 아티팩트 ────────────────────────────────────────────────────────────────
    if tap.get("lastParentShot"):
        save_data_url_png(tap["lastParentShot"], ART / f"{TAG}_parent.png")
    if tap.get("lastChildShot"):
        save_data_url_png(tap["lastChildShot"], ART / f"{TAG}_child.png")
    else:
        print("[artifact] 자식(결제창) 스크린샷 없음 — 핵심 실패 신호", flush=True)

    rowcount = obs["rowcount"]
    processed = obs["processed_docu_nos"]

    # ── 어설션 ──────────────────────────────────────────────────────────────────
    checks: dict[str, bool] = {}
    # P — 제품 경로 증거(종전 하네스엔 없던 항목: 그래프 직접 호출은 런을 남기지 않는다).
    checks["product_path_run_recorded"] = bool(run.get("run_recorded"))
    checks["db_status_succeeded"] = run.get("db_status") == "succeeded"
    checks["ui_terminal_reached"] = bool(run.get("terminal")) and run.get("ui_status") == "succeeded"
    checks["sse_stream_observed"] = int(tap.get("connects") or 0) >= 1
    # 폼이 고른 기간이 서버 권위 params 로 실제 반영됐는가(폼→runs.py→그래프 계약).
    checks["form_period_applied"] = bool(
        obs["params_log"] and p_from in obs["params_log"] and p_to in obs["params_log"]
    )
    checks["docu_type_maechul_set_ok"] = (
        steps.get("set_query") == "done"
        and obs["set_query_ok_log"] is not None
        and "국내매출" in obs["set_query_ok_log"]
        and "해외매출" in obs["set_query_ok_log"]
    )
    checks["rowcount_observed"] = rowcount is not None
    # 종전 `final_result_success_no_error`(result 프레임 + error 프레임 0)의 대체.
    checks["final_result_success_no_error"] = (
        bool(run.get("result_text") or tap.get("result")) and not (tap.get("errors") or [])
    )
    # 안전 감시 — 결과 문구가 상신 완료(또는 대상 없음)를 선언한다.
    result_text = str(tap.get("result") or run.get("result_text") or "")
    checks["result_declares_submit_done"] = (
        "전자결재 상신 완료" in result_text or "대상 전표가 없어" in result_text
    )
    # 안전 감시 — 보관 클릭 흔적은 어떤 경우에도 없어야 한다(상신은 정상 경로).
    checks["no_archive_clicked_logged"] = not any("보관 클릭" in m for m in msgs)
    # D7 — 확정 불일치 0(있으면 그래프가 이미 중단시킨다 — 여기서 재확인).
    checks["d7_no_confirmed_mismatch"] = len(obs["d7_mismatch"]) == 0
    checks["d7_docu_nos_distinct"] = len(set(processed)) == len(processed)
    # 종전 `d7_processed_matches_request`(== max_rows)의 대체:
    # 제품 폼엔 max_rows 노브가 없고 서버 기본이 **전체 진행**이라, 처리 건수는 조회 건수와
    # 정확히 같아야 한다(조용히 새거나 덜 도는 것을 잡는다 — 판정 기준 교체, 완화 아님).
    checks["processed_matches_rowcount"] = (rowcount is not None) and len(processed) == rowcount
    # EAP draft 예산 — draft 는 **결제창을 연 횟수**만큼 생긴다(묶음 결재는 1회에 N건 처리).
    # 선별한 하루의 대상 건수를 넘겨 열리지 않았는지 본다.
    checks["draft_budget_respected"] = obs["approval_opens"] <= MAX_TARGET_ROWS

    if rowcount == 0:
        checks["zero_rows_no_child_opened"] = (
            child_shot_in_loop == 0 and child_closed_in_loop == 0 and not processed
        )
    else:
        checks["submit_log_with_docu_no"] = bool(obs["virtual_submit_logs"]) and bool(processed)
        # 종전 `child_screenshot_emitted` — SSE 탭으로 관측(러너 방출수가 아니라 **브라우저 도달**).
        checks["child_screenshot_emitted"] = child_shot_in_loop >= 1
        # 종전 `child_closed_frame_emitted` / `d7_child_closed_at_least_once`.
        # closed 프레임은 커서 버퍼라 유실 없이 도달한다(스크린샷과 달리 합쳐지지 않는다).
        checks["child_closed_frame_emitted"] = child_closed_in_loop >= 1
        # 연 만큼만 닫혔다 — 결제창 개봉 횟수(=EAP draft 수)와 닫힘 전이 수가 일치해야 한다.
        checks["closed_child_matches_opens"] = child_closed_in_loop == obs["approval_opens"]

    ok = print_checks(checks)

    print("\n===== 관측 상세 =====", flush=True)
    print(f"기간 선별      = {scan['picked_from']}~{scan['picked_to']} (실측 {scan['target_rows']}건) "
          f"· 월스캔 {scan['windows']} · 이분탐색 {scan['queries']}", flush=True)
    print(f"agent_runs     = id={run_id} status={run.get('db_status')} "
          f"logs={len(logs)}줄 (SSE 로그 {len(tap.get('logs') or [])}줄)", flush=True)
    print(f"steps          = {steps}", flush=True)
    print(f"rowcount       = {rowcount} · batch_mode={obs['batch_mode']} "
          f"· 결제창 개봉(=EAP draft) {obs['approval_opens']}회", flush=True)
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
