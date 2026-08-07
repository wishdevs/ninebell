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

import logging
import time
from typing import Any

from app.agents.common import doc_steps
from app.config import get_settings
from nbkit.browser.actions import js_click
from nbkit.browser.popups import close_foreign_pages
from nbkit.omnisol import js_lib, latency, selectors, verify
from nbkit.omnisol.menu_schemas import EXPENSE_CARD, MenuSchema
from nbkit.patterns import emit_log, emit_shot, emit_step
from nbkit.patterns.login_flow import ensure_logged_in
from nbkit.patterns.menu_navigate_flow import navigate_schema
from nbkit.patterns.user_type_flow import ensure_user_type

logger = logging.getLogger(__name__)


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


async def _warn_if_unverified(emit, step: str, r: dict) -> None:
    """스텝이 '확인 불가'로 돌려준 경고를 런 로그에 노출한다(성공을 단정하지 않기 위해).

    스텝 반환 컨벤션: {"ok": bool, "reason"?: 하드 실패 사유, "warn"?: 확인 불가 사유}.
    ok=True + warn 은 "진행은 했지만 반영을 확인하지 못했다" — 로그에 남겨야 사후에
    '완료로 보이는데 값이 안 붙은' 사고를 되짚을 수 있다(§10 실패 정책).
    """
    if r.get("warn"):
        await emit_log(emit, f"{step} {r['warn']}", "warn")


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
            # 예외를 error 프레임으로 삼키면 runner 의 logger.exception 에 도달하지 않아 서버
            # 로그에 트레이스백이 남지 않는다 — 여기서 스택을 남긴다(사용자 메시지는 불변).
            logger.exception("login 노드 실패")
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
            # 로그인 이후에 뜬 외부 창(회사 홈페이지 시스템 팝업) just-in-time 정리 —
            # 로그인 구간 감시(PopupWatcher)를 지나 도착하는 사례 방어. 아바타 클릭이 그 창에
            # 포커스를 뺏긴 채 진행되지 않게 **패널 조작 전에** 치운다.
            # ⚠ 결재 순회 단계에서는 호출 금지(결제창=EAP 도 다른 호스트 창).
            await close_foreign_pages(state["page"], get_settings().erp_base)
            await ensure_user_type(state["page"], target_type, emit=emit)
        except Exception as exc:  # noqa: BLE001
            # 서버 로그용 트레이스백(login 노드와 같은 규율) — 사용자 메시지는 불변.
            logger.exception("user_type 노드 실패(target=%s)", target_type)
            return {"error": f"사용자유형 전환 실패: {exc}"}
        return {}

    return user_type


def make_menu_nav_node(schema: MenuSchema = EXPENSE_CARD):
    """지정 MenuSchema(기본 결의서입력 EXPENSE_CARD) 메뉴로 딥링크 진입(nbkit navigate_schema).

    schema 를 파라미터화해 결의서입력 외 화면(전표조회승인 VOUCHER_RECEIVABLE 등)도
    같은 노드로 진입한다 — 기존 무인자 호출부는 EXPENSE_CARD 기본값으로 그대로 동작한다.
    """

    async def menu_nav(state: dict) -> dict:
        if state.get("error"):
            return {}
        emit = state["events"].put
        base = get_settings().erp_base
        page = state["page"]
        try:
            active = await navigate_schema(page, schema, base, emit=emit)
            # 크래시 복구(menu_navigate_flow)로 page 가 교체됐을 수 있다 — 이후 정리·후속
            # 노드는 실제 사용 중인 페이지 기준(테스트 스텁이 None 을 돌려주면 기존 유지).
            if active is not None:
                page = active
            # 메뉴 진입 뒤에도 공지/홈페이지 창이 뜰 수 있다(실측 2026-07-27: 로그인 완료
            # +252ms 에 더존 공지창 uc.ninebell.co.kr 이 별도 창으로 출현 — 로그인 감시 구간이
            # 끝난 뒤라 아무도 닫지 않았다). 화면을 덮은 채 다음 조작이 진행되지 않게 정리한다.
            # ⚠ 결재 순회 전 단계에서만 호출한다(결제창=EAP 도 다른 호스트의 창이다).
            closed = await close_foreign_pages(page, base)
            for url in closed:
                await emit_log(emit, f"메뉴 진입 후 뜬 외부 창을 닫았습니다 — {url}", "info")
            # ERP 지연 감지 안내(관측성) — 그리드 출현 되먹임(navigate_menu) 직후가 배율이
            # 갱신된 첫 지점이라, 사용자에게 상한 확대 사실을 1줄로 알린다(성공 경로 불변).
            f = latency.factor()
            if f > 1.5:
                await emit_log(
                    emit, f"ERP 응답 지연 감지 — 대기 상한을 ×{f:.1f}로 확대해 진행합니다.", "warn"
                )
        except Exception as exc:  # noqa: BLE001
            # 예외를 error 프레임으로 삼키면 runner 의 logger.exception 에 도달하지 않아 서버
            # 로그에 트레이스백이 전혀 없었다(라이브 실증 2026-07-31: 렌더러 크래시 원인
            # 재구성 불가). 사용자 노출 메시지는 불변, 서버 로그에만 스택을 남긴다.
            logger.exception("menu_nav 노드 실패(%s)", schema.label)
            return {"error": f"메뉴 진입 실패: {exc}"}
        if page is not state["page"]:
            # 교체된 새 page 를 state 로 전파 — BaseAgentState 에 page 가 선언돼 있어 LangGraph
            # silent-drop 없이 후속 노드(각자 state["page"] 를 재조회)로 전달된다.
            return {"page": page}
        return {}

    return menu_nav


