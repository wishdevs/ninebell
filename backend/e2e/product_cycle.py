"""제품 경로 e2e 공통 모듈 — **우리 시스템(대시보드 UI)에서 작성 → ERP 에서 삭제**.

배경(사용자 지적 2026-08-03): 결의서입력 4종 사이클 스모크(trip/overseas/gyeongjo/hakjagum)는
`build_*_graph()` 를 스크립트가 직접 `ainvoke` 해서 **ERP 에서 작성하고 ERP 에서 지웠다**.
그래서 프론트 pre-run 폼 → `runs.py` collect 의 서버 권위 params 주입 → 러너(세마포어·SSE·
스크린캐스트·시간예산 워치독·저장 shield) → agent_runs 기록이 전부 미검증이었고, 스크립트가
params 를 손으로 조립하다 프로덕션 계약과 어긋나 국내출장 e2e 가 3주간 로그인조차 못 했다.

정답 패턴은 `e2e/e2e_smoke.py`(법인카드)다 — phase1 은 제품 UI(:3101)를 몰고, phase2 는 ERP 에
직접 붙어 F6 삭제한다. 이 모듈은 그 두 페이즈의 재사용 가능한 부분을 뽑아 4종이 공유한다.

  phase1(제품): 대시보드 로그인 → /agents/<id> → **pre-run 폼을 실제 DOM 으로 채움** → 실행
                → 종료 대기 → agent_runs 그라운드트루스 조회.
  phase2(ERP) : 별도 브라우저로 ERP 직접 로그인 → GLDDOC00300 → 결의구분 필터 → 조회 →
                **3중 가드(결의자=계정·결의구분·미결)** → 상세 대조 → F6 → 잔존 0 확인.

⚠ 안전 수칙(4종 공통, 완화 금지)
  - **상신(결재) 절대 금지.** F7 저장·F6 삭제만.
  - 삭제 3중 가드 완화 금지 — 가드가 삭제를 막으면 정상 동작이니 강제하지 말고 보고한다.
  - 삭제까지가 한 사이클 — 잔존 0 검증 없이는 다음 사이클 진행 금지.

env: E2E_FRONTEND(기본 http://localhost:3101) · E2E_USERID · E2E_PASSWORD ·
     E2E_HEADLESS=0 이면 브라우저 창 표시(기본 헤드리스).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import date as _date
from pathlib import Path
from typing import Awaitable, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Locator, Page, async_playwright  # noqa: E402

from app.agents.card_collect import js as cc_js  # noqa: E402 — MODAL_* JS
from app.config import get_settings  # noqa: E402
from nbkit.grid.provider import GridProvider  # noqa: E402
from nbkit.grid.strategies import CollectionStrategy, GridExtractor  # noqa: E402
from nbkit.omnisol import js_lib, selectors  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# env / 상수
# ─────────────────────────────────────────────────────────────────────────────
FRONTEND_BASE = os.environ.get("E2E_FRONTEND", "http://localhost:3101")
USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
# 브라우저 표시 여부 — E2E_HEADLESS=0 이면 창을 띄워 진행을 눈으로 확인할 수 있다(기본 헤드리스).
HEADLESS = os.environ.get("E2E_HEADLESS", "1").strip().lower() not in ("0", "false", "no")
SLOW_MO = 0 if HEADLESS else 60

ART = Path(__file__).resolve().parent / "artifacts"
ART.mkdir(exist_ok=True)

TODAY = _date.today().isoformat()

# 폼 제출 후 종료(닫기 버튼)까지 상한 — 그래프가 헤드리스로 ERP 를 완주하는 시간(실측 30~120s)에
# 러너 큐 대기·로그인 지연을 얹어 잡는다. 서버 활동예산(run_active_budget_s=1200s)보다 짧게 둔다.
RESULT_WAIT_TIMEOUT_S = int(os.environ.get("E2E_RUN_TIMEOUT_S", "600"))
# 폼이 뜰 때까지(에이전트 상세 로드 + 즐겨찾기/기본 프로젝트 비동기 확정) 상한.
FORM_WAIT_TIMEOUT_MS = 30_000

# ─────────────────────────────────────────────────────────────────────────────
# ERP 페이지 in-page JS — GLDDOC00300 조회/덤프/선택 (e2e_smoke 에서 이관, 단일 소스)
# ─────────────────────────────────────────────────────────────────────────────
BTN_BOX_JS = """(sel) => {
  const b = document.querySelector(sel);
  if (!b) return null;
  const r = b.getBoundingClientRect();
  if (r.width === 0 || r.height === 0) return null;
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

MASTER_ROWCOUNT_JS = ("() => { try { return window.jQuery(document.querySelectorAll('.dews-ui-grid')[0])"
                      ".data('dewsControl')._grid.getDataSource().getRowCount(); } catch(e) { return -1; } }")

MASTER_DUMP_JS = """(index) => {
  try {
    const ctrl = window.jQuery(document.querySelectorAll('.dews-ui-grid')[index]).data('dewsControl');
    const g = ctrl._grid;
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    let columns = [];
    try {
      const cols = g.getColumns ? g.getColumns() : [];
      columns = cols.map(c => ({
        field: c.fieldName || c.name || c.field || null,
        header: (c.header && (c.header.text || c.header.caption)) || c.caption || c.title || c.headerText || null
      }));
    } catch (e) { columns = [{ err: String(e).slice(0, 100) }]; }
    const rows = n > 0 ? ds.getJsonRows(0, n - 1) : [];
    return { n, columns, fieldKeys: rows[0] ? Object.keys(rows[0]) : null, rows };
  } catch (e) { return { n: -1, err: String(e).slice(0, 160) }; }
}"""

SELECT_MASTER_JS = """(index) => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[index]).data('dewsControl')._grid;
    const n = g.getDataSource().getRowCount();
    let via = [];
    try { if (g.checkAll) { g.checkAll(true); via.push('checkAll'); } } catch (e) {}
    try { if (g.setAllCheckState) { g.setAllCheckState(true); via.push('setAllCheckState'); } } catch (e) {}
    try { g.setCurrent({ itemIndex: 0 }); via.push('setCurrent0'); } catch (e) {}
    return { ok: true, n, via };
  } catch (e) { return { ok: false, err: String(e).slice(0, 120) }; }
}"""

#: 상세(디테일) 행에서 검증에 쓰는 필드만 추린 정규화 — 4종 사이클 스크립트가 공유한다.
#: SPPRC_AMT2=공급가액 · SPPRC_AMT=거래금액 · TOTAL_AMT=합계 · PARTNER_NM=거래처 · NOTE_DC=적요.
DETAIL_FIELDS = ("SPPRC_AMT2", "SPPRC_AMT", "TOTAL_AMT", "PARTNER_NM", "NOTE_DC")


def detail_view(rows: list[dict]) -> list[dict]:
    """디테일 원본 행 → 검증 필드만 문자열로 추린 뷰(리포트·대조용)."""
    return [{k: str(r.get(k) if r.get(k) is not None else "") for k in DETAIL_FIELDS} for r in rows]


def as_int(v: object) -> int | None:
    """그리드 금액 문자열 → int(콤마·소수점 0 허용). 파싱 불가면 None(불일치로 단정하지 않는다)."""
    s = str(v if v is not None else "").replace(",", "").strip()
    if not s:
        return None
    if s.endswith(".0") or s.endswith(".00"):
        s = s.split(".")[0]
    try:
        return int(s)
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# agent_runs 그라운드트루스 — 제품 경로를 탔다는 증거(그래프 직접 호출은 런을 남기지 않는다)
# ─────────────────────────────────────────────────────────────────────────────
def db_run_by_id(run_id: str) -> dict | None:
    """agent_runs 단일 행(id 고정) — 판정을 **이 사이클이 만든 런**에 묶는다.

    ⚠ latest 기반 판정은 사이클이 중첩되면 다른 사이클의 런을 집어 오염된다(2026-08-07
    20회 배치 실측: stale-terminal 조기 이탈 → 런 중첩 → latest 오독 연쇄).
    """
    sql = (
        "SELECT id || E'\\t' || status || E'\\t' || coalesce(replace(result::text, E'\\n', ' '), '')"
        " || E'\\t' || started_at "
        f"FROM agent_runs WHERE id = '{run_id}' LIMIT 1;"
    )
    return _db_run_row(sql)


def db_latest_run(workflow_id: str) -> dict | None:
    """agent_runs 최신 1행(id·status·result·started_at). 조회 실패/미존재는 None."""
    sql = (
        "SELECT id || E'\\t' || status || E'\\t' || coalesce(replace(result::text, E'\\n', ' '), '')"
        " || E'\\t' || started_at "
        f"FROM agent_runs WHERE agent_id = '{workflow_id}' ORDER BY started_at DESC LIMIT 1;"
    )
    return _db_run_row(sql)


def _db_run_row(sql: str) -> dict | None:
    try:
        out = subprocess.run(
            ["docker", "exec", "dashboard-pg", "psql", "-U", "dashboard", "-d", "dashboard",
             "-tA", "-c", sql],
            capture_output=True, text=True, timeout=20,
        )
        line = (out.stdout or "").strip()
        if not line:
            return None
        parts = line.split("\t")
        if len(parts) < 4:
            return None
        return {"id": parts[0], "status": parts[1], "result": parts[2][:400], "started_at": parts[3]}
    except Exception as exc:  # noqa: BLE001 — 그라운드트루스 조회 실패는 판정 보조 정보로만 쓴다.
        return {"error": f"db check failed: {exc!r}"}


# ─────────────────────────────────────────────────────────────────────────────
# phase1 — 제품 UI(폼 위젯) 조작 헬퍼
# ─────────────────────────────────────────────────────────────────────────────
async def dashboard_login(page: Page) -> None:
    """대시보드(:3101) 로그인 — /login 폼 제출 후 리다이렉트까지 확인. 실패면 예외."""
    await page.goto(FRONTEND_BASE)
    await page.wait_for_timeout(1_000)
    await page.fill("#userid", USERID)
    await page.fill("#password", PASSWORD)
    await page.get_by_role("button", name="로그인").click()
    for _ in range(40):
        if "/login" not in page.url:
            return
        await page.wait_for_timeout(500)
    raise RuntimeError(f"대시보드 로그인 실패 — /login 에서 벗어나지 못함(url={page.url})")


async def open_agent(page: Page, agent_id: str) -> None:
    """에이전트 상세로 이동해 **실행 전 입력 폼**이 렌더될 때까지 대기."""
    await page.goto(f"{FRONTEND_BASE}/agents/{agent_id}")
    await page.get_by_text("실행 전 입력").first.wait_for(timeout=FORM_WAIT_TIMEOUT_MS)
    # 즐겨찾기·팀 기본 프로젝트(두 비동기 소스)가 확정돼 기본값 백필이 끝날 때까지 여유.
    await page.wait_for_timeout(2_500)


def row_scope(page: Page, row_no: int) -> Locator:
    """표 폼(출장 국내/해외)의 row_no(1-base) 행 컨테이너.

    행 안의 계산서일 DatePicker(aria-label ``N행 계산서일``)를 앵커로 잡아 두 단계 위(셀→행)로
    올라간다 — 행 컨테이너에 안정적인 test id 가 없고 grid 클래스는 레이아웃 변경에 취약해서다.
    """
    return page.get_by_label(f"{row_no}행 계산서일").locator("xpath=../..")


async def pick_combo(page: Page, scope: Locator, index: int, query: str, match: str) -> None:
    """CatalogCombobox(거래처·프로젝트) 실조작 — 트리거 클릭 → 검색어 입력 → 옵션 클릭.

    ``index`` 는 행(또는 폼) 안에서 몇 번째 콤보박스인지(출장 국내 통행료 행은 0=프로젝트,
    1=거래처). ``query`` 로 자주쓰는 목록이 걸러지면 그대로 고르고, 없으면 **검색 버튼**을 눌러
    ERP/카탈로그 검색 결과에서 고른다. 선택 후 트리거 표시값으로 반영을 확인한다.

    옵션 탐색은 팝오버(트리거의 형제 div)로 한정한다 — 래퍼 전체로 잡으면 이미 같은 값을 표시
    중인 **트리거 자신**이 후보로 걸려 팝오버를 닫아버린다.
    """
    trigger = scope.locator('button[title="검색하여 선택"]').nth(index)
    await trigger.wait_for(state="visible", timeout=10_000)
    await trigger.click()
    pop = trigger.locator("xpath=following-sibling::div[1]")
    box = pop.locator('input[placeholder="자주쓰는 필터 / ERP 검색어"]')
    await box.wait_for(state="visible", timeout=5_000)
    await box.fill(query)
    await page.wait_for_timeout(400)

    option = pop.get_by_role("button").filter(has_text=match)
    if await option.count() == 0:
        # 자주쓰는에 없음 → ERP/카탈로그 검색.
        await pop.get_by_role("button", name="검색").click()
        for _ in range(30):
            await page.wait_for_timeout(500)
            if await option.count() > 0:
                break
    if await option.count() == 0:
        raise RuntimeError(f"콤보박스에서 '{match}' 옵션을 찾지 못했습니다(query={query!r}).")
    await option.first.click()
    await page.wait_for_timeout(300)
    shown = (await trigger.inner_text()).strip()
    if match not in shown:
        raise RuntimeError(f"콤보박스 선택 반영 실패 — 기대 '{match}', 표시 '{shown}'")


async def set_select(page: Page, scope: Locator, aria_label: str, option_name: str) -> None:
    """디자인 셀렉트(Radix) 실조작 — 트리거 클릭 → 포털 옵션 클릭 → 트리거 표시값 확인.

    옵션의 접근가능 이름에는 hint(연비·단가)가 붙을 수 있어 **부분일치**로 찾는다.
    """
    trigger = scope.get_by_role("combobox", name=aria_label)
    await trigger.wait_for(state="visible", timeout=10_000)
    await trigger.click()
    opt = page.get_by_role("option", name=option_name)
    await opt.first.wait_for(state="visible", timeout=5_000)
    await opt.first.click()
    await page.wait_for_timeout(400)
    shown = (await trigger.inner_text()).strip()
    if option_name not in shown:
        raise RuntimeError(f"셀렉트 '{aria_label}' 선택 반영 실패 — 기대 '{option_name}', 표시 '{shown}'")


async def set_date(page: Page, aria_label: str, iso: str) -> None:
    """DatePicker(팝오버 달력) **실조작** — 트리거 열기 → 이전/다음 달 이동 → 날짜 셀 클릭.

    기본값이 이미 오늘이라도 우회하지 않고 실제로 열어 클릭한다(달력 위젯 자체가 검증 대상).
    """
    y, m, d = (int(x) for x in iso.split("-"))
    trigger = page.get_by_label(aria_label)
    await trigger.wait_for(state="visible", timeout=10_000)
    await trigger.click()
    prev_btn = page.get_by_role("button", name="이전 달")
    await prev_btn.wait_for(state="visible", timeout=5_000)
    cal = prev_btn.locator("xpath=../..")  # 헤더 div → PopoverContent
    label = prev_btn.locator("xpath=../span")
    for _ in range(36):
        cur = (await label.inner_text()).strip()  # 'YYYY. MM'
        cy, cm = (int(p.strip()) for p in cur.split("."))
        if (cy, cm) == (y, m):
            break
        if (cy, cm) > (y, m):
            await prev_btn.click()
        else:
            await page.get_by_role("button", name="다음 달").click()
        await page.wait_for_timeout(150)
    else:
        raise RuntimeError(f"달력에서 {iso} 의 달로 이동하지 못했습니다.")
    await cal.get_by_role("button", name=str(d), exact=True).click()
    await page.wait_for_timeout(250)
    shown = (await trigger.inner_text()).strip()
    if iso not in shown:
        raise RuntimeError(f"날짜 선택 반영 실패 — 기대 {iso}, 표시 '{shown}'")


async def set_switch(page: Page, aria_label: str, on: bool) -> None:
    """토글 스위치(role=switch) 실조작 — 목표 상태와 다르면 클릭하고 aria-checked 로 확인."""
    sw = page.get_by_role("switch", name=aria_label)
    await sw.wait_for(state="visible", timeout=10_000)
    cur = (await sw.get_attribute("aria-checked")) == "true"
    if cur != on:
        await sw.click()
        await page.wait_for_timeout(250)
    now = (await sw.get_attribute("aria-checked")) == "true"
    if now != on:
        raise RuntimeError(f"스위치 '{aria_label}' 반영 실패 — 기대 {on}, 현재 {now}")


async def add_row(page: Page) -> None:
    """표 폼의 '행 추가' 버튼 클릭."""
    await page.get_by_role("button", name="행 추가").click()
    await page.wait_for_timeout(400)


async def submit_pre_run(page: Page) -> None:
    """폼의 '실행' 버튼(활성 상태인 것) 클릭 — 헤더 '실행'은 pre-run 에이전트에서 항상 비활성이다."""
    buttons = page.get_by_role("button", name="실행", exact=True)
    total = await buttons.count()
    for i in range(total):
        b = buttons.nth(i)
        if await b.is_visible() and await b.is_enabled():
            await b.click()
            return
    raise RuntimeError(f"활성 '실행' 버튼을 찾지 못했습니다(후보 {total}개 — 필수 입력 미완료?).")


async def wait_terminal_by_db(page: Page, run_id: str, timeout_s: int = RESULT_WAIT_TIMEOUT_S) -> dict:
    """**이 런(run_id)의 DB 상태가 종결**될 때까지 대기 — UI '닫기' 단독 판정의 오인 차단.

    ⚠ 근본원인(2026-08-07 20회 배치 실측): '닫기' 버튼은 **이전 런의 결과 패널**에도 떠 있어,
    반복 사이클에서 새 런 제출 직후 stale 패널을 종료로 오인 → 조기 이탈 → 다음 사이클과 런
    중첩 → 자동 취소 연쇄가 났다. 판정은 run_id 의 DB 종결 상태(succeeded/failed/cancelled)로
    하고, UI 텍스트(결과/실패사유)는 종결 후 **보조 관측**으로만 걷는다.
    """
    out: dict = {"terminal": False, "ui_status": None, "result_text": None, "fail_reason": None,
                 "db_status": None}
    elapsed = 0
    st = None
    while elapsed < timeout_s:
        row = db_run_by_id(run_id)
        st = (row or {}).get("status")
        if st in ("succeeded", "failed", "cancelled"):
            out["terminal"] = True
            out["db_status"] = st
            break
        await asyncio.sleep(3)
        elapsed += 3
        if elapsed % 30 < 3:
            print(f"[P1] ...종료 대기 {elapsed}s (run={run_id[:8]} status={st})", flush=True)
    if not out["terminal"]:
        return out
    try:
        await page.wait_for_timeout(1_500)  # UI 렌더 유예 — 텍스트 수집은 보조 관측.
        banner = page.get_by_text("실행 실패 — 사유")
        if await banner.count() > 0 and await banner.first.is_visible():
            out["ui_status"] = "failed"
            out["fail_reason"] = (await banner.first.locator("xpath=..").inner_text()).strip()[:600]
        else:
            out["ui_status"] = out["db_status"]
        done = page.get_by_text("처리 완료")
        for i in range(await done.count()):
            loc = done.nth(i)
            if await loc.is_visible():
                out["result_text"] = (await loc.inner_text()).strip()[:400]
                break
    except Exception:  # noqa: BLE001 — UI 수집 실패는 판정에 영향 없음(판정은 DB).
        pass
    return out


async def wait_terminal(page: Page, timeout_s: int = RESULT_WAIT_TIMEOUT_S) -> dict:
    """종료(헤더 '닫기' 노출)까지 대기하고 화면에서 읽히는 결과/실패사유를 수집.

    ⚠ 반복 사이클에는 쓰지 말 것 — '닫기'는 이전 런 패널에도 떠 stale-terminal 오인이 있다.
    run_product 는 wait_terminal_by_db(런 id 고정)로 판정한다(2026-08-07)."""
    out: dict = {"terminal": False, "ui_status": None, "result_text": None, "fail_reason": None}
    close_btn = page.get_by_role("button", name="닫기", exact=True)
    elapsed = 0
    while elapsed < timeout_s:
        if await close_btn.count() > 0 and await close_btn.first.is_visible():
            out["terminal"] = True
            break
        await page.wait_for_timeout(5_000)
        elapsed += 5
        if elapsed % 30 == 0:
            print(f"[P1] ...종료 대기 {elapsed}s", flush=True)
    if not out["terminal"]:
        return out
    await page.wait_for_timeout(1_500)
    banner = page.get_by_text("실행 실패 — 사유")
    if await banner.count() > 0 and await banner.first.is_visible():
        out["ui_status"] = "failed"
        out["fail_reason"] = (await banner.first.locator("xpath=..").inner_text()).strip()[:600]
    else:
        out["ui_status"] = "succeeded"
    done = page.get_by_text("처리 완료")
    for i in range(await done.count()):
        loc = done.nth(i)
        if await loc.is_visible():
            out["result_text"] = (await loc.inner_text()).strip()[:400]
            break
    return out


async def run_product(
    *,
    agent_id: str,
    workflow_id: str,
    fill: Callable[[Page], Awaitable[None]],
    tag: str,
    timeout_s: int = RESULT_WAIT_TIMEOUT_S,
    init_script: str | None = None,
    on_page_done: Callable[[Page], Awaitable[dict]] | None = None,
) -> dict:
    """phase1 — 제품 UI 완주(로그인 → 폼 채움 → 실행 → 종료 → agent_runs 확인).

    반환 dict 의 ``run_recorded`` 가 True 면 이 실행이 **제품 경로(runs.py collect → 러너)** 를
    탔다는 증거다(그래프 직접 호출은 agent_runs 행을 만들지 않는다).

    선택 훅(둘 다 기본 None → 결의서입력 4종 동작 불변):
      init_script   첫 내비게이션 **전에** 심을 페이지 초기화 스크립트. 회계전표 3종이 SSE
                    프레임 탭(스크린샷·자식창 닫힘 관측)을 심는 데 쓴다.
      on_page_done  종료 판정 직후 **브라우저를 닫기 전에** 페이지에서 무언가를 걷어오는 훅.
                    반환 dict 는 리포트의 ``page_probe`` 로 실린다.
    """
    report: dict = {
        "logged_in": False, "form_filled": False, "submitted": False, "terminal": False,
        "ui_status": None, "result_text": None, "fail_reason": None,
        "run_before": None, "run_after": None, "run_id": None, "run_recorded": False, "db_status": None,
        "screenshot": None, "error": None, "page_probe": None,
    }
    report["run_before"] = db_latest_run(workflow_id)

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO)
    ctx = await browser.new_context(viewport={"width": 1600, "height": 1000})
    if init_script:
        await ctx.add_init_script(init_script)
    page = await ctx.new_page()
    try:
        print(f"[P1] 대시보드 로그인({FRONTEND_BASE})…", flush=True)
        await dashboard_login(page)
        report["logged_in"] = True
        print(f"[P1] 로그인 완료 url={page.url}", flush=True)

        print(f"[P1] /agents/{agent_id} 진입 — 실행 전 입력 폼 대기", flush=True)
        await open_agent(page, agent_id)

        await fill(page)
        report["form_filled"] = True
        await page.screenshot(path=str(ART / f"{tag}_p1_form.png"))
        print(f"[P1] 폼 입력 완료 — screenshot {tag}_p1_form.png", flush=True)

        await submit_pre_run(page)
        report["submitted"] = True

        # 새 런 행 출현 대기 — 제출이 실제로 런을 만들었는지 확인하고 이후 모든 판정을 그 id 에
        # 묶는다(latest 오독·stale-terminal 오염 차단, 2026-08-07).
        before_id = (report["run_before"] or {}).get("id")
        run_id = None
        for _ in range(20):
            latest = db_latest_run(workflow_id)
            if latest and latest.get("id") and latest.get("id") != before_id:
                run_id = latest["id"]
                break
            await asyncio.sleep(1)
        report["run_id"] = run_id
        if run_id is None:
            report["error"] = "실행 클릭 후 20s 안에 새 agent_runs 행이 나타나지 않았습니다."
            term = {"terminal": False, "ui_status": None, "result_text": None, "fail_reason": None}
        else:
            print(f"[P1] 실행 클릭 — run={run_id[:8]} 종료까지 최대 {timeout_s}s 대기", flush=True)
            term = await wait_terminal_by_db(page, run_id, timeout_s)
        report.update({k: term[k] for k in ("terminal", "ui_status", "result_text", "fail_reason")})
        shot = str(ART / f"{tag}_p1_result.png")
        await page.screenshot(path=shot, full_page=True)
        report["screenshot"] = shot
        if not term["terminal"]:
            report["error"] = f"{timeout_s}s 안에 종료(닫기)에 도달하지 못했습니다."
        if on_page_done is not None:
            # ⚠ 브라우저를 닫기 전에 걷는다 — 페이지가 사라지면 관측 자체가 불가능하다.
            report["page_probe"] = await on_page_done(page)
    except Exception as exc:  # noqa: BLE001 — 실패도 리포트로 돌려 상위가 사이클을 끊게 한다.
        report["error"] = f"phase1 예외: {exc!r}"
        try:
            await page.screenshot(path=str(ART / f"{tag}_p1_exception.png"))
        except Exception:  # noqa: BLE001
            pass
    finally:
        await ctx.close()
        await browser.close()
        await pw.stop()

    # 그라운드트루스는 이 사이클의 런 id 로 고정해 읽는다(중첩 사이클의 latest 오독 방지).
    after = db_run_by_id(report["run_id"]) if report.get("run_id") else db_latest_run(workflow_id)
    report["run_after"] = after
    before_id = (report["run_before"] or {}).get("id")
    if after and after.get("id") and after.get("id") != before_id:
        report["run_recorded"] = True
        report["db_status"] = after.get("status")
    return report


