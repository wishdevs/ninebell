"""법인카드 결의서입력 화면 접근 노드 — chat_form 앞단(login→…→select_evdn).

nbkit 프리미티브(patterns.ensure_logged_in/ensure_user_type/navigate_schema)와 옴니솔
write-flow JS 단일소스(nbkit.omnisol.js_lib §B)만으로 조립한다. 셀렉터/JS 를 재하드코딩하지
않는다(리스킨 시 nbkit 한 곳만 고치면 됨).

각 노드는 진행 이벤트를 state["events"](asyncio.Queue)로 방출한다(emit = events.put →
nbkit.patterns.emit_* 콜백과 동일 인터페이스). 실패는 {"error": ...} 로 state 에 남겨
이후 노드가 건너뛰고 러너가 error 프레임으로 종료한다.

⚠ BTN_SAVE(실전표 저장·F7) 절대 클릭 금지 — 이 파이프라인은 증빙유형 선택까지만 하고
   chat_form 이 필드 채움(적용까지)만 한다.
"""

from __future__ import annotations

import time
from typing import Any

from app.config import get_settings
from nbkit.browser.actions import js_click, mouse_click
from nbkit.omnisol import js_lib, selectors
from nbkit.omnisol.menu_schemas import EXPENSE_CARD
from nbkit.patterns import emit_log, emit_shot, emit_step
from nbkit.patterns.login_flow import ensure_logged_in
from nbkit.patterns.menu_navigate_flow import navigate_schema
from nbkit.patterns.user_type_flow import ensure_user_type


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def make_login_node():
    """러너가 주입한 page 에 옴니솔 로그인(nbkit ensure_logged_in). 실패 시 error."""

    async def login(state: dict) -> dict:
        if state.get("error"):
            return {}
        emit = state["events"].put
        page = state["page"]
        base = get_settings().erp_base
        try:
            await ensure_logged_in(page, state["userid"], state["password"], base, emit=emit)
        except Exception as exc:  # noqa: BLE001 — 도메인 오류를 error 프레임으로 승격
            return {"error": f"로그인 실패: {exc}"}
        return {}

    return login


def make_user_type_node(target_type: str):
    """사용자유형을 target_type('회계')으로 실클릭 전환(nbkit ensure_user_type)."""

    async def user_type(state: dict) -> dict:
        if state.get("error"):
            return {}
        emit = state["events"].put
        try:
            await ensure_user_type(state["page"], target_type, emit=emit)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"사용자유형 전환 실패: {exc}"}
        return {}

    return user_type


def make_menu_nav_node():
    """결의서입력(EXPENSE_CARD) 메뉴로 딥링크 진입(nbkit navigate_schema)."""

    async def menu_nav(state: dict) -> dict:
        if state.get("error"):
            return {}
        emit = state["events"].put
        base = get_settings().erp_base
        try:
            await navigate_schema(state["page"], EXPENSE_CARD, base, emit=emit)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"메뉴 진입 실패: {exc}"}
        return {}

    return menu_nav


