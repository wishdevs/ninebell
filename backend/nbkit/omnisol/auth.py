"""옴니솔 인증 — 로그인 + 사용자유형(인사/회계) 실클릭 전환.

두 검증된 노하우를 담는다:
1. **로그인**: ``#userid``/``#password`` fill → submit → 성공 판정은 URL 이 아니라
   **로그인 폼(#userid) 소멸**(flow 문서 §1).
2. **사용자유형 전환**: ⚠ 반드시 **실제 마우스 클릭**(드롭다운→옵션→변경적용)으로. JS
   ``.click()``/위젯 ``.value()`` 는 더존 변경적용 핸들러를 못 깨워 select 값만 바뀌고 실제
   컨텍스트(모듈 접근)는 안 바뀐다. 변경적용은 페이지를 reload 하며 해당 컨텍스트 모듈을 부여.

Page 는 느슨하게(``Any``) 받는다. 브라우저/컨텍스트 수명은 호출자(patterns/엔진)가 소유한다.
"""

from __future__ import annotations

import logging
from typing import Any

from nbkit.browser import waits
from nbkit.browser.actions import mouse_click, safe_evaluate
from nbkit.browser.detection import is_authenticated, selector_present
from nbkit.omnisol import js_lib, selectors
from nbkit.omnisol.errors import AuthError, UserTypeError

logger = logging.getLogger("nbkit.omnisol.auth")

LOGIN_TIMEOUT_MS = 25_000


async def omnisol_login(
    page: Any, userid: str, password: str, base: str, *, timeout_ms: int = LOGIN_TIMEOUT_MS
) -> None:
    """주어진 page 에 옴니솔 로그인을 수행. 실패 시 :class:`AuthError`.

    자격증명은 저장하지 않는다(호출자가 즉시 폐기하는 컨텍스트에서 실행). 성공 판정은
    로그인 폼(#userid) 소멸. 브라우저/컨텍스트 생성·종료는 호출자 책임.
    """
    if not (userid and password):
        raise AuthError("자격증명이 비어 있습니다.")
    # networkidle 전체 대기를 피한다(웜 세션에서 인증 SPA 전체 로드 ~15s 실측) —
    # domcontentloaded 후 '로그인 폼 출현' vs '인증 SPA(요소 수 임계)' 중 먼저 확정되는
    # 쪽으로 분기 폴링. 폼 부재(음성)가 아니라 요소 수(양성)로 워밍을 판정해, 폼이 아직
    # 안 그려진 초기 화면을 인증으로 오판하지 않는다. 만료 세션은 폼이 보여 정상 로그인.
    await page.goto(f"{base.rstrip('/')}/", wait_until="domcontentloaded", timeout=timeout_ms)
    for i in range(40):  # 상한 ~12s
        if await selector_present(page, selectors.LOGIN_USERID):
            break  # 로그인 폼 확인 → 콜드 경로.
        # 웜 판정은 **아바타**(로그인 후에만 렌더, 헤더라 이른 시점 출현)를 1순위 양성 신호로 —
        # 요소 수 임계(200)는 SPA 하이드레이션이 느리면 수 초 늦게 넘어 로그인 단계가 길어진다
        # (실측 2026-07-04: 이미 로그인된 메인 페이지에서 login 단계 ~18s).
        if await selector_present(page, selectors.AVATAR) or await is_authenticated(page):
            logger.info("옴니솔 세션 재사용(웜 진입, %d폴): userid=%s", i + 1, userid)
            return
        await page.wait_for_timeout(300)
    else:
        raise AuthError("로그인 페이지가 로드되지 않았습니다(폼/대시보드 모두 미출현).")
    await page.fill(selectors.LOGIN_USERID, userid)
    await page.fill(selectors.LOGIN_PASSWORD, password)
    await page.click(selectors.LOGIN_SUBMIT)
    # 제출 후 성공을 **양성 신호(아바타 출현)** 폴링으로 판정 — 기존 wait_networkidle(20s)
    # 은 메인 SPA 의 롱폴링/지속 요청 때문에 상한을 통째로 태우는 경우가 잦았다(실측:
    # login 단계 ~17s). 상한(~20s)은 유지하되 아바타가 뜨는 즉시 진행한다.
    for i in range(66):
        await page.wait_for_timeout(300)
        if await selector_present(page, selectors.AVATAR):
            logger.info("옴니솔 로그인 성공(%d폴): userid=%s", i + 1, userid)
            return
    # 아바타 미출현(셀렉터 변경 등) — 최종 폴백은 기존과 동일한 폼 소멸 판정.
    if not await is_authenticated(page, login_selector=selectors.LOGIN_USERID):
        raise AuthError("아이디 또는 비밀번호가 올바르지 않습니다.")
    logger.info("옴니솔 로그인 성공(폼 소멸 폴백): userid=%s", userid)