# ─────────────────────────────────────────────────────────────────────────────
# phase2 — ERP 직접 접속: 조회 → 3중 가드 → 상세 대조 → F6 삭제 → 잔존 0
# ─────────────────────────────────────────────────────────────────────────────
def row_is_ours(row: dict, fg_code: str) -> bool:
    """삭제 3중 가드 — 결의자(WRT_EMP_NM)=로그인계정 + 결의구분(ABDOCU_FG_CD)=fg_code + 미결.

    ⚠ 완화 금지. 하나라도 어긋나면 삭제하지 않고 중단·보고한다(테스트 계정 외 전표 보호).
    """
    writer_ok = str(row.get("WRT_EMP_NM") or "").strip() == USERID
    fg_ok = str(row.get("ABDOCU_FG_CD") or "") == fg_code
    not_posted = not str(row.get("DOCU_NO") or "").strip()
    return writer_ok and fg_ok and not_posted


async def query_master(page: Page) -> int:
    """조회(F2) 클릭 후 마스터 rowcount 안정화까지 폴링. 반환 행수(-1=실패)."""
    box = await page.evaluate(BTN_BOX_JS, selectors.BTN_LOOKUP)
    if box:
        await page.mouse.click(box["x"], box["y"])
    else:
        await page.keyboard.press("F2")
    prev, stable, rc = -2, 0, -1
    for _ in range(25):
        await page.wait_for_timeout(800)
        rc = await page.evaluate(MASTER_ROWCOUNT_JS)
        if isinstance(rc, int) and rc >= 0 and rc == prev:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        prev = rc
    return rc if isinstance(rc, int) else -1