def make_set_gubun_node(gubun_text: str):
    """결의구분 Kendo dropdownlist(selectors.GUBUN_SELECT)를 gubun_text('카드')로 설정·**확인**.

    ⚠ KENDO_SET_DROPDOWN_BY_TEXT_JS 의 {ok:true} 는 "옵션을 찾아 위젯에 값을 넣고 change 를
    쐈다"까지다. 결의구분은 change 핸들러가 화면(입력 폼·그리드 컬럼)을 통째로 재구성하는
    연쇄 필드라, 그 재구성 과정에서 값이 되돌아가면 **다른 문서 종류의 화면에** 행을 추가하고
    증빙·금액을 채우는 조용한 실패가 된다(저장 직전까지 아무도 모른다).
    결의구분은 이 문서가 무엇인지를 정의하는 값이므로 불일치는 **하드 실패**로 끊는다(§10).
    """

    async def set_gubun(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        emit = events.put
        page = state["page"]
        await emit_step(emit, "set_gubun", "running")
        t0 = time.monotonic()
        # select 로드 폴링(상한 15s) — ⚠ 시간축 규율(2026-08-07): 종전 budget_polls×
        # wait_for_timeout 명목 폴은 간격이 delay_scale 로 축소돼 실관찰창이 붕괴한다.
        # 폴 대기는 실시간(verify.DEFAULT_SLEEP), 상한만 latency 배율(≤×4) 확대.
        waited = 0
        load_cap_ms = latency.budget_ms(15_000)
        while not await page.evaluate("(s) => !!document.querySelector(s)", selectors.GUBUN_SELECT):
            if waited >= load_cap_ms:
                break
            await verify.DEFAULT_SLEEP(0.3)
            waited += 300
        r = await page.evaluate(
            js_lib.KENDO_SET_DROPDOWN_BY_TEXT_JS,
            {"selector": selectors.GUBUN_SELECT, "text": gubun_text},
        )
        if not r.get("ok"):
            await emit_step(emit, "set_gubun", "failed")
            return {"error": f"결의구분을 '{gubun_text}'로 설정하지 못했습니다."}
        # 화면 재구성(연쇄) 정착 대기 — 여기는 **확인으로 대체할 리더가 없는 자리**라 기존
        # 고정 대기를 유지한다. 확인은 정착 **후에** 읽어야 '되돌려진 값'을 잡는다(정착 전
        # 스냅샷은 세팅 직후라 언제나 통과해 확인이 무의미해진다).
        await page.wait_for_timeout(1_500)
        res = await verify.confirm_select(
            page,
            selectors.GUBUN_SELECT,
            gubun_text,
            # ⚠ reapply(재세팅) 는 일부러 주지 않는다 — 재세팅 직후의 read 는 change 핸들러가
            # 값을 되돌리기 **전** 스냅샷일 수 있어, 잡으려던 되돌림을 오히려 통과시킨다.
            # 정착 대기는 이미 위에서 했으므로 재시도는 '다시 읽기'만으로 충분하다.
            # 리더가 select 자체를 못 읽으면(위젯 구조 차이) '값이 다름'이 아니라 확인 불가 —
            # 오탐이 멀쩡한 플로우를 끊지 않게 warn 후 진행(D7 규율).
            unknown_when=lambda v: not (isinstance(v, dict) and v.get("ok")),
        )
        if res.mismatch:
            await emit_step(emit, "set_gubun", "failed")
            return {"error": f"결의구분 '{gubun_text}' 반영 확인 실패 — {res.reason}"}
        if not res:  # 여기까지 왔으면 unknown(확인 불가) — 진행하되 미확인임을 반드시 남긴다.
            await emit_log(emit, f"결의구분 {res.reason}", "warn")
        # 확인이 안 된 경우 로그도 '완료'로 단정하지 않는다(로그만 보고 반영됐다고 믿지 않게).
        suffix = "" if res else " (반영 미확인)"
        await emit_log(emit, f"결의구분 = {gubun_text}{suffix}", "info")
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
        # 디테일 그리드 rowCount 0→1 폴링(상한 ~10s 유지) — ⚠ 시간축 규율(2026-08-07):
        # 종전 range(33)×wait_for_timeout(300) 명목 폴은 delay_scale 로 관찰창이 붕괴하고
        # latency 배율도 없어 느린 ERP 에서 상한 확대조차 못 받았다. 실시간 누산 + 배율 확대.
        waited = 0
        row_cap_ms = latency.budget_ms(10_000)
        while waited < row_cap_ms:
            await verify.DEFAULT_SLEEP(0.3)
            waited += 300
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
        # 브라우저 상호작용(showEditor+돋보기 3회 재시도)은 doc_steps 순수 스텝으로 위임한다
        # (출장 fill_rows 가 행별로 같은 스텝을 재사용) — 노드는 진행 이벤트만 방출한다.
        r = await doc_steps.open_evdn_editor(page)
        if not r.get("ok"):
            await emit_step(emit, "open_evdn", "failed")
            return {"error": r.get("reason") or "증빙유형 팝업이 열리지 않았습니다."}
        # 대상 행 로깅 — 2패스 사고(기존 행 증빙 오픈) 재발 진단용. shown 은 {ok, idx, rows}.
        shown = r.get("shown")
        target = (
            f"(대상 {shown['idx'] + 1}행/총 {shown['rows']}행)"
            if isinstance(shown, dict) and "idx" in shown
            else ""
        )
        # 스테일 팝업 의심(이미 열려 있던 팝업)은 성공을 막지 않되 반드시 로그로 드러낸다.
        await _warn_if_unverified(emit, "증빙유형 팝업", r)
        await emit_log(emit, f"증빙 돋보기 → 증빙유형 팝업 오픈{target}.", "ok")
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
        # 선택·적용·셀 반영 판정은 doc_steps 순수 스텝으로 위임(출장 fill_rows 재사용).
        r = await doc_steps.select_evdn_code(page, code)
        if not r.get("ok"):
            await emit_step(emit, "select_evdn", "failed")
            return {"error": r.get("reason") or f"증빙유형 코드 {code} 적용 실패"}
        # 셀 반영은 확인됐지만 팝업 닫힘을 확인 못 한 경우 — 다음 행이 스테일 팝업을 잡는
        # 사고의 **원인 지점**이라 여기서 경고를 남긴다(결과만 보고 원인을 되짚지 않게).
        await _warn_if_unverified(emit, "증빙유형 적용 후", r)
        await emit_log(
            emit,
            f"증빙유형 '{r.get('name')}'(코드 {r.get('code')}) 자동선택·적용 완료 — "
            "카드 상세 입력 단계로 진행. 저장(F7)은 하지 않음.",
            "ok",
        )
        await emit_shot(emit, page)
        await emit_step(emit, "select_evdn", "done", _ms(t0))
        return {}

    return select_evdn
