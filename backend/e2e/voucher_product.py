"""회계전표 3종 **제품 경로** e2e 공통 모듈 — 대시보드 UI 에서 실행하고, 관측은 SSE+DB 로 한다.

전환(사용자 지시 2026-08-03): 종전 3종 스모크는 `build_*_graph()` + `run_workflow()` 를 파이썬이
직접 호출해 러너까지만 탔다 — 프론트 pre-run 폼(`VoucherPreRunForm`)·`runs.py` collect 의 서버
권위 params 주입·세션/SSE/재연결·`agent_runs` 기록이 전부 미검증이었다. 결의서입력 4종이 방금
`e2e/product_cycle.py` 로 전환한 것과 같은 구조로 맞춘다.

⚠ 결의서입력과 다른 점 — **ERP 에서 제거할 것이 없다**
회계전표 계열은 전표를 **생성하지 않는다**(기존 전표를 조회·결재하는 아키타입). ERP 에 이 화면의
삭제 로직 자체가 없다(`voucher_receivable/PROCESS.md:29`). 그래서 phase2(F6 삭제)가 없고, 대신
**부작용을 애초에 만들지 않는 것**이 정리에 해당한다 — 아래 '기간 선별' 참조.

── 관측 경로 전환(핵심 설계) ────────────────────────────────────────────────────
종전 하네스는 `run_workflow` 가 yield 하는 프레임을 파이썬이 직접 받아 검증했다. 제품 경로에서는
프레임이 러너 → 세션 → SSE → 브라우저로 흐르므로 직접 받을 수 없다. 두 갈래로 복원한다.

  (1) `agent_runs.logs` — 세션이 종료 시 영속하는 log/step 프레임(`app/live/session.py:167`
      `_accumulate_log`). **log 메시지와 step 상태는 전량 보존**되므로 D7·가상 상신·rowcount·
      전표유형·참조문서·커버리지 등 **로그 기반 어설션은 전부 동등 재현**된다.
  (2) **SSE 탭(in-page)** — `agent_runs.logs` 는 스크린샷·자식창 닫힘 프레임을 저장하지 않는다
      (`_accumulate_log` 가 log/step 만 받는다). 그래서 제품 프론트가 실제로 받는 SSE 본문을
      `window.fetch` 래핑 + `body.tee()` 로 **복제만** 해서 세어 둔다. 제품 스트림을 소비하지도
      변형하지도 않는다(tee 한 쪽만 읽고 원본 브랜치를 그대로 돌려준다).
      → 종전보다 오히려 강한 증거다: 프레임이 러너에서 났다는 것뿐 아니라 **브라우저까지
        실제로 도달했다**는 것까지 확인된다.

  약화된 항목(정직 보고): 세션 stream 은 스크린샷을 **창별 최신 1장으로 합쳐** 보낸다
  (`session.py:238`). 따라서 자식 스크린샷 **개수**는 러너 방출수와 같지 않다 — 개수 상한/하한
  비교는 의미를 잃고 `>=1`(도달 여부)만 유효하다. 반면 자식창 **닫힘 전이**는 버퍼(커서) 프레임
  이라 유실 없이 전량 도달한다.

── EAP draft 최소화 = 기간 선별(phase0) ──────────────────────────────────────────
제품 폼(`VoucherPreRunForm`)에는 **max_rows 노브가 없다**. 서버 기본값은 `max_rows=None`
(=조회된 전 건 순회, `voucher_receivable/params.py:30`)이므로 제품 경로는 **기간 안의 전 건**을
처리한다. 결제창을 여는 것만으로 EAP 임시문서가 생기므로(PROCESS.md:30) 기간을 그대로 두면
draft 가 대량 생성된다 — 실측: 2026-07-01~08-31 매출 **177건**(2026-08-03 제품 런, 사용자 취소).

그래서 phase0 에서 **읽기 전용 ERP 조회**로 기간을 이분 탐색해 대상이 1~`MAX_TARGET_ROWS` 건인
부분기간을 찾아 그 날짜를 폼에 넣는다. phase0 은 조회(F2)만 하고 **결재 버튼을 누르지 않으므로
draft 를 단 1건도 만들지 않는다**. 그런 부분기간을 못 찾으면 실행하지 않고 중단한다.

⚠ 날짜 필드를 추정하지 않는 이유(실측 2026-08-03): 결과 그리드의 `ACTG_DT` 도 `WRT_DT` 도 회계일
필터 대상이 아니다 — 20260701~20260731 조회 결과에 `ACTG_DT=20260630` 행이 섞였고, `WRT_DT`
로 좁힌 하루는 실제 조회 시 0건이었다. 필드명을 짚어 그룹핑하면 "하루로 좁혔다"고 **믿고** 대량
처리하게 된다(실제로 1건인 줄 알고 11건을 처리한 회귀가 났다). 그래서 후보 기간마다 직접 조회해
건수를 재고, **잰 값만으로** 판정한다.

⚠⚠ 절대 안전(완화 금지) ⚠⚠
  - 상신·보관 절대 미클릭(그래프가 보장 — 이 하네스는 관찰만).
  - 참조문서 확인(allow_confirm) 절대 미발동 — `refdoc_confirm_never_clicked` 어설션 유지.
  - 이 모듈은 그래프를 조립하지 않는다. 제품이 등록한 워크플로우를 제품 UI 로 실행할 뿐이다.

env: E2E_FRONTEND · E2E_USERID · E2E_PASSWORD · E2E_HEADLESS=0(창 표시) ·
     VOUCHER_MAX_TARGET_ROWS(기간 선별 상한, 기본 3) · VOUCHER_SCAN_MONTHS(역방향 탐색 개월, 기본 3)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Page, async_playwright  # noqa: E402

from app.agents.voucher_receivable import js as v_js  # noqa: E402
from app.agents.voucher_receivable import steps as v_steps  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT  # noqa: E402
from e2e.product_cycle import (  # noqa: E402  — 제품 경로 공통 자산 재사용
    ART,
    HEADLESS,
    PASSWORD,
    SLOW_MO,
    USERID,
    set_date,
)
from nbkit.omnisol.menu_schemas import VOUCHER_RECEIVABLE  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

#: 기간 선별이 허용하는 최대 대상 건수 — 넘으면 실행하지 않는다(EAP draft 폭증 방지).
MAX_TARGET_ROWS = int(os.environ.get("VOUCHER_MAX_TARGET_ROWS", "3"))
#: 대상이 있는 달을 찾기 위해 현재 달부터 역방향으로 훑을 개월 수.
SCAN_MONTHS = int(os.environ.get("VOUCHER_SCAN_MONTHS", "3"))
#: 기간 이분 탐색이 쓸 수 있는 조회 횟수 상한(무한 재귀·ERP 과부하 방지).
QUERY_BUDGET = int(os.environ.get("VOUCHER_QUERY_BUDGET", "16"))


# ═════════════════════════════════════════════════════════════════════════════
# SSE 탭 — 제품 프론트가 실제로 받는 프레임을 **복제**해 센다(소비·변형 없음)
# ═════════════════════════════════════════════════════════════════════════════
#: `POST /runs/collect` 응답 본문을 tee 해 프레임을 집계한다. 원본 브랜치는 그대로 제품에 돌려주므로
#: 스트림 소비자는 하나뿐인 상태를 유지한다(제품 동작 불변). 스크린샷 payload 는 최신 1장만 보관.
SSE_TAP_JS = r"""
(() => {
  if (window.__E2E_TAP) return;
  // seq = 도착 순번. 스텝 구간(loop_approvals running~done)과 자식창 이벤트의 **선후관계**를
  // 복원하기 위해 필요하다 — 종전 하네스가 프레임을 순서대로 받아 하던 구간 게이팅의 대체물.
  const tap = {
    connects: 0, frames: 0, logs: [], steps: [],
    shotParent: 0, shotChild: 0, childClosed: 0,
    childShotSeqs: [], childClosedSeqs: [],
    errors: [], result: null, lastChildShot: null, lastParentShot: null,
  };
  window.__E2E_TAP = tap;

  // 제품(use-live-run.ts:290 consume)과 동일한 레코드 해석 — 해석이 갈리면 관측이 거짓말한다.
  const consumeRecord = (raw) => {
    const line = String(raw).trim();
    if (!line.startsWith('data:')) return;
    const data = line.slice(5).trim();
    if (!data || data === '[DONE]') return;
    let f;
    try { f = JSON.parse(data); } catch (e) { return; }
    const seq = (tap.frames += 1);
    if (f.screenshot != null) {
      if (f.window === 'child') {
        tap.shotChild += 1; tap.lastChildShot = f.screenshot; tap.childShotSeqs.push(seq);
      } else { tap.shotParent += 1; tap.lastParentShot = f.screenshot; }
    } else if (f.closed && f.window === 'child') {
      tap.childClosed += 1; tap.childClosedSeqs.push(seq);
    } else if (f.log != null) {
      tap.logs.push({ seq: seq, level: f.level || 'info', message: String(f.log) });
    } else if (f.step != null) {
      tap.steps.push({
        seq: seq, step: String(f.step), status: f.status == null ? null : String(f.status),
      });
    } else if (f.error != null) {
      tap.errors.push(String(f.error));
    } else if (f.result != null) {
      tap.result = (typeof f.result === 'string') ? f.result : JSON.stringify(f.result);
    }
  };

  const orig = window.fetch;
  window.fetch = async function (...args) {
    const res = await orig.apply(this, args);
    try {
      const a0 = args[0];
      const url = (typeof a0 === 'string') ? a0 : ((a0 && a0.url) || '');
      if (url.indexOf('/runs/collect') >= 0 && res.ok && res.body) {
        tap.connects += 1;
        const [mine, theirs] = res.body.tee();
        (async () => {
          const rd = mine.getReader();
          const dec = new TextDecoder();
          let buf = '';
          try {
            for (;;) {
              const { value, done } = await rd.read();
              if (done) break;
              buf += dec.decode(value, { stream: true });
              const parts = buf.split('\n\n');
              buf = parts.pop() || '';
              for (const p of parts) consumeRecord(p);
            }
            buf += dec.decode();
            if (buf.trim()) for (const p of buf.split('\n\n')) consumeRecord(p);
          } catch (e) { /* abort/끊김 — 관측만 멈춘다 */ }
        })();
        return new Response(theirs, {
          status: res.status, statusText: res.statusText, headers: res.headers,
        });
      }
    } catch (e) { /* 탭 실패가 제품 흐름을 깨뜨리지 않게 한다 */ }
    return res;
  };
})();
"""


async def read_tap(page: Page) -> dict:
    """페이지에 심어 둔 SSE 탭 집계를 걷는다(스크린샷 payload 포함). 실패면 error 키."""
    try:
        return await page.evaluate("() => window.__E2E_TAP || { missing: true }")
    except Exception as exc:  # noqa: BLE001 — 관측 실패는 판정 보조 정보로만 쓴다.
        return {"error": f"tap read 실패: {exc!r}"}


def save_data_url_png(data_url: str, path: Path) -> None:
    """'data:image/jpeg;base64,…' → 파일로 저장(육안 확인용, 확장자만 png 로 통일)."""
    import base64

    prefix = "base64,"
    idx = data_url.find(prefix)
    path.write_bytes(base64.b64decode(data_url[idx + len(prefix) :] if idx >= 0 else data_url))


# ═════════════════════════════════════════════════════════════════════════════
# agent_runs 그라운드트루스 — 로그 기반 어설션의 1차 소스
# ═════════════════════════════════════════════════════════════════════════════
def _psql(sql: str, timeout: int = 30) -> str:
    out = subprocess.run(
        ["docker", "exec", "dashboard-pg", "psql", "-U", "dashboard", "-d", "dashboard",
         "-tA", "-c", sql],
        capture_output=True, text=True, timeout=timeout,
    )
    return (out.stdout or "").strip()


def db_run_logs(run_id: str) -> list[dict]:
    """`agent_runs.logs`(세션이 종료 시 영속한 log/step 프레임) 전량. 조회 실패는 빈 리스트."""
    try:
        raw = _psql(f"SELECT logs::text FROM agent_runs WHERE id = '{run_id}';")
        if not raw:
            return []
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def log_messages(logs: list[dict]) -> list[str]:
    """로그 프레임 중 **메시지 로그만**(step 마커 제외) — 종전 프레임 파싱과 동일 대상."""
    return [str(e.get("message") or "") for e in logs if not e.get("step")]


def step_status(logs: list[dict]) -> dict[str, str]:
    """스텝별 **최종** 상태(done/failed/running). 종전 `frame["step"]/["status"]` 대체."""
    out: dict[str, str] = {}
    for e in logs:
        name, st = e.get("step"), e.get("status")
        if name and st:
            out[str(name)] = str(st)
    return out


def loop_window(tap: dict, step_name: str = "loop_approvals") -> tuple[int, int]:
    """SSE 탭 step 프레임에서 해당 스텝의 [시작 seq, 종료 seq] 구간을 복원한다.

    종전 하네스는 프레임을 순서대로 받아 `in_loop_approvals` 플래그로 자식창 이벤트를 구간
    게이팅했다(결제창이 아닌 코드도우미 팝업을 결제창으로 오판하지 않기 위함 — voucher_card_smoke
    주석의 2026-07-31 실측). 도착 순번(seq)으로 같은 게이팅을 복원한다.
    미도달이면 (0, 0) → 어떤 자식 이벤트도 구간 안으로 세지 않는다.
    """
    start = end = 0
    for s in tap.get("steps") or []:
        if s.get("step") != step_name:
            continue
        seq = int(s.get("seq") or 0)
        if s.get("status") == "running" and start == 0:
            start = seq
        if s.get("status") in ("done", "failed"):
            end = seq
    if start and not end:
        end = 10**9  # 종료 프레임 미도달(타임아웃 등) — 이후 전부를 구간으로 본다.
    return start, end


def count_in_window(seqs: list, window: tuple[int, int]) -> int:
    lo, hi = window
    return sum(1 for s in seqs or [] if lo <= int(s) <= hi) if lo else 0


# ── 노드 로그 파서 — 문구는 app/agents/voucher_* 노드의 emit_log 원문과 1:1 ──────────
_ROWCOUNT_RE = re.compile(r"조회 완료 — 대상 전표 (\d+)건\.")
#: 건별 순회(매입·카드) — "[1/1] 전표 FI… 결제창 확인 중…"
_OPEN_ONE_RE = re.compile(r"^\[(\d+)/(\d+)\] 전표 (\S+) 결제창 확인 중…")
#: 건별 순회 — "[1/1] 가상 상신 완료 — 전표 FI… (누적 1/1건 실행)."
#: ⚠ 전표번호 접두사는 FI 만이 아니다(2026-08-03 실측: 매입 대상이 'TEST2026053100198').
_SUBMIT_ONE_RE = re.compile(r"^\[(\d+)/(\d+)\] 가상 상신 완료 — 전표 (\S+)")
#: 묶음 결재(매출) — "[1/3] 일괄 5건(…) 결재창 확인 중… 전표: FI…, FI…"  (‘결재창’·콜론 표기)
_OPEN_BATCH_RE = re.compile(r"^\[(\d+)/(\d+)\] .*결재창 확인 중… 전표: (.*)$")
#: 묶음 결재 — "[1/3] 가상 상신 완료 — 5건 (누적 5/12건)."  (전표번호가 이 줄엔 없다)
_SUBMIT_BATCH_RE = re.compile(r"^\[(\d+)/(\d+)\] 가상 상신 완료 — (\d+)건")
_DOCU_TOKEN_RE = re.compile(r"[A-Z]{2,8}\d{8,}")


def parse_common(msgs: list[str]) -> dict:
    """3종 공통 로그 관측치 — 종전 프레임 파싱과 **동일 문구·동일 의미**로 재현한다.

    건별(매입·카드)과 묶음(매출) 두 순회 모드의 문구를 모두 받는다. 묶음 모드는 '가상 상신 완료'
    줄에 전표번호가 없으므로, 같은 묶음 번호의 '결재창 확인 중' 줄에서 잡아 둔 번호를 확정한다.
    """
    out: dict = {
        "params_log": None, "set_query_ok_log": None, "rowcount": None,
        "opened_docu_nos": [], "processed_docu_nos": [], "virtual_submit_logs": [],
        # 결제창을 **연 횟수** — 곧 생성되는 EAP 임시문서(draft) 수다(묶음 결재는 1회에 N건).
        "approval_opens": 0,
        "d7_ok": [], "d7_soft": [], "d7_mismatch": [],
        "d7_checked_ok": [], "d7_checked_soft": [], "d7_recheck": [],
        "batch_mode": False,
    }
    pending: dict[str, list[str]] = {}  # 묶음번호 → 그 묶음이 연 전표번호들
    for msg in msgs:
        if msg.startswith("실행 파라미터 확인"):
            out["params_log"] = msg
        elif msg.startswith("조회 조건 세팅 완료"):
            out["set_query_ok_log"] = msg
        rc = _ROWCOUNT_RE.search(msg)
        if rc:
            out["rowcount"] = int(rc.group(1))

        m = _OPEN_ONE_RE.match(msg)
        if m:
            out["opened_docu_nos"].append(m.group(3))
            out["approval_opens"] += 1
        else:
            mb = _OPEN_BATCH_RE.match(msg)
            if mb:
                out["batch_mode"] = True
                keys = _DOCU_TOKEN_RE.findall(mb.group(3))
                pending[mb.group(1)] = keys
                out["opened_docu_nos"].extend(keys)
                out["approval_opens"] += 1

        if "가상 상신" in msg:
            out["virtual_submit_logs"].append(msg)
        ms = _SUBMIT_ONE_RE.match(msg)
        if ms:
            out["processed_docu_nos"].append(ms.group(3))
        else:
            msb = _SUBMIT_BATCH_RE.match(msg)
            if msb:
                out["processed_docu_nos"].extend(pending.get(msb.group(1)) or [])

        if msg.startswith("D7 정합성 확인 ✅"):
            out["d7_ok"].append(msg)
        elif msg.startswith("D7 정합성 확인 불가") or msg.startswith("D7 부분 확인(soft)"):
            out["d7_soft"].append(msg)
        elif "D7 정합성 오류" in msg:
            out["d7_mismatch"].append(msg)
        elif msg.startswith("D7 체크행수 확인 ✅") or msg.startswith("D7 체크행 확인 ✅"):
            # 배치 노드는 '체크행 확인', 건별 노드는 '체크행수 확인' — 두 문구 모두 수용.
            out["d7_checked_ok"].append(msg)
        elif msg.startswith("D7 체크행수 확인 불가") or msg.startswith("D7 체크행 확인 불가"):
            out["d7_checked_soft"].append(msg)
        elif msg.startswith("D7 체크행수 불일치"):
            out["d7_recheck"].append(msg)
    return out


def print_checks(checks: dict[str, bool]) -> bool:
    print("\n===== SMOKE ASSERTIONS =====", flush=True)
    for k, v in checks.items():
        print(f"{'PASS' if v else 'FAIL'} — {k}", flush=True)
    ok = all(checks.values())
    print(f"\n===== {'ALL PASS' if ok else 'SOME FAILED'} =====", flush=True)
    return ok


# ═════════════════════════════════════════════════════════════════════════════
# phase0 — 읽기 전용 기간 선별(결재 버튼 미클릭 → EAP draft 0건)
# ═════════════════════════════════════════════════════════════════════════════
def _month_window(back: int) -> tuple[str, str]:
    """오늘로부터 back 개월 전 달의 1일~말일 (YYYYMMDD, YYYYMMDD)."""
    t = date.today()
    y, m = t.year, t.month - back
    while m <= 0:
        y, m = y - 1, m + 12
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    last = (date(ny, nm, 1) - date.resolution).day
    return f"{y:04d}{m:02d}01", f"{y:04d}{m:02d}{last:02d}"


async def _set_conditions(page: Page, docu_types: tuple[str, ...]) -> None:
    """조회 조건 세팅 — `nodes/query.py:set_query` 와 **동일 순서·동일 함수**를 호출한다.

    같은 `steps` 모듈을 쓰므로 제품 조건과 갈라질 여지가 없다(조건이 다르면 선별 자체가 무의미).
    """
    await v_steps.expand_condition_panel(page)
    for label, coro in (
        ("작성부서", v_steps.set_dept_all(page)),
        ("작성자", v_steps.clear_writer(page)),
        ("전표상태", v_steps.set_docu_status(page)),
        ("전자결재상태", v_steps.set_gwaprvlst(page)),
        ("전표유형", v_steps.set_docu_types(page, docu_types)),
    ):
        r = await coro
        if not r.get("ok"):
            raise RuntimeError(f"[P0] 조회조건 '{label}' 세팅 실패: {r.get('reason')}")


async def _query_window(page: Page, start: str, end: str) -> dict:
    """기간만 바꿔 재조회 → {rowcount, rows}. 조회 실패는 예외."""
    r = await v_steps.set_period(page, start, end)
    if not r.get("ok"):
        raise RuntimeError(f"[P0] 회계일 {start}~{end} 세팅 실패: {r.get('reason')}")
    q = await v_steps.run_query(page)
    if not q.get("ok"):
        raise RuntimeError(f"[P0] 조회 실패: {q.get('reason')}")
    n = int(q.get("rowcount") or 0)
    dump = await page.evaluate(v_js.MASTER_DUMP_JS, max(n, 1))
    rows = dump.get("sample") or [] if isinstance(dump, dict) else []
    return {"rowcount": n, "rows": rows, "fields": list(rows[0].keys()) if rows else []}


def _as_day(v: object) -> str | None:
    """값 → 'YYYYMMDD'(표기가 '2026-07-28'·ISO 타임스탬프 등으로 갈려도 흡수). 아니면 None."""
    digits = "".join(c for c in str(v or "") if c.isdigit())
    if len(digits) < 8:
        return None
    y, m, d = digits[:4], digits[4:6], digits[6:8]
    if "1900" <= y <= "2999" and "01" <= m <= "12" and "01" <= d <= "31":
        return digits[:8]
    return None


def _d(yyyymmdd: str) -> date:
    return date(int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:8]))


def _s(d: date) -> str:
    return f"{d.year:04d}{d.month:02d}{d.day:02d}"


async def pick_period(docu_types: tuple[str, ...], *, tag: str) -> dict:
    """phase0 — 대상이 가장 적은(≥1) **하루**를 고른다. 조회만 하고 결재는 열지 않는다.

    반환 ``{picked_from, picked_to, target_rows, by_day, windows, error}``.
    대상이 있는 달을 못 찾으면 picked_* 가 None(호출자가 '0건 경로'로 진행할지 결정).
    """
    out: dict = {"picked_from": None, "picked_to": None, "target_rows": None,
                 "by_day": {}, "windows": [], "queries": [], "error": None}
    settings = get_settings()
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO)
    ctx = await browser.new_context(viewport=LIVE_VIEWPORT)
    page = await ctx.new_page()
    try:
        print("[P0] ERP 직접 로그인(읽기 전용 기간 선별 — 결재 버튼 미클릭)…", flush=True)
        await ensure_logged_in(page, USERID, PASSWORD, settings.erp_base)
        await ensure_user_type(page, "회계")
        await navigate_schema(page, VOUCHER_RECEIVABLE, settings.erp_base)
        await _set_conditions(page, docu_types)

        budget = [QUERY_BUDGET]

        async def measure(lo: str, hi: str) -> int:
            """이 기간을 **실제로 조회해** 건수를 잰다. 추정하지 않는다."""
            budget[0] -= 1
            res = await _query_window(page, lo, hi)
            out["queries"].append({"from": lo, "to": hi, "rowcount": res["rowcount"]})
            print(f"[P0] {lo}~{hi} → {res['rowcount']}건", flush=True)
            if res["rowcount"] > 0 and not out["by_day"]:
                # 참고용 분포(진단 출력에만 쓴다 — 판정은 오직 측정값으로 한다).
                out["by_day"] = dict(sorted(Counter(
                    d for d in (_as_day(r.get("ACTG_DT")) for r in res["rows"]) if d
                ).items()))
            return res["rowcount"]

        async def narrow(lo: str, hi: str, n: int) -> tuple[str, str, int] | None:
            """[lo,hi] 를 이분해 대상이 1~MAX_TARGET_ROWS 건인 부분기간을 찾는다.

            ⚠ 날짜 필드를 **추정하지 않는다**. 어느 컬럼이 회계일 필터에 걸리는지는 화면마다
            다르고(실측 2026-08-03: ACTG_DT·WRT_DT 둘 다 아님), 필드를 잘못 짚으면 '하루로
            좁혔다'고 믿고 대량 처리하게 된다 — 실제로 그 회귀가 났다(1건인 줄 알고 11건 처리).
            그래서 후보 기간마다 **직접 조회해 건수를 재고**, 잰 값만으로 판정한다.
            """
            if n <= 0 or budget[0] <= 0:
                return None
            if n <= MAX_TARGET_ROWS:
                return lo, hi, n
            if lo == hi:
                return None  # 하루인데도 상한 초과 — 더 좁힐 수 없다.
            a, b = _d(lo), _d(hi)
            mid = a + (b - a) // 2
            halves = ((lo, _s(mid)), (_s(mid + timedelta(days=1)), hi))
            for sub_lo, sub_hi in halves:
                if budget[0] <= 0:
                    break
                got = await narrow(sub_lo, sub_hi, await measure(sub_lo, sub_hi))
                if got:
                    return got
            return None

        for back in range(SCAN_MONTHS):
            start, end = _month_window(back)
            n = await measure(start, end)
            out["windows"].append({"from": start, "to": end, "rowcount": n})
            if n <= 0:
                continue
            got = await narrow(start, end, n)
            if got:
                out["picked_from"], out["picked_to"], out["target_rows"] = got
                print(f"[P0] 선택 {got[0]}~{got[1]} — 실측 {got[2]}건", flush=True)
            else:
                out["error"] = (
                    f"{start}~{end}({n}건)에서 대상 1~{MAX_TARGET_ROWS}건인 부분기간을 찾지 "
                    f"못했습니다(조회 {len(out['queries'])}회, 잔여예산 {budget[0]}) — {out['queries']}"
                )
            break
        await page.screenshot(path=str(ART / f"{tag}_p0_scan.png"))
    except Exception as exc:  # noqa: BLE001 — 선별 실패는 리포트로 돌려 상위가 중단하게 한다.
        out["error"] = f"phase0 예외: {exc!r}"
        print(f"[P0][ERROR] {out['error']}", flush=True)
        try:
            await page.screenshot(path=str(ART / f"{tag}_p0_exception.png"))
        except Exception:  # noqa: BLE001
            pass
    finally:
        await ctx.close()
        await browser.close()
        await pw.stop()
    return out


def iso(yyyymmdd: str) -> str:
    """'YYYYMMDD' → 'YYYY-MM-DD'(프론트 DatePicker 규약)."""
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


async def fill_period(page: Page, from_iso: str, to_iso: str) -> None:
    """`VoucherPreRunForm` 의 두 DatePicker 를 **실제 달력 클릭**으로 채운다."""
    await set_date(page, "회계일 시작일", from_iso)
    await set_date(page, "회계일 종료일", to_iso)


__all__ = [
    "ART", "MAX_TARGET_ROWS", "SSE_TAP_JS", "USERID",
    "count_in_window", "db_run_logs", "fill_period", "iso",
    "log_messages", "loop_window", "parse_common", "pick_period", "print_checks",
    "read_tap", "save_data_url_png", "step_status",
]