async def open_erp_doc_screen(page: Page, gubun_label: str) -> None:
    """ERP 직접 로그인 → GLDDOC00300 → 결의구분 드롭다운 설정(실패면 예외)."""
    base = get_settings().erp_base
    await ensure_logged_in(page, USERID, PASSWORD, base)
    await page.goto(f"{base}/FI/GLDDOC00300")
    try:
        await page.wait_for_load_state("networkidle", timeout=20_000)
    except Exception:  # noqa: BLE001 — 옴니솔은 폴링이 계속 돌아 networkidle 이 안 올 수 있다.
        pass
    for _ in range(20):
        if await page.evaluate("(s) => !!document.querySelector(s)", selectors.GUBUN_SELECT):
            break
        await page.wait_for_timeout(1_000)
    r = await page.evaluate(
        js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS,
        {"selector": selectors.GUBUN_SELECT, "text": gubun_label},
    )
    if not r.get("ok"):
        raise RuntimeError(f"결의구분 '{gubun_label}' 설정 실패 — {r}")
    print(f"[P2] 결의구분 = {gubun_label} (value={r.get('val')})", flush=True)
    await page.wait_for_timeout(1_500)


async def collect_detail(page: Page, master_index: int) -> dict:
    """마스터 ``master_index`` 행의 상세를 로드해 읽는다.

    조회(F2) 직후 ERP 는 **첫 행을 자동 선택**해 상세를 이미 렌더해 둔다(실측 2026-08-03) —
    우리 문서가 유일한 행(master_index==0)이면 그대로 읽는 것이 가장 짧고 안전하다.
    그 외(다중 행)에는 ⚠ ``setCurrent`` 가 상세 로딩을 트리거하지 않으므로(js_lib 주석) 검증된
    :class:`nbkit.grid.strategies.GridExtractor` 의 KEYBOARD_FALLBACK(첫 행 실클릭 + ArrowDown +
    정착 조건 폴링)에 맡긴다. 어느 경로든 금액 합계는 마스터 DETAIL_SUM_AMT 로 교차검증된다.
    """
    if master_index == 0:
        direct = GridProvider(page, 1)
        if await direct.get_row_count() > 0:
            return {"rows": await direct.get_all_rows(), "unverified": False, "via": "direct"}
    ex = GridExtractor(page, master_index=0, detail_index=1)
    res = await ex.extract(
        master_count=master_index + 1,
        detail_service_url=None,
        master_id_field=None,  # 조인 필드 미상 → rowcount 변화+안정 판정 경로.
        strategy=CollectionStrategy.KEYBOARD_FALLBACK,
        dwell_ms=2_500,
    )
    details = res.get("details") or []
    if master_index >= len(details):
        return {"rows": [], "unverified": True, "error": "상세 수집 결과가 비었습니다."}
    entry = details[master_index]
    return {"rows": entry.get("rows") or [], "unverified": bool(entry.get("unverified")),
            "via": "keyboard"}


