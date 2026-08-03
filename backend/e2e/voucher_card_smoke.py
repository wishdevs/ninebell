"""미지급금 법인카드(voucher-card) 라이브 스모크 — **제품 경로**(대시보드 폼 → 실행)로 실행한다.

형제 스모크(외상매출금/매입금)와 같은 제품 경로 구조에, 카드 고유 델타 3가지를 추가로
파싱·검증한다:

  Δ1  전표유형 = **일반**            (공유 set_query 를 DOCU_TYPES_CARD 로 재사용)
  Δ2  **결의서조회승인(GLDDOC00400) 2nd 메뉴 탭** 진입 → 결의부서 전체·결의자 비움·회계일·
      결의구분=카드 필터로 일괄 조회 → `ABDOCU_NO→GWDOCU_NO(결재번호)` 맵 수집 → 탭 복귀
                                                        (nodes/collect_payments.py)
  Δ3  결제창(EAP) 안 **참조문서 선택** — 문서번호=이 행의 GWDOCU_NO 로 조회 → 1건이면 선택 →
      아래(↓) 버튼으로 '선택된 문서 목록' 이동          (nodes/reference_doc.py)

⚠⚠ 이 스모크가 **어디서 멈추는가** ⚠⚠
회계전표 계열은 전표를 **생성하지 않고** 기존 전표를 조회·검증하며, ERP 에 삭제 로직이 없다 —
결의서입력 계열의 '실저장(F7)→검증→삭제(F6)' 사이클을 흉내내면 되돌릴 방법이 없다. 그래서 이
스모크는 `ACTIONS.md` 기준 **`확정`·`발신` 등급 동사를 한 번도 실행하지 않는 지점**에서 멈춘다.
카드 `FLOW.md` 의 `금지` 둘 —

  금지  [문서반영]  참조문서 확인 — 미클릭 (기록만)
  금지  [상신]      미클릭 — '가상 상신' 기록만

— 은 그래프 코드가 보장하고(`make_reference_doc_hook(allow_confirm=False)` + `loop_approvals`
의 read/close-only 규율), 이 스모크는 **관찰만** 한다. 게이트를 여는 인자를 넘기지 않는 정도가
아니라 **아예 그래프를 조립하지 않는다** — 제품이 등록한 워크플로우를 제품 UI 로 실행할 뿐이다.

되돌릴 수 없는 부작용: **0건**. 관찰되는 유일한 잔여물은 결제창을 여는 것만으로 생기는
**EAP 임시문서(draft)** 이며(PROCESS.md 기지 이슈), phase0 기간 선별로 결제창 개봉 횟수를
`MAX_TARGET_ROWS` 이하로 묶는다(제품 폼에 max_rows 노브가 없어 기간이 유일한 레버다).

전환 배경·관측 경로(agent_runs.logs + SSE 탭) 설계는 `e2e/voucher_product.py` docstring 참조.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/voucher_card_smoke.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")

from app.agents.voucher_card import steps as card_steps  # noqa: E402
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

AGENT_ID = "voucher-card-payable"
WORKFLOW_ID = "voucher-card"
TAG = "voucher_card_product"
DOCU_TYPES = card_steps.DOCU_TYPES_CARD  # ("일반",)

# ── 카드 고유 로그 파서 — 문구는 voucher_card 노드의 emit_log 원문과 1:1 ────────────
# collect_payments: "결재번호 수집 완료 — 결의서 12건 중 매핑 4건(ABDOCU_NO→GWDOCU_NO)."
_MAP_RE = re.compile(r"결재번호 수집 완료 — 결의서 (\d+)건 중 매핑 (\d+)건")
# loop_approvals(카드): "조회 9건 중 결의서번호 보유 4건 → 결재 대상 4건(결재번호 맵 32건, 매칭 4/4)."
_TARGETS_RE = re.compile(
    r"조회 (\d+)건 중 결의서번호 보유 (\d+)건 → 결재 대상 (\d+)건"
    r"\(결재번호 맵 (\d+)건, 매칭 (\d+)/(\d+)\)"
)
# 제외 요약: "결재 대상 제외 2건 — 결의서번호 없음(직접 전표) 1건 · 결재번호 맵에 없음 1건(전표 …)."
_EXCLUDED_RE = re.compile(r"결재 대상 제외 (\d+)건")
_EXC_NO_AB_RE = re.compile(r"결의서번호 없음\(직접 전표\) (\d+)건")
_EXC_UNMAPPED_RE = re.compile(r"결재번호 맵에 없음 (\d+)건")

# 참조문서 훅의 **종결 로그**(행당 정확히 하나) — 진단성 경고는 제외한다.
_REFDOC_TERMINAL = (
    ("attached_ok", "참조문서 첨부 완료"),
    ("attach_failed", "참조문서 첨부 실패"),
    ("zero_hits", "참조문서 검색 결과 0건"),
    ("multi_hits", "참조문서 검색 결과가"),
    ("unsettled", "참조문서 조회 결과를 확인하지 못했습니다"),
    ("search_not_run", "참조문서 '조회' 버튼을 누르지 못했습니다"),
    ("dialog_not_found", "참조문서 선택 버튼을 찾지 못했습니다"),
    ("no_payment_no", "참조문서 미검색 — 결재번호 미상"),
    ("row_select_failed", "참조문서 목록 행을 선택하지 못했습니다"),
)
# 진단(종결 아님) — 개수만 센다.
_REFDOC_DIAG = (
    ("panel_expand_warn", "참조문서 조회 조건 패널 확장을 확인하지 못했습니다"),
    ("docno_fill_warn", "참조문서 문서번호"),
    ("hits_confirmed", "참조문서 검색 "),
    ("attach_lost", "참조문서 첨부 직후엔 담겼으나"),
    ("hook_exception", "참조문서 처리 중 경고(무시하고 진행)"),
    ("virtual_confirm", "가상: 참조문서 확인·상신"),
    # ⚠ 절대 안전 감시 — 0이어야 한다. 1 이상이면 게이트가 열린 채 실행된 것이다.
    ("confirm_clicked", "참조문서 확인 클릭(allow_confirm=True)"),
)


def _classify_refdoc(msg: str) -> tuple[str, bool] | None:
    """참조문서 로그 → (분류키, 종결여부). 해당 없으면 None."""
    for key, needle in _REFDOC_TERMINAL:
        if needle in msg:
            return key, True
    for key, needle in _REFDOC_DIAG:
        if needle in msg:
            return key, False
    return None


def parse_card(msgs: list[str]) -> dict:
    """카드 델타 관측치 — 종전 프레임 파싱과 동일 문구·동일 의미로 `agent_runs.logs` 에서 재현."""
    out: dict = {
        "collect_map_n": None, "collect_map_size": None, "collect_skip_log": None,
        "targets_stat": None, "coverage_zero_warn": False,
        "excluded_log": None, "excluded_total": None,
        "excluded_no_ab": None, "excluded_unmapped": None,
        "refdoc_terminal": {}, "refdoc_diag": {}, "refdoc_logs": [],
    }
    for msg in msgs:
        mp = _MAP_RE.search(msg)
        if mp:
            out["collect_map_n"] = int(mp.group(1))
            out["collect_map_size"] = int(mp.group(2))
        elif "결재번호 수집을 건너뜁니다" in msg or "수집을 생략하고 종료" in msg:
            out["collect_skip_log"] = msg

        tg = _TARGETS_RE.search(msg)
        if tg:
            out["targets_stat"] = {
                "rowcount": int(tg.group(1)), "with_ab": int(tg.group(2)),
                "process": int(tg.group(3)), "map": int(tg.group(4)),
                "matched": int(tg.group(5)),
            }
        elif "결재번호 맵과 하나도 매칭되지 않았습니다" in msg:
            out["coverage_zero_warn"] = True
        elif msg.startswith("결재 대상 제외"):
            out["excluded_log"] = msg
            m_ex = _EXCLUDED_RE.search(msg)
            out["excluded_total"] = int(m_ex.group(1)) if m_ex else None
            m_na = _EXC_NO_AB_RE.search(msg)
            out["excluded_no_ab"] = int(m_na.group(1)) if m_na else 0
            m_um = _EXC_UNMAPPED_RE.search(msg)
            out["excluded_unmapped"] = int(m_um.group(1)) if m_um else 0

        hit = _classify_refdoc(msg)
        if hit:
            key, terminal = hit
            bucket = out["refdoc_terminal"] if terminal else out["refdoc_diag"]
            bucket[key] = bucket.get(key, 0) + 1
            out["refdoc_logs"].append(msg)
    return out


async def main() -> int:
    print("[SMOKE] 미지급금 법인카드 — 제품 경로(대시보드 폼 → 실행). ERP 삭제 단계 없음(전표 미생성).",
          flush=True)
    print("[SMOKE] ⚠ 상신·보관·참조문서 확인 절대 미클릭 — 관찰만 한다.", flush=True)

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
    print(f"[SMOKE] 선별 기간 {p_from} ~ {p_to} (전표유형 일반 {scan['target_rows']}건 — 이 중 "
          "결의구분=카드만 결재 대상이라 0건일 수 있다)", flush=True)

    # ── phase1 — 제품 UI 완주 ────────────────────────────────────────────────────
    async def fill(page) -> None:
        await fill_period(page, p_from, p_to)

    run = await run_product(
        agent_id=AGENT_ID,
        workflow_id=WORKFLOW_ID,
        fill=fill,
        tag=TAG,
        init_script=SSE_TAP_JS,
        on_page_done=read_tap,
        timeout_s=900,  # collect_payments 2nd 탭 왕복이 형제보다 길다.
    )
    tap = run.get("page_probe") or {}
    run_id = (run.get("run_after") or {}).get("id")
    logs = db_run_logs(run_id) if run.get("run_recorded") and run_id else []
    msgs = log_messages(logs)
    steps = step_status(logs)
    obs = parse_common(msgs)
    card = parse_card(msgs)

    # ⚠ 자식창(Page) 회계는 **loop_approvals 구간으로 한정**한다.
    #   runner `_on_new_page` 는 컨텍스트에 열리는 **모든** 팝업 Page 를 자식으로 보고 닫힐 때
    #   {"window":"child","closed":true} 를 낸다 — 결제창(EAP)뿐 아니라 set_query 의 코드도우미
    #   팝업도 같은 프레임을 낸다. 전역 카운터로 판정하면 결제창을 한 번도 열지 않은 실행이
    #   '자식창 1건'으로 오판된다(2026-07-31 라이브 실측).
    win = loop_window(tap)
    child_shot_in_loop = count_in_window(tap.get("childShotSeqs"), win)
    child_closed_in_loop = count_in_window(tap.get("childClosedSeqs"), win)
    child_closed_outside_loop = int(tap.get("childClosed") or 0) - child_closed_in_loop

    if tap.get("lastParentShot"):
        save_data_url_png(tap["lastParentShot"], ART / f"{TAG}_parent.png")
    if tap.get("lastChildShot"):
        save_data_url_png(tap["lastChildShot"], ART / f"{TAG}_child.png")

    rowcount = obs["rowcount"]
    processed = obs["processed_docu_nos"]
    opened = obs["opened_docu_nos"]
    targets_stat = card["targets_stat"]
    process_count = targets_stat["process"] if targets_stat else None
    result_text = str(tap.get("result") or run.get("result_text") or "")

    # ── 어설션 — "무엇이 맞아야 성공인가" ────────────────────────────────────────
    checks: dict[str, bool] = {}
    # P — 제품 경로 증거(종전 하네스엔 없던 항목).
    checks["product_path_run_recorded"] = bool(run.get("run_recorded"))
    checks["db_status_succeeded"] = run.get("db_status") == "succeeded"
    checks["ui_terminal_reached"] = bool(run.get("terminal")) and run.get("ui_status") == "succeeded"
    checks["sse_stream_observed"] = int(tap.get("connects") or 0) >= 1
    checks["form_period_applied"] = bool(
        obs["params_log"] and p_from in obs["params_log"] and p_to in obs["params_log"]
    )
    # V1 — 실행 전 파라미터가 '상신·참조문서 확인 없음'을 선언한다(게이트가 켜진 채 시작).
    checks["params_declare_no_submit"] = bool(
        obs["params_log"] and "실제 상신·참조문서 확인 없음" in obs["params_log"]
    )
    # V2(Δ1) — 전표유형이 카드 델타인 **일반**으로 세팅됐다.
    checks["docu_type_ilban_set_ok"] = (
        steps.get("set_query") == "done"
        and obs["set_query_ok_log"] is not None
        and "전표유형 일반" in obs["set_query_ok_log"]
    )
    # V3 — 조회(F2)가 실행돼 rowcount 를 읽었다(0건도 정상).
    checks["rowcount_observed"] = rowcount is not None
    # V4(Δ2) — 결재번호 수집 노드가 정상 종료했다(수집 완료 또는 명시적 생략 경로).
    checks["collect_payments_done"] = steps.get("collect_payments") == "done"
    checks["collect_payments_resolved"] = (card["collect_map_size"] is not None) or (
        card["collect_skip_log"] is not None
    )
    # V5 — 종단 성공 + error 프레임 0.
    checks["final_result_success_no_error"] = (
        bool(run.get("result_text") or tap.get("result")) and not (tap.get("errors") or [])
    )
    # V6 — 결과 문구가 '가상만'을 선언한다(실제 상신 없음 / 대상 없음).
    checks["result_declares_virtual_only"] = bool(
        result_text and ("실제 상신 없음" in result_text or "진행하지 않았습니다" in result_text
                         or "대상 전표가 없어" in result_text)
    )
    # V7(절대 안전) — 참조문서 '확인' 게이트가 열린 흔적이 0이어야 한다. **완화 금지**.
    checks["refdoc_confirm_never_clicked"] = card["refdoc_diag"].get("confirm_clicked", 0) == 0
    # V7b(절대 안전) — 상신/보관 클릭 흔적도 0.
    checks["no_real_submit_logged"] = not any(
        ("상신 클릭" in m) or ("보관 클릭" in m) for m in msgs
    )
    # V8 — D7 확정 불일치 0(있으면 그래프가 이미 중단시킨다 — 여기서 재확인).
    checks["d7_no_confirmed_mismatch"] = len(obs["d7_mismatch"]) == 0
    # EAP draft 예산 — draft 는 결제창을 연 횟수만큼 생긴다.
    checks["draft_budget_respected"] = obs["approval_opens"] <= MAX_TARGET_ROWS

    if rowcount == 0:
        # 경로 A — 전표조회승인 조회 0건. 2nd 탭도 열지 않고 결제창도 열지 않는다.
        checks["zero_rows_no_collect_no_child"] = (
            card["collect_skip_log"] is not None
            and child_shot_in_loop == 0
            and child_closed_in_loop == 0
            and not processed
        )
    elif not process_count:
        # 경로 B — 조회는 됐지만 결재 대상 0건(전 행 결의서번호 없음 = 직접 전표, 또는 비카드 결의).
        checks["zero_targets_no_child_opened"] = (
            child_shot_in_loop == 0
            and child_closed_in_loop == 0
            and not opened
            and not processed
        )
        # ── 커버리지 0 을 어떻게 볼 것인가 ────────────────────────────────────────
        # 그 자체는 실패가 아니다. 전표조회승인은 **전표유형=일반**으로만 좁히므로 카드가 아닌
        # 결의(출장·일반경비 등)에서 나온 전표도 함께 잡히고, 그 행의 ABDOCU_NO 는 결의구분=
        # 카드로 수집한 맵에 애초에 없다. 대신 **그 설명이 성립하는지**를 두 각도로 검증한다.
        #   (a) 맵이 실제로 수집됐는가(2026-07-27 사고: 결의부서가 로그인 부서로 좁혀져 전 행 미매칭).
        checks["zero_coverage_explained_by_noncard_rows"] = (not card["coverage_zero_warn"]) or (
            (card["collect_map_n"] or 0) >= 1 and (card["collect_map_size"] or 0) >= 1
        )
        #   (b) 제외 회계가 조회 건수와 맞는가 — 대상 0건 경로엔 max_rows 절단이 없으므로
        #       `조회 = 직접전표 + 맵미보유`, `맵미보유 = 결의서번호 보유 수` 가 정확히 성립해야 한다.
        checks["exclusions_reconcile_with_rowcount"] = (
            targets_stat is not None
            and card["excluded_total"] is not None
            and card["excluded_total"] == targets_stat["rowcount"]
            and (card["excluded_no_ab"] or 0) + (card["excluded_unmapped"] or 0)
            == card["excluded_total"]
            and (card["excluded_unmapped"] or 0) == targets_stat["with_ab"]
        )
    else:
        # 경로 C — 결재 대상 ≥1. 결제창·참조문서·D7 까지 종단 검증.
        checks["child_screenshot_emitted"] = child_shot_in_loop >= 1
        checks["child_closed_frame_emitted"] = child_closed_in_loop >= 1
        # 3단 창(부모→결재창→참조문서)을 역순으로 닫고 부모로 복귀했는지 — 연 만큼만 닫힌다.
        checks["closed_child_within_opened"] = 1 <= child_closed_in_loop <= max(1, len(opened))
        # 처리 건수 = 선별된 결재 대상 건수(제외분이 상한을 잡아먹지 않았는지 포함).
        checks["processed_matches_targets"] = len(processed) == process_count
        checks["opened_matches_targets"] = len(opened) == process_count
        checks["processed_docu_nos_distinct"] = len(set(processed)) == len(processed)
        # Δ2 커버리지 — 결의서번호 보유 행이 결재번호 맵과 실제로 매칭됐다.
        checks["payment_map_coverage_nonzero"] = (
            targets_stat is not None and targets_stat["matched"] >= 1
            and not card["coverage_zero_warn"]
        )
        # Δ3 — 결제창을 연 행마다 참조문서 훅이 **정확히 한 번** 종결 로그를 남겼다.
        #   (0건/미검색도 현재 테스트 계정의 정상 경로 — FLOW.md '알려진 제약'. 보는 것은
        #    "훅이 행마다 도달해 판정까지 갔는가"이지 "첨부에 성공했는가"가 아니다.)
        terminal_total = sum(card["refdoc_terminal"].values())
        checks["refdoc_outcome_per_processed_row"] = (
            terminal_total + card["refdoc_diag"].get("hook_exception", 0) == len(processed)
        )
        # D7 체크행수 — 확인 가능했다면 재체크 후에도 어긋난 건이 없어야 한다.
        checks["d7_checked_rows_ok_or_soft"] = (
            len(obs["d7_checked_ok"]) + len(obs["d7_checked_soft"]) >= len(opened)
        )

    ok = print_checks(checks)

    print("\n===== 카드 델타 상세 =====", flush=True)
    print(f"기간 선별      = {scan['picked_from']}~{scan['picked_to']} (실측 {scan['target_rows']}건) "
          f"· 월스캔 {scan['windows']} · 이분탐색 {scan['queries']}", flush=True)
    print(f"agent_runs     = id={run_id} status={run.get('db_status')} "
          f"logs={len(logs)}줄 (SSE 로그 {len(tap.get('logs') or [])}줄)", flush=True)
    print(f"steps          = {steps}", flush=True)
    print(f"params_log     = {obs['params_log']!r}", flush=True)
    print(f"set_query_log  = {obs['set_query_ok_log']!r}", flush=True)
    print(f"rowcount       = {rowcount} · 결제창 개봉(=EAP draft) {obs['approval_opens']}회", flush=True)
    print(f"collect(결의서 {card['collect_map_n']}건 → 맵 {card['collect_map_size']}건) "
          f"skip={card['collect_skip_log']!r}", flush=True)
    print(f"targets_stat   = {targets_stat!r}", flush=True)
    print(f"excluded_log   = {card['excluded_log']!r}", flush=True)
    print(f"child windows  = loop(shot {child_shot_in_loop}, closed {child_closed_in_loop}) "
          f"· outside-loop closed {child_closed_outside_loop}(코드도우미 등 — 결제창 아님)",
          flush=True)
    if card["coverage_zero_warn"]:
        print("[관찰] 커버리지 0 — 결의서번호 보유 행이 전부 비카드 결의(맵 미보유)로 제외됨. "
              f"맵 {card['collect_map_size']}건/결의서 {card['collect_map_n']}건 수집은 정상.",
              flush=True)
    print(f"refdoc_terminal= {card['refdoc_terminal']}", flush=True)
    print(f"refdoc_diag    = {card['refdoc_diag']}", flush=True)
    print(f"opened/processed = {opened} / {processed}", flush=True)
    print(f"d7_ok={len(obs['d7_ok'])} soft={len(obs['d7_soft'])} mismatch={len(obs['d7_mismatch'])} "
          f"checked_ok={len(obs['d7_checked_ok'])} checked_soft={len(obs['d7_checked_soft'])} "
          f"recheck={len(obs['d7_recheck'])}", flush=True)
    print(f"result         = {result_text!r}", flush=True)
    if run.get("error") or run.get("fail_reason"):
        print(f"run.error      = {run.get('error')} / {run.get('fail_reason')}", flush=True)

    report = ART / f"{TAG}.json"
    report.write_text(
        json.dumps(
            {"scan": scan, "run": {k: v for k, v in run.items() if k != "page_probe"},
             "checks": checks, "observed": obs, "card": card, "steps": steps,
             "child": {"shot_in_loop": child_shot_in_loop, "closed_in_loop": child_closed_in_loop,
                       "closed_outside_loop": child_closed_outside_loop,
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
