"""관리자 배치 라이브 스모크 — 전표조회승인(voucher-receivable) EAP 자식창 캡처 + D7 정합성 종단 검증.

목적: 실제 그래프(`app.agents.voucher_receivable.graph.build_voucher_receivable_graph`)를
`app.live.runner.run_workflow`(프로덕션 라이브 러너)로 태워, 결제(결재) 버튼으로 열리는
EAP 팝업이 러너의 **부모/자식 창 캡처**(`context.on("page")` → `screencast_pump(window="child")`)
로 실제로 잡히는지 확인한다. `max_rows` 는 `VoucherReceivableParams` 기본값(사용자 결정
2026-07-21: 3건, `allow_batch` 불필요)을 그대로 쓴다 — 이 스크립트가 값을 강제하지 않는다.

D7(배치 순회 정합성) 검증: 반복마다 결제창이 그 행의 DOCU_NO 와 일치하는지 — 이제
`nodes/approvals.py:loop_approvals` 자체가 안전 크리티컬 하드 실패로 검증한다(확정 불일치 시
배치 즉시 중단). 이 스모크는 그 결과를 로그 프레임에서 파싱해 구조화된 PASS/FAIL 로 재확인한다:
  - "가상 상신: 전표 {DOCU_NO}" → 처리된 행별 DOCU_NO 수집(순서·중복 확인).
  - "D7 정합성 확인 ✅/불가(soft)/오류" → 자식창 표시 전표번호 대조 결과.
  - "D7 체크행수 확인 ✅/불가(soft)" → 결제 열기 직전 체크된 행 수(=1) 확인 결과.
  - 자식 스크린샷은 `closed_child` 전이마다 스냅샷해 행별로 별도 PNG 저장(육안 대조용).

⚠⚠ 절대 안전 ⚠⚠
  - 그래프(nodes/approvals.py:loop_approvals)가 결제창에서 상신·보관을 절대 클릭하지 않고
    `close_child()`만 호출하도록 이미 보장돼 있다 — 이 스모크는 그 동작을 **관찰만** 한다.
  - `processed` 는 `max_rows` 를 초과할 수 없다(그래프의 `min(max_rows, rowcount)` 게이트).
  - EAP 임시문서(draft)는 `max_rows` 건 생기는 게 정상 범위(PROCESS.md 기지 이슈, 사용자 승인
    범위) — draft 목록 자체는 이 스크립트가 관찰하지 않는다(별도 EAP 화면 필요, 범위 밖).

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/voucher_receivable_smoke.py
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

from app.agents.voucher_receivable.graph import build_voucher_receivable_graph  # noqa: E402
from app.live.runner import run_workflow  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))
OVERALL_TIMEOUT_S = 300  # 5분 상한.

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

# 행별 "가상 상신: 전표 {DOCU_NO}" 로그 파싱(요약줄 "결재창 확인 완료 — N건 가상 상신…"과
# 구분하기 위해 정확한 접두 패턴으로 매칭).
_SUBMIT_RE = re.compile(r"^가상 상신: 전표 (\S+)$")


def _save_data_url_png(data_url: str, path: Path) -> None:
    """'data:image/jpeg;base64,...' → PNG 로 디코드 저장(육안 확인용, 확장자만 png로 통일)."""
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
    processed_docu_nos: list[str] = []  # "가상 상신: 전표 {DOCU_NO}" 에서 파싱(행별, 요약줄 제외).
    d7_ok: list[str] = []  # "D7 정합성 확인 ✅"
    d7_soft: list[str] = []  # "D7 정합성 확인 불가(soft, …)" — 모호, 하드 실패 아님.
    d7_mismatch: list[str] = []  # "D7 정합성 오류" — 확정 불일치(중단 조건).
    d7_checked_ok: list[str] = []  # "D7 체크행수 확인 ✅"
    d7_checked_soft: list[str] = []  # "D7 체크행수 확인 불가(soft, …)"
    error_frames: list[dict] = []
    result_text: str | None = None

    # 행별 자식 스크린샷 — closed_child 전이가 올 때마다 그 시점까지의 최신 자식 프레임을
    # 스냅샷해 별도 PNG 로 저장한다(행별 "이 팝업이 실제로 무슨 문서였는지" 육안 대조용).
    row_child_shots: list[str] = []

    creds = {"userid": USERID, "password": PASSWORD}
    # params={} → VoucherReceivableParams 기본값 그대로(사용자 결정 2026-07-21: max_rows=3,
    # allow_batch 불필요) — 이 스크립트가 값을 강제하지 않는다. 절대 조작 금지.
    params: dict = {}

    async with async_playwright() as pw:

        async def browser_factory():
            return await pw.chromium.launch(headless=HEADLESS)

        graph = build_voucher_receivable_graph()

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
                    run_id="smoke",
                    owner="smoke",
                ):
                    frames_log.append(frame)
                    if "step" in frame:
                        counts["step"] += 1
                        print(f"[step] {frame}", flush=True)
                    elif "log" in frame:
                        counts["log"] += 1
                        msg = frame["log"]
                        print(f"[log:{frame.get('level')}] {msg}", flush=True)
                        if "가상 상신" in msg:
                            virtual_submit_logs.append(msg)
                        m = _SUBMIT_RE.match(msg)
                        if m:
                            processed_docu_nos.append(m.group(1))
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

    # ── 아티팩트: 부모/자식 최신 스크린샷 PNG + 전체 프레임 로그 JSON ────────────────
    parent_png = ARTIFACTS / "voucher_receivable_smoke_parent.png"
    child_png = ARTIFACTS / "voucher_receivable_smoke_child.png"
    if latest_parent_shot:
        _save_data_url_png(latest_parent_shot, parent_png)
        print(f"[artifact] {parent_png}", flush=True)
    else:
        print("[artifact] 부모 스크린샷 없음(미방출)", flush=True)
    if latest_child_shot:
        _save_data_url_png(latest_child_shot, child_png)
        print(f"[artifact] {child_png}", flush=True)
    else:
        print("[artifact] 자식 스크린샷 없음(미방출) — 핵심 실패 신호", flush=True)

    # 행별 자식 스크린샷(closed_child 전이마다 스냅샷) — 3세트 시퀀스 육안 대조용.
    row_child_pngs: list[str] = []
    for i, shot in enumerate(row_child_shots, start=1):
        p = ARTIFACTS / f"voucher_receivable_smoke_child_row{i}.png"
        _save_data_url_png(shot, p)
        row_child_pngs.append(str(p))
        print(f"[artifact] {p}", flush=True)

    # 프레임 로그는 스크린샷 data URL을 생략(용량)하고 JSON 덤프.
    def _slim(f: dict) -> dict:
        if "screenshot" in f:
            return {k: v for k, v in f.items() if k != "screenshot"} | {
                "screenshot": f"<{len(f['screenshot'])} chars>"
            }
        return f

    frames_path = ARTIFACTS / "voucher_receivable_smoke_frames.json"
    frames_path.write_text(
        json.dumps([_slim(f) for f in frames_log], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[artifact] {frames_path}", flush=True)

    # ── 어설션 ────────────────────────────────────────────────────────────────
    checks: dict[str, bool] = {}
    checks["child_screenshot_emitted"] = counts["screenshot_child"] >= 1
    checks["virtual_submit_log_with_docu_no"] = any(
        "전표" in m and len(m.strip()) > len("가상 상신: 전표") for m in virtual_submit_logs
    )
    checks["child_closed_frame_emitted"] = counts["closed_child"] >= 1
    checks["final_result_success_no_error"] = (result_text is not None) and (counts["error"] == 0)
    # D7 — 핵심 검증(코디네이터 지시): processed 3건, 서로 다른 DOCU_NO 3개, 확정 불일치 0건,
    # 체크행수 위반 0건(그래프 자체가 이미 하드 실패로 막지만, 여기서도 로그로 재확인).
    checks["d7_processed_exactly_3"] = len(processed_docu_nos) == 3
    checks["d7_docu_nos_distinct"] = len(set(processed_docu_nos)) == len(processed_docu_nos)
    checks["d7_no_confirmed_mismatch"] = len(d7_mismatch) == 0
    checks["d7_closed_count_matches_processed"] = counts["closed_child"] == len(processed_docu_nos)

    print("\n===== SMOKE ASSERTIONS =====", flush=True)
    for k, v in checks.items():
        print(f"{'PASS' if v else 'FAIL'} — {k}", flush=True)

    print("\n===== FRAME COUNTS =====", flush=True)
    print(json.dumps(counts, ensure_ascii=False, indent=2), flush=True)

    print("\n===== D7 상세 =====", flush=True)
    print(f"processed_docu_nos = {processed_docu_nos}", flush=True)
    print(f"d7_ok(정합성 일치)      n={len(d7_ok)}: {d7_ok}", flush=True)
    print(f"d7_soft(정합성 모호)    n={len(d7_soft)}: {d7_soft}", flush=True)
    print(f"d7_mismatch(확정불일치) n={len(d7_mismatch)}: {d7_mismatch}", flush=True)
    print(f"d7_checked_ok           n={len(d7_checked_ok)}: {d7_checked_ok}", flush=True)
    print(f"d7_checked_soft         n={len(d7_checked_soft)}: {d7_checked_soft}", flush=True)

    print("\n===== SUMMARY =====", flush=True)
    summary = {
        "elapsed_s": round(elapsed, 1),
        "result_text": result_text,
        "error_frames": error_frames,
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