async def delete_selected(page: Page) -> list:
    """F6(삭제) → 확인 모달 처리. 관측된 모달 스냅샷 목록을 반환한다."""
    seen: list = []
    dbox = await page.evaluate(BTN_BOX_JS, selectors.BTN_DELETE)
    if dbox:
        await page.mouse.click(dbox["x"], dbox["y"])
    else:
        await page.keyboard.press("F6")
    for _ in range(8):
        await page.wait_for_timeout(1_200)
        modals = await page.evaluate(cc_js.MODALS_SNAPSHOT_JS)
        if not modals:
            break
        seen.extend(modals)
        clicked = False
        for label in ("예", "확인", "삭제"):
            btn = await page.evaluate(cc_js.MODAL_BTN_BOX_JS, label)
            if btn:
                await page.mouse.click(btn["x"], btn["y"])
                clicked = True
                break
        if not clicked:
            break
    return seen


async def erp_verify_and_delete(
    *,
    gubun_label: str,
    fg_code: str,
    tag: str,
    pick_master: Callable[[list[dict]], int] | None = None,
    want_detail: bool = True,
) -> dict:
    """phase2 — ERP 직접 접속으로 저장 결과를 검증하고 F6 삭제 후 잔존 0 을 확인한다.

    반환: ``{before, all_ours, master, detail, deleted, after, abdocu_nos, error}``.
    ``pick_master`` 는 마스터 행 목록에서 **우리가 방금 만든 문서**의 인덱스를 고르는 함수
    (기본: 마지막 행). 상세 대조는 그 행을 대상으로 한다.
    """
    out: dict = {"before": None, "all_ours": None, "master": None, "detail": None,
                 "deleted": False, "after": None, "abdocu_nos": [], "error": None,
                 "screenshots": []}
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO)
    page = await browser.new_page(viewport=selectors.VIEWPORT)
    try:
        print("[P2] ERP 직접 로그인…", flush=True)
        await open_erp_doc_screen(page, gubun_label)
        await query_master(page)
        dump = await page.evaluate(MASTER_DUMP_JS, 0)
        before = dump.get("n", -1)
        out["before"] = before
        rows = dump.get("rows") or []
        out["abdocu_nos"] = [str(r.get("ABDOCU_NO") or "") for r in rows]
        before_path = str(ART / f"{tag}_p2_before.png")
        await page.screenshot(path=before_path)
        out["screenshots"].append(before_path)
        print(f"[P2] 조회 결과 {before}건 전표={out['abdocu_nos']}", flush=True)

        if before <= 0:
            out["error"] = "삭제 대상 0건 — 제품 경로 저장이 안 됐을 수 있음(팬텀 저장?)"
            return out

        all_ours = all(row_is_ours(r, fg_code) for r in rows)
        out["all_ours"] = all_ours
        if not all_ours:
            out["error"] = "가드레일 불일치 — 우리 전표가 아닌 행 존재. 삭제 중단."
            out["dump"] = dump
            await page.screenshot(path=str(ART / f"{tag}_p2_guardrail.png"))
            print(f"[P2][ABORT] {out['error']}", flush=True)
            return out

        idx = pick_master(rows) if pick_master else len(rows) - 1
        m = rows[idx]
        out["master"] = {
            "index": idx,
            "ABDOCU_NO": str(m.get("ABDOCU_NO") or ""),
            "ABDOCU_FG_CD": str(m.get("ABDOCU_FG_CD") or ""),
            "WRT_EMP_NM": str(m.get("WRT_EMP_NM") or ""),
            "ACTG_DT": str(m.get("ACTG_DT") or ""),
            "DETAIL_SUM_AMT": str(m.get("DETAIL_SUM_AMT") or ""),
            "DETAIL_SUM_AMT3": str(m.get("DETAIL_SUM_AMT3") or ""),
        }
        if want_detail:
            det = await collect_detail(page, idx)
            out["detail"] = {"n": len(det["rows"]), "unverified": det.get("unverified"),
                             "via": det.get("via"), "rows": detail_view(det["rows"]),
                             "error": det.get("error")}
            print(f"[P2] 상세 {out['detail']['n']}행 unverified={out['detail']['unverified']}", flush=True)

        # 삭제는 항상 조회 결과 **전체**(모두 가드 통과 확인됨)를 대상으로 한다.
        await page.evaluate(SELECT_MASTER_JS, 0)
        modals = await delete_selected(page)
        if modals:
            print(f"[P2] 삭제 모달: {json.dumps(modals[:3], ensure_ascii=False)}", flush=True)
        await page.wait_for_timeout(1_000)
        after = await query_master(page)
        out["after"] = after
        out["deleted"] = after == 0
        after_path = str(ART / f"{tag}_p2_after.png")
        await page.screenshot(path=after_path)
        out["screenshots"].append(after_path)
        if after != 0:
            out["error"] = f"삭제 후 잔존 {after}건 — 수동 정리 필요(전표번호 {out['abdocu_nos']})"
            print(f"[P2][FAILURE] {out['error']}", flush=True)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"phase2 예외: {exc!r}"
        print(f"[P2][ERROR] {out['error']}", flush=True)
        try:
            await page.screenshot(path=str(ART / f"{tag}_p2_exception.png"))
        except Exception:  # noqa: BLE001
            pass
    finally:
        await browser.close()
        await pw.stop()
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 사이클 러너 — 4종 스크립트가 공유하는 반복/중단/리포트 골격
# ─────────────────────────────────────────────────────────────────────────────
async def run_cycles(
    *,
    title: str,
    cycles: int,
    tag: str,
    run_one: Callable[[int], Awaitable[dict]],
    report_line: Callable[[int, dict], None],
) -> int:
    """N 사이클 반복 — 삭제 실패/잔존이 보이면 즉시 중단하고 리포트를 남긴다.

    **cycle 1 안전 게이트**: 첫 사이클이 PASS 가 아니면(저장 실패·금액 불일치·스트레이 빈 행 등)
    나머지 사이클을 돌리지 않는다 — 회귀 상태에서 전표만 계속 만들지 않게.

    반환: 프로세스 종료코드(0=전 사이클 PASS·잔존 0, 1=그 외).
    """
    print(f"[SMOKE] {title} — 제품 경로(대시보드 폼 → 실행) 작성 → ERP 삭제. cycles={cycles}", flush=True)
    print("[SMOKE] ⚠ 상신 금지 · F7 저장/F6 삭제만 · 삭제 3중 가드 완화 금지", flush=True)
    results: list[dict] = []
    aborted = False
    for i in range(1, cycles + 1):
        print(f"\n===== CYCLE {i}/{cycles} =====", flush=True)
        try:
            c = await run_one(i)
        except Exception as exc:  # noqa: BLE001
            c = {"cycle": i, "ok": False, "error": f"cycle exception: {exc!r}", "delete": {}}
        results.append(c)
        report_line(i, c)
        vd = c.get("delete") or {}
        if vd.get("error") or (vd.get("before") not in (None, 0) and not vd.get("deleted")):
            print(f"[CYCLE {i}][ABORT] 삭제 문제 → 사이클 중단. {vd.get('error')}", flush=True)
            aborted = True
            break
        if i == 1 and cycles > 1 and not c.get("ok"):
            print("[CYCLE 1][GATE] 첫 사이클 FAIL → 나머지 사이클 중단(회귀 상태에서 전표 양산 방지).",
                  flush=True)
            aborted = True
            break
    passed = sum(1 for c in results if c.get("ok"))
    print("\n" + "=" * 60, flush=True)
    print(f"{title} SUMMARY — {passed}/{len(results)} PASS · aborted={aborted}", flush=True)
    print("=" * 60, flush=True)
    leftover = [c for c in results if (c.get("delete") or {}).get("after") not in (0, None)]
    if leftover:
        print("⚠ 잔존 전표 있음:", flush=True)
        for c in leftover:
            d = c.get("delete") or {}
            print(f"  cycle {c.get('cycle')}: after={d.get('after')} 전표={d.get('abdocu_nos')}", flush=True)
    else:
        print("잔존 전표 0 확인(모든 사이클 삭제 완료).", flush=True)
    path = ART / f"{tag}.json"
    path.write_text(json.dumps({"cycles": results, "aborted": aborted}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    print(f"\n리포트: {path}", flush=True)
    return 0 if (passed == len(results) and not aborted and not leftover) else 1


def summarize_run(c: dict) -> str:
    """사이클 리포트 공통 1줄 — 제품 경로 증거(agent_runs)와 삭제 결과."""
    r = c.get("run") or {}
    d = c.get("delete") or {}
    return (
        f"run: terminal={r.get('terminal')} ui={r.get('ui_status')} db={r.get('db_status')} "
        f"agent_runs기록={r.get('run_recorded')} result={r.get('result_text')!r}\n"
        f"  delete: before={d.get('before')} all_ours={d.get('all_ours')} "
        f"deleted={d.get('deleted')} after={d.get('after')} 전표={d.get('abdocu_nos')}"
    )


__all__ = [
    "ART", "FRONTEND_BASE", "HEADLESS", "PASSWORD", "TODAY", "USERID",
    "BTN_BOX_JS", "MASTER_DUMP_JS", "MASTER_ROWCOUNT_JS", "SELECT_MASTER_JS",
    "add_row", "as_int", "collect_detail", "dashboard_login", "db_latest_run", "db_run_by_id",
    "detail_view", "erp_verify_and_delete", "open_agent", "pick_combo", "query_master",
    "row_is_ours", "row_scope", "run_cycles", "run_product", "set_date", "set_select",
    "set_switch", "submit_pre_run", "summarize_run", "wait_terminal", "wait_terminal_by_db",
]
