"""시스템 e2e — tax-invoice **제품 경로** 실전 검증(대시보드 UI → POST 실행 → 라이브 러너 → 저장).

스모크(`tax_invoice_smoke_cycle.py`)는 `build_tax_invoice_graph()` 를 스크립트가 직접
`ainvoke` 한다 — `runs.py` params 수집·러너 큐·SSE 스크린캐스트·`agent_runs` 기록을 타지 않는다.
이 스크립트는 그 제품 경로 자체가 동작하는지 확인한다.

시나리오 = **증빙유형 코드**(SCENARIO 환경변수). 10종 전부를 같은 하네스로 돈다:

  발행 전(폼 전량 입력 → 무개입 완주 → F7 저장)
    22 과세 · 23 비과세 · 24 불공

  발행 후(폼은 질문+조회기간만 → 라이브 중 계산서 그리드 개입 → F7 저장)
    03 세금계산서 · 04 계산서 · 05 불공·사업무관 · 06 불공·차량 · 07 불공·면세사업

  발행 후·분할(계산서 1행 라디오 + 분할 계획 2행을 개입 화면에서)
    11 과세 · 13 비과세

⚠ 2026-08-20 사용자 재확정(PROCESS.md D1)으로 **발행 후 폼에는 예산단위·프로젝트·적요가
없다** — 리스트 선택이 복수일 수 있어 실행 전에 못 정하기 때문이다. 그 값들은 라이브 개입
(`InvoiceGridCard`, kind="invoice-grid")에서 행별로 받는다. 종전 하네스는 발행 후에도 폼
콤보박스를 채우려다 `button[title="검색하여 선택"]` 타임아웃으로 죽었다(2026-08-25 실측).

SKIP_CLEANUP=1 이면 phase2(ERP 정리)를 생략한다 — 여러 코드를 연달아 돌릴 때 마지막에 한 번만
정리하기 위함. 저장이 일어나는 시나리오에서 함부로 쓰지 말 것(잔존 전표가 다음 판정을 오염시킨다).

⚠ 안전 수칙
  - 저장된 전표는 phase2 `erp_verify_and_delete`(3중 가드+F6+잔존0)로 반드시 정리한다 —
    이 스크립트는 F7 을 직접 누르지 않는다(제품 그래프가 누른다).
  - 상신 절대 금지 — 이 경로엔 상신 버튼 자체가 없다(저장까지만).

env: E2E_FRONTEND/E2E_USERID/E2E_PASSWORD/E2E_HEADLESS/E2E_RUN_TIMEOUT_S (product_cycle 공유)
     SCENARIO=22(기본)|03|04|05|06|07|11|13|23|24 · SKIP_CLEANUP=1 이면 phase2 생략.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Locator, Page, async_playwright  # noqa: E402

from e2e.product_cycle import (  # noqa: E402
    ART,
    FRONTEND_BASE,
    HEADLESS,
    PASSWORD,
    RESULT_WAIT_TIMEOUT_S,
    SLOW_MO,
    USERID,
    db_latest_run,
    db_run_by_id,
    erp_verify_and_delete,
    open_agent,
    set_date,
    submit_pre_run,
)

# 종전 시나리오 이름 → 코드(호출부 하위호환).
_ALIAS = {"PRE22": "22", "POST03": "03", "POST04": "04", "SPLIT11": "11"}
_raw = os.environ.get("SCENARIO", "22").strip().upper()
CODE = _ALIAS.get(_raw, _raw)

# 증빙유형 10종 — 포털 카드 라벨(model.ts QUICK_PICK_GROUPS)과 경로 축.
# label 은 포털 카드의 접근가능 이름 "{code} {label}" 을 만드는 데 쓴다.
SPECS: dict[str, dict] = {
    "03": {"label": "세금계산서", "issue": "post", "split": False, "tax": "taxable"},
    "04": {"label": "계산서", "issue": "post", "split": False, "tax": "exempt"},
    "05": {"label": "불공·사업무관", "issue": "post", "split": False, "tax": "nondeduct"},
    "06": {"label": "불공·차량", "issue": "post", "split": False, "tax": "nondeduct"},
    "07": {"label": "불공·면세사업", "issue": "post", "split": False, "tax": "nondeduct"},
    "11": {"label": "과세", "issue": "post", "split": True, "tax": "taxable"},
    "13": {"label": "비과세", "issue": "post", "split": True, "tax": "exempt"},
    "22": {"label": "과세", "issue": "pre", "split": False, "tax": "taxable"},
    "23": {"label": "비과세", "issue": "pre", "split": False, "tax": "exempt"},
    "24": {"label": "불공", "issue": "pre", "split": False, "tax": "nondeduct"},
}
if CODE not in SPECS:
    raise SystemExit(f"SCENARIO 는 {sorted(SPECS)} 중 하나여야 합니다 — 받은 값 {_raw!r}")
SPEC = SPECS[CODE]
IS_PRE = SPEC["issue"] == "pre"
IS_SPLIT = SPEC["split"]

SKIP_CLEANUP = os.environ.get("SKIP_CLEANUP", "0").strip() == "1"
TAG = f"tax_invoice_system_e2e_{CODE}"
AGENT_ID = "tax-invoice"
WORKFLOW_ID = "tax-invoice"
GUBUN_LABEL = "세금계산서"
FG_CODE = "51"

# 대시보드 UI 표준 데스크톱 뷰포트. ⚠ InvoiceGridCard 는 md(768px) 기준으로 표/카드 중 한쪽만
# 마운트한다 — 768 미만이면 행 편집 컨트롤 셀렉터가 통째로 달라진다.
VIEWPORT = {"width": 1440, "height": 900}

TODAY = date.today().isoformat()
NOTE = f"시스템e2e검증{CODE}"

# 예산단위·프로젝트 — **폼과 개입 화면의 선택지 출처가 다르다**.
#   실행 전 폼(CatalogCombobox) : ERP 전사 카탈로그 검색 → 아무 예산단위나 고를 수 있다.
#   개입 그리드(InvoiceBudgetCombobox) : 즐겨찾기 + '내 부서' 매칭분만(invoice_pick.load_catalogs
#     가 all 그룹을 안 보낸다 — "전사 전체는 과다"라는 card_collect 사용자 확정 관례).
# 그래서 개입용은 계정(이트라이브2, 부서 '인사/기획팀')의 실제 즐겨찾기에서 골라야 한다.
BUDGET_QUERY, BUDGET_MATCH = "임원실", "임원실"  # 발행 전 폼용(ERP 검색)
HITL_BUDGET_QUERY, HITL_BUDGET_MATCH = "인사기획팀", "인사기획팀"  # 개입 그리드용(즐겨찾기)
PROJECT_QUERY, PROJECT_MATCH = "800", "판매관리비"

# 발행 전 전용 입력(isBefore 에서만 렌더되는 필드).
PARTNER_NAME = "코웨이(주)"
SUPPLY_AMOUNT = "41000"

# 분할(11/13) 계획 — 2행. 마지막 행은 금액 입력칸 자체가 없다(차액반영 계약).
# 1행 금액은 고정하지 않고 **선택한 계산서 공급가액의 절반**으로 잡는다 — 고정값을 쓰면 공급가액이
# 그보다 작은 계산서가 1행일 때 차액이 음수가 되어 ERP 가 거부한다(목록은 매달 바뀐다).
SPLIT_ROWS = [
    {"note": "분할1", "cost_center": "임원실"},
    {"note": "분할2", "cost_center": "임원실"},
]
SPLIT_FALLBACK_AMOUNT = 10_000  # 공급가액을 못 읽었을 때만 쓰는 보수적 기본값.

# 라이브 실행 관찰 — 종료 대기 중 이 간격으로 스크린샷을 남긴다.
PROGRESS_SHOT_INTERVAL_S = 20

# ⚠ 셀렉터는 CSS 속성 완전일치로 쓴다 — get_by_role(name=…) 은 **부분일치**라
# "1행 처리 대상 선택" 이 11·21·31행까지 잡아 strict mode 위반으로 죽는다(2026-08-25 실측).
PICK_ROW1 = 'input[aria-label="1행 처리 대상 선택"]'
COMBO_TRIGGER = 'button[title="검색하여 선택"]'  # CatalogCombobox 트리거(프로젝트 등)


async def _row1_supply_amount(page: Page) -> int | None:
    """계산서 1행의 공급가액 — 분할 1행 금액을 실제 금액에 맞추는 데 쓴다.

    ⚠ 열 위치로 집지 않는다. 분할 모드는 선택·번호·계산서일·거래처명 열이 더 붙어 공급가액이
    5번째 칸이고, 비분할은 첫 칸이다(2026-08-25 실측). 대신 **천단위 콤마 숫자**로 보이는 첫
    칸을 고른다 — 번호('1')·날짜는 이 형태가 아니라 걸리지 않는다.
    """
    money = re.compile(r"^\d{1,3}(?:,\d{3})+$")
    try:
        cells = await page.locator('[data-row-no="1"] td').all_inner_texts()
    except Exception:  # noqa: BLE001 — 못 읽으면 폴백 금액으로 진행한다(판정을 막지 않는다).
        return None
    for text in cells:
        t = text.strip()
        if money.match(t):
            return int(t.replace(",", ""))
    return None


def _split_row(page: Page, n: int) -> Locator:
    """분할 계획 n행 컨테이너 — 적요·비용센터를 **둘 다** 품는 div 중 문서순 마지막(=최내곽).

    계산서 그리드 행과 `{n}행 적요` aria-label 이 겹치고, 프로젝트 콤보 트리거는 계산서 33행에도
    하나씩 있어 인덱스로는 못 집는다. 행 컨테이너로 스코프하는 것이 유일하게 안정적이다.
    """
    return (
        page.locator("div")
        .filter(has=page.locator(f'input[aria-label="{n}행 비용센터"]'))
        .filter(has=page.locator(f'input[aria-label="{n}행 적요"]'))
        .last
    )


async def _complete_signup(page: Page) -> None:
    """가입 리다이렉트 방어 처리 — 이름/부서는 읽기전용(옴니솔 프로필 자동), 약관만 체크 후 제출."""
    checkbox = page.locator('input[type="checkbox"]')
    await checkbox.wait_for(state="visible", timeout=10_000)
    await checkbox.check()
    await page.get_by_role("button", name="가입 완료").click()


async def _login(page: Page) -> dict:
    """대시보드 로그인 — 첫 접속 가입 리다이렉트를 감지해 화면 그대로 완료(방어 경로)."""
    out: dict = {"signup_triggered": False, "signup_screenshot": None}
    await page.goto(FRONTEND_BASE)
    await page.wait_for_timeout(1_000)
    await page.fill("#userid", USERID)
    await page.fill("#password", PASSWORD)
    await page.get_by_role("button", name="로그인").click()
    for _ in range(40):
        if "/login" not in page.url:
            break
        await page.wait_for_timeout(500)
    if "/signup" in page.url:
        out["signup_triggered"] = True
        shot = str(ART / f"{TAG}_signup.png")
        await page.screenshot(path=shot, full_page=True)
        out["signup_screenshot"] = shot
        print(f"[E2E] 가입 리다이렉트 감지 — {shot}, 안내대로 완료 진행", flush=True)
        await _complete_signup(page)
        for _ in range(40):
            if "/login" not in page.url and "/signup" not in page.url:
                break
            await page.wait_for_timeout(500)
    if "/login" in page.url or "/signup" in page.url:
        raise RuntimeError(f"로그인 미완료 — url={page.url}")
    return out


async def _enable_debug_mode(page: Page) -> None:
    """DEBUG_ONLY 에이전트(tax-invoice) 노출 — localStorage 플래그 후 리로드."""
    await page.evaluate("() => localStorage.setItem('nb_debug_mode', '1')")
    await page.reload()
    await page.wait_for_timeout(1_000)


# ══════════════════════════════════════════════════════════════════════════════
# 콤보박스 조작 — 두 종류를 구분해 다룬다
#   CatalogCombobox      : Radix Popover(포털) — 프로젝트, 그리고 발행 전 폼의 예산단위
#   InvoiceBudgetCombobox: 인라인 패널([data-budget-trigger]) — 개입 그리드의 예산단위
# ══════════════════════════════════════════════════════════════════════════════
async def _click_el(target: Locator) -> None:
    """가려져도 확실히 클릭 — 일반 클릭 실패 시 요소에 직접 click 을 디스패치한다.

    분할(11/13) 개입 그리드는 컬럼이 많아(선택·번호·계산서일·거래처명이 더 붙는다) 표가 가로
    스크롤되고, 스크롤 컨테이너가 셀 위로 겹쳐 Playwright 의 hit-test 가 "intercepts pointer
    events" 로 30초를 소진한다. 콤보 **트리거**뿐 아니라 인라인 패널의 **옵션 버튼**도 같은
    컨테이너 안에 렌더돼 똑같이 막힌다(2026-08-25 증빙 11 실측 — 트리거만 고쳤다가 옵션에서
    재발). 요소 자체는 visible·enabled 이므로 직접 디스패치로 뚫는다.
    """
    await target.wait_for(state="visible", timeout=10_000)
    try:
        await target.scroll_into_view_if_needed(timeout=4_000)
    except Exception:  # noqa: BLE001 — 스크롤 실패는 클릭 폴백이 흡수한다.
        pass
    try:
        await target.click(timeout=4_000)
    except Exception:  # noqa: BLE001 — 가려진 경우만 폴백(원인은 위 독스트링).
        await target.evaluate("el => el.click()")


async def _pick_catalog_combo(page: Page, trigger: Locator, query: str, match: str) -> None:
    """CatalogCombobox 실조작 — **Radix Popover(포털) 대응**.

    ⚠ product_cycle.py 의 공유 `pick_combo()` 는 트리거의 형제 div 로 팝업을 찾는다(옛 자체
    absolute 팝업 가정). CatalogCombobox 는 Radix Popover(document.body 하위)로 옮겨 가 형제
    탐색이 실패한다. 다른 문서종류가 공유하는 product_cycle.py 는 건드리지 않고 여기서만 고친다.
    """
    await _click_el(trigger)

    box = page.get_by_placeholder("자주쓰는 필터 / ERP 검색어")
    await box.wait_for(state="visible", timeout=5_000)
    pop = page.locator("[data-radix-popper-content-wrapper]").filter(has=box)
    await box.fill(query)
    await page.wait_for_timeout(400)

    option = pop.get_by_role("button").filter(has_text=match)
    if await option.count() == 0:
        search_btn = pop.get_by_role("button", name="검색")
        if await search_btn.count() > 0:
            await _click_el(search_btn)
        for _ in range(30):
            await page.wait_for_timeout(500)
            if await option.count() > 0:
                break
    if await option.count() == 0:
        raise RuntimeError(f"콤보박스에서 '{match}' 옵션을 찾지 못했습니다(query={query!r}).")
    await _click_el(option.first)
    await page.wait_for_timeout(300)


async def _pick_budget_inline(page: Page, trigger: Locator, query: str, match: str) -> None:
    """InvoiceBudgetCombobox — 인라인 ComboPanel(포털 아님). 검색 입력 후 role=option 클릭."""
    await _click_el(trigger)
    box = page.get_by_placeholder("이름·사업계획·예산계정 검색")
    await box.wait_for(state="visible", timeout=5_000)
    await box.fill(query)
    await page.wait_for_timeout(400)
    option = page.get_by_role("option").filter(has_text=match)
    if await option.count() == 0:
        raise RuntimeError(f"예산단위 목록에서 '{match}' 를 찾지 못했습니다(query={query!r}).")
    await _click_el(option.first)
    await page.wait_for_timeout(300)


# ══════════════════════════════════════════════════════════════════════════════
# 실행 전 폼
# ══════════════════════════════════════════════════════════════════════════════
async def _fill_form(page: Page) -> dict:
    """포털에서 증빙유형 코드를 고르고, 발행 전이면 전용 필드까지 채운다.

    ⚠ 폼 초기 렌더는 포털이 아니라 **질문 화면**이다(defaultAnswers 가 issue='after' 를 넣어
    entryMode 가 'form' 으로 시작 — questions-section.tsx:92-94). 포털 카드로 가려면 항상
    "증빙유형 코드로 바로 선택" 을 먼저 눌러야 한다.
    """
    observations: dict = {"code": CODE, "issue": SPEC["issue"], "split": IS_SPLIT}

    portal_btn = page.get_by_role("button", name="증빙유형 코드로 바로 선택")
    if await portal_btn.count() > 0 and await portal_btn.first.is_visible():
        await portal_btn.first.click()
        await page.wait_for_timeout(300)

    card = page.get_by_role("button", name=f"{CODE} {SPEC['label']}", exact=True)
    await card.first.wait_for(state="visible", timeout=15_000)
    await card.first.click()
    await page.wait_for_timeout(400)

    # 증빙유형 요약 배지가 고른 코드로 바뀌었는지 — 카드 클릭이 삼켜지면 여기서 잡힌다.
    # ⚠ exact=True 필수 — 폼 설명문("…증빙유형이 정해집니다")이 부분일치로 먼저 잡힌다.
    label = page.get_by_text("증빙유형", exact=True)
    if await label.count() > 0:
        badge = label.first.locator("xpath=..")
        observations["evidence_badge"] = " ".join((await badge.inner_text()).split())[:60]
    else:
        observations["evidence_badge"] = None

    if IS_PRE:
        await page.fill("#tax-invoice-partner", PARTNER_NAME)
        await page.get_by_label("공급가액").fill(SUPPLY_AMOUNT)
        # 발행 전 폼의 예산단위(0)·프로젝트(1) — 이 화면의 CatalogCombobox 는 이 둘뿐이다.
        triggers = page.locator('button[title="검색하여 선택"]')
        await _pick_catalog_combo(page, triggers.nth(0), BUDGET_QUERY, BUDGET_MATCH)
        await _pick_catalog_combo(page, triggers.nth(1), PROJECT_QUERY, PROJECT_MATCH)
        await page.fill("#tax-invoice-note", NOTE)
        await set_date(page, "회계일", TODAY)
    else:
        # 발행 후는 기간(이번 달)이 카드 클릭으로 이미 채워져 있다 — 추가 조작 불필요.
        # 폼에 예산단위·프로젝트·적요가 **없는 것이 정상**임을 증거로 남긴다(D1 재확정).
        observations["post_form_has_combobox"] = (
            await page.locator('button[title="검색하여 선택"]').count() > 0
        )
        observations["post_form_has_note"] = await page.locator("#tax-invoice-note").count() > 0

    if SPEC["tax"] == "exempt":
        reason = page.locator("#tax-invoice-exempt-reason")
        visible = await reason.count() > 0 and await reason.is_visible()
        observations["exempt_reason_field_visible"] = visible
        if visible:
            observations["exempt_reason_value"] = (await reason.input_value()).strip()

    return observations


# ══════════════════════════════════════════════════════════════════════════════
# 라이브 개입 — InvoiceGridCard(kind="invoice-grid")
# ══════════════════════════════════════════════════════════════════════════════
async def _drive_invoice_grid(page: Page, out: dict) -> None:
    """계산서 1행 선택 + 행별 예산단위·프로젝트·적요(+ 분할이면 분할 계획) → '입력 완료'.

    분할(11/13)은 선택 컨트롤이 라디오라 1행만 고를 수 있다 — ERP 분할처리 팝업이 한 전표의
    금액을 쪼개는 구조이기 때문이다.
    """
    picker = page.locator(PICK_ROW1)
    out["appeared"] = True
    out["control_role"] = "radio" if IS_SPLIT else "checkbox"
    out["rows_count"] = await page.locator("[data-row-no]").count()

    shot = str(ART / f"{TAG}_hitl_before.png")
    await page.screenshot(path=shot, full_page=True)
    out["screenshot_before"] = shot
    print(
        f"[E2E] 개입 감지 — 계산서 {out['rows_count']}행, 컨트롤={out['control_role']}, {shot}",
        flush=True,
    )

    await picker.check()
    await page.wait_for_timeout(300)

    row = page.locator('[data-row-no="1"]')
    await _pick_budget_inline(
        page, row.locator("[data-budget-trigger]"), HITL_BUDGET_QUERY, HITL_BUDGET_MATCH
    )
    await _pick_catalog_combo(
        page, row.locator(COMBO_TRIGGER), PROJECT_QUERY, PROJECT_MATCH
    )
    await row.locator('input[aria-label="1행 적요"]').fill(NOTE)
    await page.wait_for_timeout(300)

    if IS_SPLIT:
        # 분할 계획 섹션은 **행 선택 뒤에야** 마운트된다(splitVisible — 선택 1행 기준금액 필요).
        first_cc = page.locator('input[aria-label="1행 비용센터"]')
        await first_cc.wait_for(state="visible", timeout=10_000)
        out["split_section_visible"] = True
        supply = await _row1_supply_amount(page)
        out["row1_supply"] = supply
        first_amount = max(1, supply // 2) if supply else SPLIT_FALLBACK_AMOUNT
        out["split_first_amount"] = first_amount
        last = len(SPLIT_ROWS) - 1
        for i, r in enumerate(SPLIT_ROWS):
            n = i + 1
            srow = _split_row(page, n)
            # 적요는 계산서 행(1행 적요)과 aria-label 이 겹친다 — 분할 행 컨테이너로 스코프한다.
            await srow.locator(f'input[aria-label="{n}행 적요"]').fill(r["note"])
            await srow.locator(f'input[aria-label="{n}행 비용센터"]').fill(r["cost_center"])
            if i != last:  # 마지막 행은 금액칸이 없다(차액반영).
                await srow.locator(f'input[aria-label="{n}행 공급가액"]').fill(str(first_amount))
            await _pick_catalog_combo(page, srow.locator(COMBO_TRIGGER), PROJECT_QUERY, PROJECT_MATCH)
        await page.wait_for_timeout(300)

    shot2 = str(ART / f"{TAG}_hitl_filled.png")
    await page.screenshot(path=shot2, full_page=True)
    out["screenshot_filled"] = shot2

    submit = page.get_by_role("button", name="입력 완료")
    out["submit_enabled"] = await submit.first.is_enabled()
    if not out["submit_enabled"]:
        # 실패 표면화 — 왜 못 누르는지(미입력 행 안내)를 그대로 싣는다.
        out["submit_blocked_text"] = None
        warn = page.get_by_text("미입력", exact=False)
        if await warn.count() > 0:
            out["submit_blocked_text"] = (await warn.first.inner_text()).strip()[:200]
        print(f"[E2E][WARN] '입력 완료' 비활성 — {out.get('submit_blocked_text')}", flush=True)
        return
    await submit.first.click()
    out["submitted"] = True
    print("[E2E] 개입 '입력 완료' 제출", flush=True)
    await page.wait_for_timeout(800)


async def _wait_terminal_with_progress_shots(page: Page, run_id: str, timeout_s: int) -> dict:
    """DB 종결 대기 + 주기적 스크린샷 + 발행 후 계산서 그리드 개입 자동 처리."""
    out: dict = {
        "terminal": False, "db_status": None, "ui_status": None,
        "result_text": None, "fail_reason": None, "progress_shots": [],
        "hitl": {"appeared": False, "submitted": False},
    }
    import asyncio

    elapsed = 0
    next_shot_at = 0
    shot_n = 0
    hitl_handled = False
    # 개입 도착 신호 = 계산서 행 선택 컨트롤(InvoiceGridCard 고유).
    picker = page.locator(PICK_ROW1)

    while elapsed < timeout_s:
        row = db_run_by_id(run_id)
        st = (row or {}).get("status")

        if not hitl_handled and await picker.count() > 0:
            hitl_handled = True
            try:
                await _drive_invoice_grid(page, out["hitl"])
            except Exception as exc:  # noqa: BLE001 — 개입 조작 실패도 리포트로 남긴다.
                out["hitl"]["error"] = f"{exc!r}"[:400]
                shot = str(ART / f"{TAG}_hitl_error.png")
                await page.screenshot(path=shot, full_page=True)
                out["hitl"]["screenshot_error"] = shot
                print(f"[E2E][ERROR] 개입 조작 실패: {exc!r}", flush=True)

        if elapsed >= next_shot_at:
            shot_n += 1
            path = str(ART / f"{TAG}_progress{shot_n}.png")
            try:
                await page.screenshot(path=path, full_page=True)
                out["progress_shots"].append(path)
                print(f"[E2E] 진행 스크린샷 {path} (elapsed={elapsed}s status={st})", flush=True)
            except Exception as exc:  # noqa: BLE001 — 관찰 실패가 판정을 막으면 안 된다.
                print(f"[E2E] 진행 스크린샷 실패: {exc!r}", flush=True)
            next_shot_at = elapsed + PROGRESS_SHOT_INTERVAL_S
        if st in ("succeeded", "failed", "cancelled"):
            out["terminal"] = True
            out["db_status"] = st
            break
        await asyncio.sleep(3)
        elapsed += 3
    if not out["terminal"]:
        return out
    await page.wait_for_timeout(1_500)
    try:
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
                out["result_text"] = (await loc.inner_text()).strip()[:600]
                break
    except Exception:  # noqa: BLE001 — UI 텍스트 수집 실패는 판정에 영향 없음(판정은 DB).
        pass
    return out


async def main() -> None:
    report: dict = {
        "code": CODE, "label": SPEC["label"], "issue": SPEC["issue"], "split": IS_SPLIT,
        "login": None, "debug_mode": False, "form_filled": False,
        "form_observations": None, "submitted": False, "run_id": None, "term": None,
        "console_errors": [], "final_screenshot": None, "p1_error": None, "cleanup": None,
    }

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO)
    ctx = await browser.new_context(viewport=VIEWPORT)
    page = await ctx.new_page()

    console_errors: list[dict] = []
    page.on(
        "console",
        lambda msg: console_errors.append({"type": msg.type, "text": msg.text})
        if msg.type in ("error", "warning")
        else None,
    )
    page.on("pageerror", lambda exc: console_errors.append({"type": "pageerror", "text": str(exc)}))

    try:
        print(f"[E2E] 증빙 {CODE}({SPEC['label']}) — 대시보드 로그인({FRONTEND_BASE}, 계정={USERID})…", flush=True)
        report["login"] = await _login(page)
        print(f"[E2E] 로그인 완료 url={page.url}", flush=True)

        await _enable_debug_mode(page)
        report["debug_mode"] = True

        run_before = db_latest_run(WORKFLOW_ID)

        print(f"[E2E] /agents/{AGENT_ID} 진입 — 실행 전 입력 폼 대기", flush=True)
        await open_agent(page, AGENT_ID)
        pre_shot = str(ART / f"{TAG}_p1_prerun.png")
        await page.screenshot(path=pre_shot, full_page=True)

        report["form_observations"] = await _fill_form(page)
        report["form_filled"] = True
        form_shot = str(ART / f"{TAG}_p1_form_filled.png")
        await page.screenshot(path=form_shot, full_page=True)
        print(f"[E2E] 폼 입력 완료 {json.dumps(report['form_observations'], ensure_ascii=False)}", flush=True)

        await submit_pre_run(page)
        report["submitted"] = True
        print("[E2E] 실행 클릭", flush=True)

        before_id = (run_before or {}).get("id")
        run_id = None
        for _ in range(20):
            latest = db_latest_run(WORKFLOW_ID)
            if latest and latest.get("id") and latest.get("id") != before_id:
                run_id = latest["id"]
                break
            await page.wait_for_timeout(1_000)
        report["run_id"] = run_id
        if run_id is None:
            report["p1_error"] = "실행 클릭 후 20s 안에 새 agent_runs 행이 나타나지 않음."
        else:
            print(f"[E2E] agent_runs 확인 run={run_id[:8]} — 종료까지 최대 {RESULT_WAIT_TIMEOUT_S}s 대기", flush=True)
            term = await _wait_terminal_with_progress_shots(page, run_id, RESULT_WAIT_TIMEOUT_S)
            report["term"] = term
            final_shot = str(ART / f"{TAG}_p1_final.png")
            await page.screenshot(path=final_shot, full_page=True)
            report["final_screenshot"] = final_shot
            print(f"[E2E] 최종 term={json.dumps(term, ensure_ascii=False)[:500]}", flush=True)
    except Exception as exc:  # noqa: BLE001 — 실패도 리포트로 남긴다.
        report["p1_error"] = f"{report.get('p1_error') or ''} / 예외: {exc!r}".strip(" /")
        try:
            await page.screenshot(path=str(ART / f"{TAG}_p1_exception.png"), full_page=True)
        except Exception:  # noqa: BLE001
            pass
        print(f"[E2E][ERROR] phase1 예외: {exc!r}", flush=True)
    finally:
        report["console_errors"] = console_errors
        await ctx.close()
        await browser.close()
        await pw.stop()

    print(f"[E2E] 콘솔 에러/경고 {len(console_errors)}건: {json.dumps(console_errors[:20], ensure_ascii=False)}", flush=True)

    if SKIP_CLEANUP:
        print("[E2E] SKIP_CLEANUP=1 — phase2 정리 생략(배치 종료 후 별도 실행)", flush=True)
    else:
        print("[E2E] phase2 — ERP 독립 재조회 + 정리(F6) 시작", flush=True)
        cleanup = await erp_verify_and_delete(gubun_label=GUBUN_LABEL, fg_code=FG_CODE, tag=TAG)
        report["cleanup"] = cleanup
        print(f"[E2E] phase2 결과: {json.dumps(cleanup, ensure_ascii=False, default=str)[:1200]}", flush=True)

    out_path = ART / f"{TAG}_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[E2E] 리포트 저장 {out_path}", flush=True)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
