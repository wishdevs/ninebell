"""관리자 라이브 스모크 — 미지급금 법인카드(voucher-card) 공유그래프 + 카드 3대 확장 종단 검증.

`e2e/voucher_receivable_smoke.py`(run_workflow 종단 하네스)를 `voucher_payable_smoke.py` 와
같은 방식으로 재사용하되, 그래프를 `build_voucher_card_graph()`(전표유형=일반, SYSDEF_CD=11)로
바꾸고 **카드 고유 델타 3가지**를 추가로 파싱·검증한다:

  Δ1  전표유형 = **일반**            (공유 set_query 를 DOCU_TYPES_CARD 로 재사용)
  Δ2  **결의서조회승인(GLDDOC00400) 2nd 메뉴 탭** 진입 → 결의부서 전체·결의자 비움·회계일·
      **결의구분=카드** 필터로 일괄 조회 → `ABDOCU_NO→GWDOCU_NO(결재번호)` 맵 수집 →
      전표조회승인 탭 복귀                                   (nodes/collect_payments.py)
  Δ3  결제창(EAP) 안 **참조문서 선택** — 문서번호=이 행의 GWDOCU_NO 로 조회 → 1건이면 선택 →
      아래(↓) 버튼으로 '선택된 문서 목록' 이동                (nodes/reference_doc.py)

⚠⚠ 이 스모크가 **어디서 멈추는가** ⚠⚠
회계전표(전표조회승인) 계열은 **전표를 생성하지 않고 기존 전표를 조회·검증**하는 아키타입이며,
ERP 에 삭제 로직이 없다 — 결의서입력 계열의 '실저장(F7)→검증→삭제(F6)' 사이클을 흉내내면
되돌릴 방법이 없다. 그래서 이 스모크는 `ACTIONS.md` 기준 **`확정`·`발신` 등급 동사를 한 번도
실행하지 않는 지점**에서 멈춘다. 카드의 `FLOW.md` 는 확정 등급이 한 줄도 없고 `금지` 가 둘이다:

  금지  [문서반영]  참조문서 확인 — 미클릭 (기록만)
  금지  [상신]      미클릭 — '가상 상신' 기록만

두 게이트는 **그래프 코드가 이미 보장**한다(`make_reference_doc_hook(allow_confirm=False)` +
`loop_approvals` 의 read/close-only 규율). 이 스모크는 그 게이트를 **관찰만** 하며, 게이트를
여는 어떤 인자도 넘기지 않는다 — `allow_confirm` 을 건드리지 않고, 그래프를 직접 조립하지 않고
등록된 팩토리(`build_voucher_card_graph()`)를 그대로 태운다. 형제 스모크(외상매출금/매입금)가
확립한 안전 패턴 그대로다.

되돌릴 수 없는 부작용: **0건**. 관찰되는 유일한 잔여물은 결제창을 여는 것만으로 생길 수 있는
**EAP 임시문서(draft)** 이며(형제와 동일·PROCESS.md 기지 이슈), `max_rows` 기본 1 로 최대 1건에
묶는다.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/voucher_card_smoke.py

env(형제 스모크 관례 E2E_* 를 그대로 쓰고, 카드 고유 노브만 VOUCHER_CARD_SMOKE_* 우선):
    E2E_USERID / E2E_PASSWORD          자격증명(기본 이트라이브2/1111)
    E2E_HEADLESS                       "0" 이면 헤드풀
    E2E_DELAY_SCALE                    대기 배율(기본 0.4 — 등록된 워크플로우와 동일)
    VOUCHER_CARD_SMOKE_MAX_ROWS        결재 대상 상한(기본 1, 0=전체). 폴백 E2E_MAX_ROWS
    VOUCHER_CARD_SMOKE_PERIOD_FROM/_TO 회계일 YYYYMMDD(미지정=당월). 폴백 E2E_PERIOD_START/_END
    VOUCHER_CARD_SMOKE_TIMEOUT_S       전체 상한 초(기본 420 — 2nd 탭 왕복이 형제보다 길다)
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

from app.agents.voucher_card.graph import build_voucher_card_graph  # noqa: E402
from app.live.runner import run_workflow  # noqa: E402


def _env(name: str, legacy: str, default: str = "") -> str:
    """카드 고유 노브는 VOUCHER_CARD_SMOKE_* 우선, 없으면 형제 스모크 관례(E2E_*)."""
    return os.environ.get(f"VOUCHER_CARD_SMOKE_{name}") or os.environ.get(legacy) or default


USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))
# 카드는 collect_payments 가 2nd 메뉴 탭을 열고 돌아오는 왕복이 더 있어 형제(300s)보다 여유를 둔다.
OVERALL_TIMEOUT_S = int(_env("TIMEOUT_S", "E2E_TIMEOUT_S", "420"))
MAX_ROWS = int(_env("MAX_ROWS", "E2E_MAX_ROWS", "1"))  # 0 = 전체(기본값 None 그대로)
PERIOD_FROM = _env("PERIOD_FROM", "E2E_PERIOD_START") or None
PERIOD_TO = _env("PERIOD_TO", "E2E_PERIOD_END") or None

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

# ── 노드 로그 파서 — 문구는 app/agents/voucher_{receivable,card} 노드의 emit_log 원문과 1:1 ──
_ROWCOUNT_RE = re.compile(r"조회 완료 — 대상 전표 (\d+)건\.")
# collect_payments: "결재번호 수집 완료 — 결의서 12건 중 매핑 4건(ABDOCU_NO→GWDOCU_NO)."
_MAP_RE = re.compile(r"결재번호 수집 완료 — 결의서 (\d+)건 중 매핑 (\d+)건")
# loop_approvals(카드 경로): "조회 9건 중 결의서번호 보유 4건 → 결재 대상 4건(결재번호 맵 32건, 매칭 4/4)."
_TARGETS_RE = re.compile(
    r"조회 (\d+)건 중 결의서번호 보유 (\d+)건 → 결재 대상 (\d+)건"
    r"\(결재번호 맵 (\d+)건, 매칭 (\d+)/(\d+)\)"
)
_OPEN_RE = re.compile(r"^\[(\d+)/(\d+)\] 전표 (\S+) 결제창 확인 중…")
_SUBMIT_RE = re.compile(r"^\[(\d+)/(\d+)\] 가상 상신 완료 — 전표 (\S+) ")
# 제외 요약: "결재 대상 제외 2건 — 결의서번호 없음(직접 전표) 1건 · 결재번호 맵에 없음 1건(전표 …)."
_EXCLUDED_RE = re.compile(r"결재 대상 제외 (\d+)건")
_EXC_NO_AB_RE = re.compile(r"결의서번호 없음\(직접 전표\) (\d+)건")
_EXC_UNMAPPED_RE = re.compile(r"결재번호 맵에 없음 (\d+)건")

# 참조문서 훅의 **종결 로그**(행당 정확히 하나) — 진단성 경고(패널 확장/문서번호 입력)는 제외한다.
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
    ("hits_confirmed", "참조문서 검색 "),  # "참조문서 검색 1건 확인(…)"
    ("attach_lost", "참조문서 첨부 직후엔 담겼으나"),
    ("hook_exception", "참조문서 처리 중 경고(무시하고 진행)"),
    ("virtual_confirm", "가상: 참조문서 확인·상신"),
    # ⚠ 절대 안전 감시 — 0이어야 한다. 1 이상이면 게이트가 열린 채 실행된 것이다.
    ("confirm_clicked", "참조문서 확인 클릭(allow_confirm=True)"),
)


def _save_data_url_png(data_url: str, path: Path) -> None:
    """'data:image/jpeg;base64,...' → PNG 로 디코드 저장(육안 확인용, 확장자만 png로 통일)."""
    prefix = "base64,"
    idx = data_url.find(prefix)
    raw = base64.b64decode(data_url[idx + len(prefix) :] if idx >= 0 else data_url)
    path.write_bytes(raw)


def _classify_refdoc(msg: str) -> tuple[str, bool] | None:
    """참조문서 로그 → (분류키, 종결여부). 해당 없으면 None."""
    for key, needle in _REFDOC_TERMINAL:
        if needle in msg:
            return key, True
    for key, needle in _REFDOC_DIAG:
        if needle in msg:
            return key, False
    return None


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
    row_child_shots: list[str] = []

    # ⚠ 자식창(Page) 회계는 **loop_approvals 구간으로 한정**한다.
    #   runner.py `_on_new_page` 는 브라우저 컨텍스트에 열리는 **모든** 팝업 Page 를 자식으로
    #   보고, 닫힐 때 {"window":"child","closed":true} 를 방출한다 — 결제창(EAP)뿐 아니라
    #   set_query 의 코드도우미 팝업(작성부서 전체선택 등)도 같은 프레임을 낸다.
    #   전역 카운터로 "결제창을 열었는가"를 판정하면 결제창을 한 번도 열지 않은 실행이
    #   '자식창 1건'으로 오판된다(2026-07-31 초회 라이브 실측: set_query 중 closed 1건).
    in_loop_approvals = False
    child_shot_in_loop = 0
    child_closed_in_loop = 0
    child_closed_outside_loop = 0

    # 단계별 타이밍 — 노드 자기보고 ms(step done 프레임)와 프레임 도착 기준 wall ms 를 둘 다 남긴다.
    step_order: list[str] = []
    step_status: dict[str, str] = {}
    step_reported_ms: dict[str, int] = {}
    step_started_at: dict[str, float] = {}
    step_wall_ms: dict[str, int] = {}

    # 카드 델타 관측치.
    params_log: str | None = None
    set_query_ok_log: str | None = None
    rowcount: int | None = None
    collect_map_n: int | None = None  # 결의서조회승인 조회 건수
    collect_map_size: int | None = None  # 수집된 맵 크기
    collect_skip_log: str | None = None  # 수집 생략(0건/직접 전표) 경로
    targets_stat: dict[str, int] | None = None  # rowcount/with_ab/process/map/matched
    coverage_zero_warn: bool = False  # "맵과 하나도 매칭되지 않았습니다" 진단 로그(그래프 방출)
    excluded_log: str | None = None
    excluded_total: int | None = None  # 제외 합계
    excluded_no_ab: int | None = None  # 결의서번호 없음(직접 전표)
    excluded_unmapped: int | None = None  # 결의서번호는 있으나 결재번호 맵에 없음(비카드 결의)
    opened_docu_nos: list[str] = []  # "[i/N] 전표 X 결제창 확인 중…"
    processed_docu_nos: list[str] = []  # "[i/N] 가상 상신 완료 — 전표 X …"
    refdoc_terminal: dict[str, int] = {}
    refdoc_diag: dict[str, int] = {}
    refdoc_logs: list[str] = []

    d7_ok: list[str] = []
    d7_soft: list[str] = []
    d7_mismatch: list[str] = []
    d7_checked_ok: list[str] = []
    d7_checked_soft: list[str] = []
    d7_recheck: list[str] = []

    error_frames: list[dict] = []
    result_text: str | None = None

    creds = {"userid": USERID, "password": PASSWORD}
    # ⚠ max_rows 명시(기본 1) — VoucherCardParams 기본값은 None(전체 진행)이라 명시하지 않으면
    #   결재 대상 전 건의 결제창을 열어 EAP 임시문서가 그만큼 생긴다. 스모크는 1건이면 충분하다.
    #   (VOUCHER_CARD_SMOKE_MAX_ROWS=0 이면 그래프 기본값=전체 — 의도적으로 켤 때만.)
    params: dict = {} if MAX_ROWS == 0 else {"max_rows": MAX_ROWS}
    if PERIOD_FROM:
        params["period_from"] = PERIOD_FROM
    if PERIOD_TO:
        params["period_to"] = PERIOD_TO

    async with async_playwright() as pw:

        async def browser_factory():
            return await pw.chromium.launch(headless=HEADLESS)

        # ⚠ 등록된 팩토리를 그대로 쓴다 — allow_confirm 등 게이트 인자를 스모크가 조립하지 않는다.
        graph = build_voucher_card_graph()

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
                    run_id="smoke-card",
                    owner="smoke-card",
                ):
                    frames_log.append(frame)
                    if "step" in frame:
                        counts["step"] += 1
                        name = frame["step"]
                        status = frame.get("status")
                        print(f"[step] {frame}", flush=True)
                        if name not in step_order:
                            step_order.append(name)
                        if name == "loop_approvals":
                            # 결제창(EAP)은 이 구간에서만 열린다 — 자식창 카운팅 구간 게이트.
                            in_loop_approvals = status == "running"
                        if status == "running" and name not in step_started_at:
                            step_started_at[name] = time.monotonic()
                        if status in ("done", "failed"):
                            step_status[name] = status
                            if isinstance(frame.get("ms"), int):
                                step_reported_ms[name] = frame["ms"]
                            if name in step_started_at:
                                step_wall_ms[name] = int(
                                    (time.monotonic() - step_started_at[name]) * 1000
                                )
                        elif name not in step_status:
                            step_status[name] = "running"
                    elif "log" in frame:
                        counts["log"] += 1
                        msg = frame["log"]
                        print(f"[log:{frame.get('level')}] {msg}", flush=True)

                        if msg.startswith("실행 파라미터 확인"):
                            params_log = msg
                        elif msg.startswith("조회 조건 세팅 완료"):
                            set_query_ok_log = msg
                        rc = _ROWCOUNT_RE.search(msg)
                        if rc:
                            rowcount = int(rc.group(1))

                        # Δ2 — 결재번호 수집(2nd 메뉴 결의서조회승인).
                        mp = _MAP_RE.search(msg)
                        if mp:
                            collect_map_n = int(mp.group(1))
                            collect_map_size = int(mp.group(2))
                        elif "결재번호 수집을 건너뜁니다" in msg or "수집을 생략하고 종료" in msg:
                            collect_skip_log = msg

                        # 결재 대상 선별(카드 경로에서만 나오는 커버리지 줄).
                        tg = _TARGETS_RE.search(msg)
                        if tg:
                            targets_stat = {
                                "rowcount": int(tg.group(1)),
                                "with_ab": int(tg.group(2)),
                                "process": int(tg.group(3)),
                                "map": int(tg.group(4)),
                                "matched": int(tg.group(5)),
                            }
                        elif "결재번호 맵과 하나도 매칭되지 않았습니다" in msg:
                            coverage_zero_warn = True
                        elif msg.startswith("결재 대상 제외"):
                            excluded_log = msg
                            m_ex = _EXCLUDED_RE.search(msg)
                            excluded_total = int(m_ex.group(1)) if m_ex else None
                            m_na = _EXC_NO_AB_RE.search(msg)
                            excluded_no_ab = int(m_na.group(1)) if m_na else 0
                            m_um = _EXC_UNMAPPED_RE.search(msg)
                            excluded_unmapped = int(m_um.group(1)) if m_um else 0

                        m = _OPEN_RE.match(msg)
                        if m:
                            opened_docu_nos.append(m.group(3))
                        m = _SUBMIT_RE.match(msg)
                        if m:
                            processed_docu_nos.append(m.group(3))

                        # Δ3 — 참조문서 훅.
                        hit = _classify_refdoc(msg)
                        if hit:
                            key, terminal = hit
                            bucket = refdoc_terminal if terminal else refdoc_diag
                            bucket[key] = bucket.get(key, 0) + 1
                            refdoc_logs.append(msg)

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
                        elif msg.startswith("D7 체크행수 불일치"):
                            d7_recheck.append(msg)
                    elif "screenshot" in frame:
                        if frame.get("window") == "child":
                            counts["screenshot_child"] += 1
                            if in_loop_approvals:
                                child_shot_in_loop += 1
                            latest_child_shot = frame["screenshot"]
                        else:
                            counts["screenshot_parent"] += 1
                            latest_parent_shot = frame["screenshot"]
                    elif frame.get("window") == "child" and frame.get("closed"):
                        counts["closed_child"] += 1
                        scope = "loop" if in_loop_approvals else "outside-loop(코드도우미 등)"
                        print(f"[child] closed[{scope}]={frame}", flush=True)
                        if in_loop_approvals:
                            child_closed_in_loop += 1
                            if latest_child_shot:
                                row_child_shots.append(latest_child_shot)
                        else:
                            child_closed_outside_loop += 1
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

    # ── 아티팩트: 부모/자식 스크린샷 PNG + 프레임 로그 JSON + 리포트 JSON ────────────
    parent_png = ARTIFACTS / "voucher_card_smoke_parent.png"
    child_png = ARTIFACTS / "voucher_card_smoke_child.png"
    if latest_parent_shot:
        _save_data_url_png(latest_parent_shot, parent_png)
        print(f"[artifact] {parent_png}", flush=True)
    else:
        print("[artifact] 부모 스크린샷 없음(미방출)", flush=True)
    if latest_child_shot:
        _save_data_url_png(latest_child_shot, child_png)
        print(f"[artifact] {child_png}", flush=True)
    else:
        print("[artifact] 자식 스크린샷 없음 — 결재 대상 0건이면 정상, ≥1 이면 실패 신호", flush=True)

    row_child_pngs: list[str] = []
    for i, shot in enumerate(row_child_shots, start=1):
        p = ARTIFACTS / f"voucher_card_smoke_child_row{i}.png"
        _save_data_url_png(shot, p)
        row_child_pngs.append(str(p))
        print(f"[artifact] {p}", flush=True)

    def _slim(f: dict) -> dict:
        if "screenshot" in f:
            return {k: v for k, v in f.items() if k != "screenshot"} | {
                "screenshot": f"<{len(f['screenshot'])} chars>"
            }
        return f

    frames_path = ARTIFACTS / "voucher_card_smoke_frames.json"
    frames_path.write_text(
        json.dumps([_slim(f) for f in frames_log], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[artifact] {frames_path}", flush=True)

    timings = [
        {
            "step": name,
            "status": step_status.get(name),
            "reported_ms": step_reported_ms.get(name),
            "wall_ms": step_wall_ms.get(name),
        }
        for name in step_order
    ]

    # ── 어설션 — "무엇이 맞아야 성공인가" ────────────────────────────────────────
    process_count = targets_stat["process"] if targets_stat else None
    checks: dict[str, bool] = {}

    # 공통(모든 경로에서 성립해야 한다).
    # V1 — 실행 전 파라미터가 '상신·참조문서 확인 없음'을 선언한다(게이트가 켜진 채 시작).
    checks["params_declare_no_submit"] = bool(
        params_log and "실제 상신·참조문서 확인 없음" in params_log
    )
    # V2(Δ1) — 전표유형이 카드 델타인 **일반**으로 세팅됐다.
    checks["docu_type_ilban_set_ok"] = (
        step_status.get("set_query") == "done"
        and set_query_ok_log is not None
        and "전표유형 일반" in set_query_ok_log
    )
    # V3 — 조회(F2)가 실행돼 rowcount 를 읽었다(0건도 정상).
    checks["rowcount_observed"] = rowcount is not None
    # V4(Δ2) — 결의서조회승인 수집 노드가 정상 종료했다(수집 완료 또는 명시적 생략 경로).
    checks["collect_payments_done"] = step_status.get("collect_payments") == "done"
    checks["collect_payments_resolved"] = (collect_map_size is not None) or (
        collect_skip_log is not None
    )
    # V5 — 종단 성공 + error 프레임 0.
    checks["final_result_success_no_error"] = (result_text is not None) and (counts["error"] == 0)
    # V6 — 결과 문구가 '가상만' 을 선언한다(실제 상신 없음 / 대상 없음).
    checks["result_declares_virtual_only"] = bool(
        result_text and ("실제 상신 없음" in result_text or "진행하지 않았습니다" in result_text)
    )
    # V7(절대 안전) — 참조문서 '확인' 게이트가 열린 흔적이 0이어야 한다.
    checks["refdoc_confirm_never_clicked"] = refdoc_diag.get("confirm_clicked", 0) == 0
    # V8 — D7 확정 불일치 0(있으면 그래프가 이미 중단시킨다 — 여기서 재확인).
    checks["d7_no_confirmed_mismatch"] = len(d7_mismatch) == 0

    if rowcount == 0:
        # 경로 A — 전표조회승인 조회 0건. 2nd 탭도 열지 않고 결제창도 열지 않는다.
        checks["zero_rows_no_collect_no_child"] = (
            collect_skip_log is not None
            and child_shot_in_loop == 0
            and child_closed_in_loop == 0
            and not processed_docu_nos
        )
    elif not process_count:
        # 경로 B — 조회는 됐지만 결재 대상 0건(전 행 결의서번호 없음 = 직접 전표, 또는 비카드 결의).
        # 자식창은 **loop 구간 기준**으로 본다(위 in_loop_approvals 주석 참조 — 전역 카운터는
        # set_query 의 코드도우미 팝업 닫힘까지 포함해 결제창 개봉으로 오판한다).
        checks["zero_targets_no_child_opened"] = (
            child_shot_in_loop == 0
            and child_closed_in_loop == 0
            and not opened_docu_nos
            and not processed_docu_nos
        )
        # ── 커버리지 0(결의서번호 보유 행이 맵과 하나도 안 맞음)을 어떻게 볼 것인가 ──────
        # 그 자체는 실패가 아니다. 전표조회승인은 **전표유형=일반**으로만 좁히므로 카드가 아닌
        # 결의(출장·일반경비 등)에서 나온 전표도 함께 잡히고, 그 행의 ABDOCU_NO 는 결의구분=
        # 카드로 수집한 맵에 애초에 없다 — PROCESS.md '대상 = 결의구분=카드(ABDOCU_FG_CD=52)만',
        # 'Phase A 결과 중 카드(52)·ABDOCU_NO 있는 행만 결제 대상'.
        # (2026-07-31 라이브 실측: IMP3팀 '유류비 지원' FI2026072300000008 1건이 이 사유로 제외.)
        # 대신 **그 설명이 성립하는지**를 두 각도로 검증한다 — 완화가 아니라 판정 기준 교체다.
        #   (a) 맵이 실제로 수집됐는가. 맵이 비었다면 '비카드라 안 맞았다'가 아니라 수집 조건이
        #       어긋난 것이다(2026-07-27 사고: 결의부서가 로그인 부서로 좁혀져 전 행 미매칭).
        checks["zero_coverage_explained_by_noncard_rows"] = (not coverage_zero_warn) or (
            (collect_map_n or 0) >= 1 and (collect_map_size or 0) >= 1
        )
        #   (b) 제외 회계가 조회 건수와 맞는가. 커버리지 줄과 제외 요약은 서로 다른 시점에
        #       독립적으로 방출되는 로그이고, 대상 0건 경로에는 max_rows 절단이 없으므로
        #       `조회 = 직접전표 + 맵미보유`, `맵미보유 = 결의서번호 보유 수` 가 정확히 성립해야
        #       한다. 어긋나면 행이 조용히 새거나 선별 회계가 깨진 것이다.
        checks["exclusions_reconcile_with_rowcount"] = (
            targets_stat is not None
            and excluded_total is not None
            and excluded_total == targets_stat["rowcount"]
            and (excluded_no_ab or 0) + (excluded_unmapped or 0) == excluded_total
            and (excluded_unmapped or 0) == targets_stat["with_ab"]
        )
    else:
        # 경로 C — 결재 대상 ≥1. 결제창·참조문서·D7 까지 종단 검증.
        checks["child_screenshot_emitted"] = child_shot_in_loop >= 1
        checks["child_closed_frame_emitted"] = child_closed_in_loop >= 1
        # 3단 창(부모→결재창→참조문서)을 역순으로 닫고 부모로 복귀했는지 — 연 만큼만 닫힌다.
        # (loop 구간 기준 — set_query 의 코드도우미 팝업 닫힘이 상한을 잡아먹지 않게 한다.)
        checks["closed_child_within_opened"] = (
            1 <= child_closed_in_loop <= max(1, len(opened_docu_nos))
        )
        # 처리 건수 = 선별된 결재 대상 건수(제외분이 상한을 잡아먹지 않았는지 포함).
        checks["processed_matches_targets"] = len(processed_docu_nos) == process_count
        checks["opened_matches_targets"] = len(opened_docu_nos) == process_count
        checks["processed_docu_nos_distinct"] = len(set(processed_docu_nos)) == len(
            processed_docu_nos
        )
        # max_rows 상한 준수(0=전체일 때는 검사하지 않는다).
        checks["max_rows_respected"] = MAX_ROWS == 0 or process_count <= MAX_ROWS
        # Δ2 커버리지 — 결의서번호 보유 행이 결재번호 맵과 실제로 매칭됐다.
        checks["payment_map_coverage_nonzero"] = (
            targets_stat is not None and targets_stat["matched"] >= 1 and not coverage_zero_warn
        )
        # Δ3 — 결제창을 연 행마다 참조문서 훅이 **정확히 한 번** 종결 로그를 남겼다.
        #   (0건/미검색도 현재 테스트 계정의 정상 경로 — FLOW.md '알려진 제약'. 여기서 보는 것은
        #    "훅이 행마다 도달해 판정까지 갔는가"이지 "첨부에 성공했는가"가 아니다.)
        terminal_total = sum(refdoc_terminal.values())
        checks["refdoc_outcome_per_processed_row"] = (
            terminal_total + refdoc_diag.get("hook_exception", 0) == len(processed_docu_nos)
        )
        # D7 체크행수 — 확인 가능했다면 재체크 후에도 어긋난 건이 없어야 한다(어긋나면 하드 실패
        # 로 error 프레임이 뜨므로 위 V5 와 중복 방어).
        checks["d7_checked_rows_ok_or_soft"] = (
            len(d7_checked_ok) + len(d7_checked_soft) >= len(opened_docu_nos)
        )

    print("\n===== STEP TIMINGS (ms) =====", flush=True)
    for t in timings:
        rep = t["reported_ms"]
        wall = t["wall_ms"]
        print(
            f"{t['step']:<20} status={t['status']:<7} reported={rep if rep is not None else '-':>7} "
            f"wall={wall if wall is not None else '-':>7}",
            flush=True,
        )

    print("\n===== SMOKE ASSERTIONS =====", flush=True)
    for k, v in checks.items():
        print(f"{'PASS' if v else 'FAIL'} — {k}", flush=True)

    print("\n===== FRAME COUNTS =====", flush=True)
    print(json.dumps(counts, ensure_ascii=False, indent=2), flush=True)

    print("\n===== 카드 델타 상세 =====", flush=True)
    print(f"params_log        = {params_log!r}", flush=True)
    print(f"set_query_ok_log  = {set_query_ok_log!r}", flush=True)
    print(f"rowcount          = {rowcount!r}", flush=True)
    print(f"collect(결의서 {collect_map_n}건 → 맵 {collect_map_size}건) skip={collect_skip_log!r}", flush=True)
    print(f"targets_stat      = {targets_stat!r}", flush=True)
    print(f"excluded_log      = {excluded_log!r}", flush=True)
    print(
        f"child windows     = loop(shot {child_shot_in_loop}, closed {child_closed_in_loop}) "
        f"· outside-loop closed {child_closed_outside_loop}(코드도우미 등 — 결제창 아님)",
        flush=True,
    )
    if coverage_zero_warn:
        # 실패는 아니지만 눈에 띄게 남긴다 — 카드 결의가 한 건도 안 걸린 실행이라는 뜻이다.
        print(
            "[관찰] 커버리지 0 — 결의서번호 보유 행이 전부 비카드 결의(맵 미보유)로 제외됨. "
            f"맵 {collect_map_size}건/결의서 {collect_map_n}건 수집은 정상.",
            flush=True,
        )
    print(f"opened_docu_nos   = {opened_docu_nos}", flush=True)
    print(f"processed_docu_nos= {processed_docu_nos}", flush=True)
    print(f"refdoc_terminal   = {refdoc_terminal}", flush=True)
    print(f"refdoc_diag       = {refdoc_diag}", flush=True)

    print("\n===== D7 상세 =====", flush=True)
    print(f"d7_ok           n={len(d7_ok)}: {d7_ok}", flush=True)
    print(f"d7_soft         n={len(d7_soft)}: {d7_soft}", flush=True)
    print(f"d7_mismatch     n={len(d7_mismatch)}: {d7_mismatch}", flush=True)
    print(f"d7_checked_ok   n={len(d7_checked_ok)}: {d7_checked_ok}", flush=True)
    print(f"d7_checked_soft n={len(d7_checked_soft)}: {d7_checked_soft}", flush=True)
    print(f"d7_recheck      n={len(d7_recheck)}: {d7_recheck}", flush=True)

    all_pass = all(checks.values())
    report = {
        "agent": "voucher-card",
        "graph": "build_voucher_card_graph",
        "env": {
            "userid": USERID,
            "headless": HEADLESS,
            "delay_scale": DELAY_SCALE,
            "max_rows": MAX_ROWS or None,
            "period_from": PERIOD_FROM,
            "period_to": PERIOD_TO,
            "timeout_s": OVERALL_TIMEOUT_S,
        },
        "params": params,
        "elapsed_s": round(elapsed, 1),
        "timings": timings,
        "counts": counts,
        "checks": checks,
        "all_pass": all_pass,
        "result_text": result_text,
        "error_frames": error_frames,
        "delta": {
            "params_log": params_log,
            "set_query_ok_log": set_query_ok_log,
            "rowcount": rowcount,
            "collect_query_rows": collect_map_n,
            "payment_map_size": collect_map_size,
            "collect_skip_log": collect_skip_log,
            "targets_stat": targets_stat,
            "coverage_zero_warn": coverage_zero_warn,
            "excluded_log": excluded_log,
            "excluded_total": excluded_total,
            "excluded_no_ab": excluded_no_ab,
            "excluded_unmapped": excluded_unmapped,
            "child_shot_in_loop": child_shot_in_loop,
            "child_closed_in_loop": child_closed_in_loop,
            "child_closed_outside_loop": child_closed_outside_loop,
            "opened_docu_nos": opened_docu_nos,
            "processed_docu_nos": processed_docu_nos,
            "refdoc_terminal": refdoc_terminal,
            "refdoc_diag": refdoc_diag,
            "refdoc_logs": refdoc_logs,
        },
        "d7": {
            "ok": d7_ok,
            "soft": d7_soft,
            "mismatch": d7_mismatch,
            "checked_ok": d7_checked_ok,
            "checked_soft": d7_checked_soft,
            "recheck": d7_recheck,
        },
        "artifacts": {
            "parent_png": str(parent_png) if latest_parent_shot else None,
            "child_png": str(child_png) if latest_child_shot else None,
            "row_child_pngs": row_child_pngs,
            "frames_json": str(frames_path),
        },
    }
    report_path = ARTIFACTS / "voucher_card_smoke_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[artifact] {report_path}", flush=True)

    print("\n===== SUMMARY =====", flush=True)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    print(f"\n===== {'ALL PASS' if all_pass else 'SOME FAILED'} =====", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