def make_set_gubun_node(gubun_text: str):
    """결의구분 Kendo dropdownlist(selectors.GUBUN_SELECT)를 gubun_text('카드')로 설정."""

    async def set_gubun(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        emit = events.put
        page = state["page"]
        await emit_step(emit, "set_gubun", "running")
        t0 = time.monotonic()
        for _ in range(15):  # select 로드 폴링
            if await page.evaluate("(s) => !!document.querySelector(s)", selectors.GUBUN_SELECT):
                break
            await page.wait_for_timeout(1_000)
        r = await page.evaluate(
            js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS,
            {"selector": selectors.GUBUN_SELECT, "text": gubun_text},
        )
        if not r.get("ok"):
            await emit_step(emit, "set_gubun", "failed")
            return {"error": f"결의구분을 '{gubun_text}'로 설정하지 못했습니다."}
        await page.wait_for_timeout(1_500)
        await emit_log(emit, f"결의구분 = {gubun_text}", "info")
        await emit_shot(emit, page)
        await emit_step(emit, "set_gubun", "done", _ms(t0))
        return {}

    return set_gubun


def make_add_row_node():
    """추가(F3) — 결의서 입력 행 생성(selectors.BTN_ADD). ⚠ BTN_SAVE 아님."""

    async def add_row(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        emit = events.put
        page = state["page"]
        await emit_step(emit, "add_row", "running")
        t0 = time.monotonic()
        await js_click(page, selectors.BTN_ADD)
        rows: Any = -1
        for _ in range(10):  # 디테일 그리드 rowCount 0→1 폴링
            await page.wait_for_timeout(1_000)
            rows = await page.evaluate(js_lib.DETAIL_ROWCOUNT_JS)
            if isinstance(rows, int) and rows > 0:
                break
        if not (isinstance(rows, int) and rows > 0):
            await emit_step(emit, "add_row", "failed")
            return {"error": "추가(F3) 후 입력 행이 생성되지 않았습니다."}
        await emit_log(emit, "추가(F3) — 입력 행 생성됨.", "ok")
        await emit_shot(emit, page)
        await emit_step(emit, "add_row", "done", _ms(t0))
        return {}

    return add_row


def make_open_evdn_node():
    """디테일 그리드 증빙 셀 → showEditor → 돋보기 실클릭 → 증빙유형 팝업 오픈.

    RealGrid(캔버스)라 셀은 DOM 이 아님 → js_lib.OPEN_EVDN_EDITOR_JS 로 DOM 에디터 오버레이를
    띄운 뒤, 검증된 돋보기 좌표(EVDN_EDITOR_MAGNIFIER_RECT_JS)를 픽셀 클릭한다.
    """

    async def open_evdn(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        emit = events.put
        page = state["page"]
        await emit_step(emit, "open_evdn", "running")
        t0 = time.monotonic()
        opened = False
        for attempt in range(1, 4):  # 캔버스 돋보기 클릭은 빗나갈 수 있어 재시도
            if attempt > 1:
                await emit_log(emit, f"증빙 돋보기 재시도 ({attempt}/3)…", "warn")
            shown = await page.evaluate(js_lib.OPEN_EVDN_EDITOR_JS)
            if not shown:
                continue
            await page.wait_for_timeout(700)  # 에디터가 증빙 셀로 렌더·정착할 시간
            rect = await page.evaluate(js_lib.EVDN_EDITOR_MAGNIFIER_RECT_JS)
            if not rect:
                continue
            await mouse_click(page, rect["x"], rect["y"])  # 돋보기(캔버스) 클릭
            for _ in range(6):
                await page.wait_for_timeout(1_000)
                opened = await page.evaluate(js_lib.EVDN_POPUP_OPEN_JS)
                if opened:
                    break
            if opened:
                break
        if not opened:
            await emit_step(emit, "open_evdn", "failed")
            return {"error": "증빙유형 팝업이 열리지 않았습니다(돋보기 클릭 3회 실패). 잠시 후 다시 실행해 주세요."}
        await emit_log(emit, "증빙 돋보기 → 증빙유형 팝업 오픈.", "ok")
        await emit_shot(emit, page)
        await emit_step(emit, "open_evdn", "done", _ms(t0))
        return {}

    return open_evdn


def make_select_evdn_node(code: str = "01"):
    """증빙유형을 code(기본 '01' = 법인카드)로 자동선택·'적용'(HITL 없음). 저장(F7) 안 함.

    선택(EVDN_SELECT_BY_CODE_JS) → 적용 버튼 실클릭(EVDN_APPLY_BOX_JS) → 디테일 증빙 셀
    반영(DETAIL_EVDN_CELL_JS)으로 적용 판정.
    """

    async def select_evdn(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        emit = events.put
        page = state["page"]
        await emit_step(emit, "select_evdn", "running")
        t0 = time.monotonic()
        r = await page.evaluate(js_lib.EVDN_SELECT_BY_CODE_JS, code)
        if not r.get("ok"):
            await emit_step(emit, "select_evdn", "failed")
            return {"error": f"증빙유형 코드 {code} 자동선택 실패: {r.get('reason')}"}
        await page.wait_for_timeout(500)
        sel_name = r.get("name") or ""
        box = await page.evaluate(js_lib.EVDN_APPLY_BOX_JS)
        if box:
            await mouse_click(page, box["x"], box["y"])
        applied = False
        for _ in range(8):
            await page.wait_for_timeout(1_000)
            cell = await page.evaluate(js_lib.DETAIL_EVDN_CELL_JS)
            if sel_name and sel_name in cell:
                applied = True
                break
        if not applied:
            await emit_step(emit, "select_evdn", "failed")
            return {"error": "증빙유형 자동 적용(적용 버튼)에 실패했습니다."}
        await emit_log(
            emit,
            f"증빙유형 '{sel_name}'(코드 {r.get('code')}) 자동선택·적용 완료 — "
            "카드 상세 입력 단계로 진행. 저장(F7)은 하지 않음.",
            "ok",
        )
        await emit_shot(emit, page)
        await emit_step(emit, "select_evdn", "done", _ms(t0))
        return {}

    return select_evdn