async def read_current_user_type(page: Any) -> str:
    """현재 사용자유형 텍스트(예 '인사사용자(예외)'). 선택기 없으면 '?'."""
    val = await safe_evaluate(page, js_lib.USER_TYPE_READ_JS, default="?")
    return val or "?"


async def open_user_panel(page: Any) -> None:
    """우상단 아바타를 실제 클릭해 사용자유형 패널을 연다(실패 시 JS 폴백)."""
    try:
        await page.click(selectors.AVATAR, timeout=4_000)
    except Exception:  # noqa: BLE001 — 실클릭 실패 시 JS 폴백
        await page.evaluate(js_lib.AVATAR_CLICK_JS)
    await page.wait_for_timeout(1_500)


async def _switch_user_type_real(page: Any, target: str) -> bool:
    """드롭다운 열기 → target 옵션 클릭 → 변경적용. 전부 실제 마우스 클릭(좌표)."""
    db = await safe_evaluate(page, js_lib.UT_DROPDOWN_BOX_JS, default=None)
    if not db:
        return False
    await mouse_click(page, db["x"], db["y"])  # 드롭다운 열기
    await page.wait_for_timeout(1_000)
    ob = await safe_evaluate(page, js_lib.UT_OPTION_BOX_JS, target, default=None)
    if not ob:
        return False
    await mouse_click(page, ob["x"], ob["y"])  # target 옵션 선택(실제 Kendo change)
    await page.wait_for_timeout(1_000)
    disp = await safe_evaluate(page, js_lib.UT_DISPLAY_JS, default="")
    if target not in (disp or ""):  # 선택이 표시에 반영됐는지 1차 확인
        return False
    ab = await safe_evaluate(page, js_lib.UT_APPLY_BOX_JS, default=None)
    if not ab:
        return False
    await mouse_click(page, ab["x"], ab["y"])  # 변경적용 → reload + 컨텍스트 적용
    return True


async def switch_user_type(page: Any, target: str, *, attempts: int = 2) -> None:
    """사용자유형을 ``target``('인사'|'회계')으로 보장. 실패 시 :class:`UserTypeError`.

    이미 target 이면 전환하지 않는다. 전환은 실클릭(드롭다운→옵션→변경적용)으로만 하며,
    변경적용 후 reload+컨텍스트 적용을 기다린 뒤 **패널을 다시 열어 재확인**한다(더블체크).
    """
    await open_user_panel(page)
    cur = await read_current_user_type(page)
    if cur == "?":
        raise UserTypeError("사용자 유형 선택기를 찾을 수 없습니다.")
    if target in cur:  # 이미 맞으면 전환 불필요
        logger.info("사용자유형 %s 확인됨(전환 불필요).", cur)
        return

    for attempt in range(1, attempts + 1):
        if attempt > 1:
            logger.info("사용자유형 전환 재시도 (%s/%s)…", attempt, attempts)
            await open_user_panel(page)
        if not await _switch_user_type_real(page, target):
            continue
        # 변경적용 후 reload + 컨텍스트 적용 대기.
        await page.wait_for_timeout(2_500)
        await waits.wait_networkidle(page, timeout_ms=12_000)
        await page.wait_for_timeout(1_500)
        # 재확인: 패널 다시 열어 실제로 바뀌었는지.
        await open_user_panel(page)
        cur2 = await read_current_user_type(page)
        if target in (cur2 or ""):
            logger.info("사용자유형 전환 완료 → %s사용자", target)
            return

    raise UserTypeError(
        f"{target}사용자로 전환하지 못했습니다(현재 유형 미반영). 잠시 후 다시 시도하세요."
    )
