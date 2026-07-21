"""관리자 단건 라이브 스모크 — 전표조회승인(voucher-payable) 공유그래프 매입 종단 검증.

`e2e/voucher_receivable_smoke.py`(run_workflow 종단 하네스)를 그대로 재사용하되
`build_voucher_payable_graph()`(전표유형=내수구매, SYSDEF_CD=31)로 바꾼 것 — 공유 그래프
(`build_voucher_graph`)가 매입에도 종단 동작하는지 확인한다. **`max_rows=1` 명시**(전체 진행이
이제 기본값이므로 스모크에선 EAP draft 를 1건으로 제한하기 위해 반드시 명시해야 한다).

D2 검증: 전표유형 **내수구매**(매출과 달리 단일 타깃)가 조회폼에 정상 세팅되는지 —
set_query 스텝 성공/실패와 "조회 조건 세팅 완료(…전표유형 내수구매)" 로그로 확인.

D3 검증: 조회(F2) 후 rowcount. **0건도 정상**(내수구매 미결·저장 전표가 당월에 없을 수 있음) —
그 경우 결제창 loop 는 스킵되고 "처리 완료 — 대상 전표가 없어…" 결과로 정상 종료된다. rowcount≥1
이면 단건 스모크와 동일하게 결제창(EAP)·D7 정합성·자식 프레임까지 검증한다.

⚠⚠ 절대 안전 ⚠⚠
  - 상신·보관 절대 미클릭(그래프가 이미 보장, 이 스모크는 관찰만).
  - max_rows=1 → EAP draft 최대 1건.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/voucher_payable_smoke.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import async_playwright  # noqa: E402

from app.agents.voucher_receivable.graph import build_voucher_payable_graph  # noqa: E402
from app.live.runner import run_workflow  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))
OVERALL_TIMEOUT_S = 300  # 5분 상한.

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

_SUBMIT_RE = re.compile(r"^가상 상신: 전표 (\S+)$")
_ROWCOUNT_RE = re.compile(r"조회 완료 — 대상 전표 (\d+)건\.")


def _save_data_url_png(data_url: str, path: Path) -> None:
    prefix = "base64,"
    idx = data_url.find(prefix)
    raw = base64.b64decode(data_url[idx + len(prefix) :] if idx >= 0 else data_url)
    path.write_bytes(raw)


async def main() -> None:
    counts = {
        "step": 0,
        "log": 0,
        "screenshot_parent": 0,
        "screenshot_child": 0,
        "closed_child": 0,
        "result": 0,
        "error": 0,
        "hitl": 0,
        "chat": 0,
        "transactions": 0,
    }
    frames_log: list[dict] = []
    latest_parent_shot: str | None = None
    latest_child_shot: str | None = None
    virtual_submit_logs: list[str] = []
    processed_docu_nos: list[str] = []
    d7_ok: list[str] = []
    d7_soft: list[str] = []
    d7_mismatch: list[str] = []
    d7_checked_ok: list[str] = []
    d7_checked_soft: list[str] = []
    error_frames: list[dict] = []
    result_text: str | None = None
    rowcount: int | None = None
    set_query_status: str | None = None  # "done" | "failed" | None(미도달)
    set_query_ok_log: str | None = None  # "조회 조건 세팅 완료(…전표유형 내수구매)."

    row_child_shots: list[str] = []

    creds = {"userid": USERID, "password": PASSWORD}
    # ⚠ max_rows=1 명시 — 기본값이 이제 None(전체 진행)이라 명시하지 않으면 조회된 전 건을
    # 처리해 EAP draft 가 rowcount 만큼 생긴다. 스모크는 1건만 검증하면 충분하다.
    params: dict = {"max_rows": 1}

    async with async_playwright() as pw:

        async def browser_factory():
            return await pw.chromium.launch(headless=HEADLESS)

        graph = build_voucher_payable_graph()

        t0 = time.monotonic()
        try:
            async with asyncio.timeout(OVERALL_TIMEOUT_S):
                async for frame in run_workflow(
                    graph,
                    browser_factory,
                    creds,
                    params,
                    screencast=True,
                    delay_scale=DELAY_SCALE,
                    run_id="smoke-payable",
                    owner="smoke-payable",
                ):
                    frames_log.append(frame)
                    if "step" in frame:
                        counts["step"] += 1
                        print(f"[step] {frame}", flush=True)
                        if frame.get("step") == "set_query":
                            set_query_status = frame.get("status")
                    elif "log" in frame:
                        counts["log"] += 1
                        msg = frame["log"]
                        print(f"[log:{frame.get('level')}] {msg}", flush=True)
                        if "가상 상신" in msg:
                            virtual_submit_logs.append(msg)
                        m = _SUBMIT_RE.match(msg)
                        if m:
                            processed_docu_nos.append(m.group(1))
                        rc_m = _ROWCOUNT_RE.search(msg)
                        if rc_m:
                            rowcount = int(rc_m.group(1))
                        if msg.startswith("조회 조건 세팅 완료"):
                            set_query_ok_log = msg
                        if msg.startswith("D7 정합성 확인 ✅"):
                            d7_ok.append(msg)
                        elif msg.startswith("D7 정합성 확인 불가"):
                            d7_soft.append(msg)
                        elif "D7 정합성 오류" in msg:
                            d7_mismatch.append(msg)
                        elif msg.startswith("D7 체크행수 확인 ✅"):
                            d7_checked_ok.append(msg)
                        elif msg.startswith("D7 체크행수 확인 불가"):
                            d7_checked_soft.append(msg)
                    elif "screenshot" in frame:
                        if frame.get("window") == "child":
                            counts["screenshot_child"] += 1
                            latest_child_shot = frame["screenshot"]
                        else:
                            counts["screenshot_parent"] += 1
                            latest_parent_shot = frame["screenshot"]
                    elif frame.get("window") == "child" and frame.get("closed"):
                        counts["closed_child"] += 1
                        print(f"[child] closed={frame}", flush=True)
                        if latest_child_shot:
                            row_child_shots.append(latest_child_shot)
                    elif "hitl" in frame:
                        counts["hitl"] += 1
                        print(f"[hitl] {frame}", flush=True)
                    elif "chat" in frame:
                        counts["chat"] += 1
                    elif "transactions" in frame:
                        counts["transactions"] += 1
                    elif "result" in frame:
                        counts["result"] += 1
                        result_text = frame["result"]
                        print(f"[result] {result_text}", flush=True)
                    elif "error" in frame:
                        counts["error"] += 1
                        error_frames.append(frame)
                        print(f"[error] {frame}", flush=True)
        except TimeoutError:
            error_frames.append({"error": f"스모크 전체 타임아웃({OVERALL_TIMEOUT_S}s) 초과"})
            print(f"[FATAL] 전체 타임아웃 {OVERALL_TIMEOUT_S}s 초과", flush=True)

    elapsed = time.monotonic() - t0

    # ── 아티팩트 ──────────────────────────────────────────────────────────────
    parent_png = ARTIFACTS / "voucher_payable_smoke_parent.png"
    child_png = ARTIFACTS / "voucher_payable_smoke_child.png"
    if latest_parent_shot:
        _save_data_url_png(latest_parent_shot, parent_png)
        print(f"[artifact] {parent_png}", flush=True)
    else:
        print("[artifact] 부모 스크린샷 없음(미방출)", flush=True)
    if latest_child_shot:
        _save_data_url_png(latest_child_shot, child_png)
        print(f"[artifact] {child_png}", flush=True)
    else:
        print("[artifact] 자식 스크린샷 없음(미방출) — rowcount=0 이면 정상, ≥1 이면 실패 신호", flush=True)

    row_child_pngs: list[str] = []
    for i, shot in enumerate(row_child_shots, start=1):
        p = ARTIFACTS / f"voucher_payable_smoke_child_row{i}.png"
        _save_data_url_png(shot, p)
        row_child_pngs.append(str(p))
        print(f"[artifact] {p}", flush=True)

    def _slim(f: dict) -> dict:
        if "screenshot" in f:
            return {k: v for k, v in f.items() if k != "screenshot"} | {
                "screenshot": f"<{len(f['screenshot'])} chars>"
            }
        return f

    frames_path = ARTIFACTS / "voucher_payable_smoke_frames.json"
    frames_path.write_text(
        json.dumps([_slim(f) for f in frames_log], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[artifact] {frames_path}", flush=True)

    # ── 어설션 ────────────────────────────────────────────────────────────────
    checks: dict[str, bool] = {}
    # D2: 전표유형(내수구매) 세팅 성공 — set_query 스텝이 failed 가 아니고, 완료 로그에
    # "내수구매" 가 포함돼 있어야 한다(공유 코드가 실제로 이 값을 세팅했다는 증거).
    checks["docu_type_naesugumae_set_ok"] = (
        set_query_status == "done"
        and set_query_ok_log is not None
        and "내수구매" in set_query_ok_log
    )
    checks["final_result_success_no_error"] = (result_text is not None) and (counts["error"] == 0)
    checks["rowcount_observed"] = rowcount is not None  # rowcount 를 못 읽었으면 set_query/run_query 이전 실패.

    zero_rows = rowcount == 0
    if zero_rows:
        checks["zero_rows_no_loop_attempted"] = counts["screenshot_child"] == 0 and len(processed_docu_nos) == 0
    else:
        checks["child_screenshot_emitted"] = counts["screenshot_child"] >= 1
        checks["virtual_submit_log_with_docu_no"] = any(
            "전표" in m and len(m.strip()) > len("가상 상신: 전표") for m in virtual_submit_logs
        )
        checks["child_closed_frame_emitted"] = counts["closed_child"] >= 1
        checks["processed_exactly_1"] = len(processed_docu_nos) == 1
        checks["d7_no_confirmed_mismatch"] = len(d7_mismatch) == 0

    print("\n===== SMOKE ASSERTIONS =====", flush=True)
    for k, v in checks.items():
        print(f"{'PASS' if v else 'FAIL'} — {k}", flush=True)

    print("\n===== FRAME COUNTS =====", flush=True)
    print(json.dumps(counts, ensure_ascii=False, indent=2), flush=True)

    print("\n===== D2/D3/D7 상세 =====", flush=True)
    print(f"set_query_status = {set_query_status!r}", flush=True)
    print(f"set_query_ok_log = {set_query_ok_log!r}", flush=True)
    print(f"rowcount = {rowcount!r}", flush=True)
    print(f"processed_docu_nos = {processed_docu_nos}", flush=True)
    print(f"d7_ok n={len(d7_ok)}: {d7_ok}", flush=True)
    print(f"d7_soft n={len(d7_soft)}: {d7_soft}", flush=True)
    print(f"d7_mismatch n={len(d7_mismatch)}: {d7_mismatch}", flush=True)
    print(f"d7_checked_ok n={len(d7_checked_ok)}: {d7_checked_ok}", flush=True)
    print(f"d7_checked_soft n={len(d7_checked_soft)}: {d7_checked_soft}", flush=True)

    print("\n===== SUMMARY =====", flush=True)
    summary = {
        "elapsed_s": round(elapsed, 1),
        "result_text": result_text,
        "error_frames": error_frames,
        "set_query_status": set_query_status,
        "set_query_ok_log": set_query_ok_log,
        "rowcount": rowcount,
        "virtual_submit_logs": virtual_submit_logs,
        "processed_docu_nos": processed_docu_nos,
        "d7_ok": d7_ok,
        "d7_soft": d7_soft,
        "d7_mismatch": d7_mismatch,
        "d7_checked_ok": d7_checked_ok,
        "d7_checked_soft": d7_checked_soft,
        "counts": counts,
        "checks": checks,
        "parent_png": str(parent_png) if latest_parent_shot else None,
        "child_png": str(child_png) if latest_child_shot else None,
        "row_child_pngs": row_child_pngs,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)

    all_pass = all(checks.values())
    print(f"\n===== {'ALL PASS' if all_pass else 'SOME FAILED'} =====", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
