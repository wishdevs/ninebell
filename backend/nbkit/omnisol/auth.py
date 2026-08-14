"""옴니솔 인증 — 로그인 + 사용자유형 실클릭 전환(유형 추가에 견디는 옵션-목록 기반 해석).

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
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from nbkit.browser.actions import mouse_click, safe_evaluate
from nbkit.browser.detection import is_authenticated, selector_present
from nbkit.omnisol import js_lib, latency, selectors, verify
from nbkit.omnisol.errors import AuthError, LoginPageError, UserTypeError
from nbkit.omnisol.modals import dismiss_notice_popup

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
    # 상한 ~12s — ERP 지연 시 폴 간격은 불변, 회수 상한만 배율(≤×4)로 확대(latency).
    for i in range(latency.budget_polls(40)):
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
        # 페이지는 로드됐지만 폼/아바타 모두 미출현 = 옴니솔 점검·SPA 지연(인프라성).
        # 자격증명 실패와 구분되는 LoginPageError(AuthError 서브클래스)로 던진다.
        raise LoginPageError("로그인 페이지가 로드되지 않았습니다(폼/대시보드 모두 미출현).")
    await page.fill(selectors.LOGIN_USERID, userid)
    await page.fill(selectors.LOGIN_PASSWORD, password)
    await page.click(selectors.LOGIN_SUBMIT)
    # 제출 후 성공을 **양성 신호(아바타 출현)** 폴링으로 판정 — 기존 wait_networkidle(20s)
    # 은 메인 SPA 의 롱폴링/지속 요청 때문에 상한을 통째로 태우는 경우가 잦았다(실측:
    # login 단계 ~17s). 상한(~20s)은 유지하되 아바타가 뜨는 즉시 진행한다.
    for i in range(latency.budget_polls(66)):  # 회수 상한만 배율 확대(간격 불변).
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


async def read_user_type_options(page: Any) -> list[str]:
    """ERP 가 실제로 제공하는 사용자유형 옵션 라벨 전량(읽기 실패 시 빈 리스트).

    별칭 해석·진단 로그의 **단일 소스**다. 하드코딩 목록을 두지 않기 때문에 유형이 추가돼도
    이 리더가 그대로 새 라벨을 실어 나른다(코드 수정 불필요).
    """
    data = await safe_evaluate(page, js_lib.USER_TYPE_OPTIONS_JS, default=None)
    if not isinstance(data, dict):
        return []
    return [str(o) for o in (data.get("options") or []) if str(o).strip()]


def _norm(text: str) -> str:
    """라벨 정규화 — 공백 전부 제거(‘SCM - 구매’/‘SCM-구매’ 같은 표기 흔들림 흡수)."""
    return re.sub(r"\s+", "", text or "")


@dataclass(frozen=True)
class _Resolved:
    """별칭 해석 결과. ``exact`` = 실제 옵션 목록에서 해석됐는가."""

    label: str  # 클릭·비교에 쓸 **실제 옵션 라벨 원문**
    options: tuple[str, ...]  # 해석 근거(로그/에러 메시지 노출용)
    exact: bool  # True=동등 비교, False=옵션 미확보 폴백이라 부분문자열 비교


def resolve_user_type_label(options: Sequence[str], target: str) -> str:
    """별칭 ``target``('회계'·'SCM' 등)을 실제 옵션 라벨 하나로 해석한다.

    정규화(공백 제거) 후 ① 완전일치 ② 접두일치 ③ 포함일치 순으로 좁힌다. 각 단계에서
    후보가 **정확히 1개**여야 확정하고, 2개 이상이면 임의 선택하지 않고 모호성 오류로
    실패한다(저장소 규율: 애매하면 조용히 고르지 말고 명확히 실패).
    해석 실패·모호 모두 **실제 옵션 목록을 메시지에 노출**한다 — 새 유형이 추가되면 로그만
    보고 알 수 있어야 하기 때문(관측성 요구).
    """
    want = _norm(target)
    if not want:
        raise UserTypeError(f"사용자유형 target 이 비어 있습니다. 실제 옵션: {list(options)}")
    pairs = [(o, _norm(o)) for o in options]
    for rule, hits in (
        ("완전일치", [o for o, n in pairs if n == want]),
        ("접두일치", [o for o, n in pairs if n.startswith(want)]),
        ("포함일치", [o for o, n in pairs if want in n]),
    ):
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise UserTypeError(
                f"사용자유형 '{target}' 이(가) 모호합니다({rule} 후보 {hits}). "
                f"실제 옵션: {list(options)} — 후보를 하나로 좁히는 라벨을 쓰세요."
            )
    raise UserTypeError(
        f"사용자유형 '{target}' 에 해당하는 옵션이 없습니다. 실제 옵션: {list(options)}"
    )


async def _resolve_target(page: Any, target: str) -> _Resolved:
    """옵션 목록을 읽어 ``target`` 을 실제 라벨로 해석(+ 관측 로그 1회).

    옵션 목록을 못 읽으면(리더 실패·스킨 변경) target 을 라벨로 간주하는 **레거시 폴백**으로
    퇴화한다 — 리더 하나가 깨졌다고 전환 자체를 못 하게 만들지 않는다. 이 경우에만 비교가
    부분문자열이 된다(``exact=False``).
    """
    options = await read_user_type_options(page)
    if not options:
        logger.warning("사용자유형 옵션 목록을 읽지 못했습니다 — target=%r 을 라벨로 간주(폴백).", target)
        return _Resolved(label=target, options=(), exact=False)
    label = resolve_user_type_label(options, target)
    # 관측성: 유형이 추가/변경되면 이 한 줄만 보고 즉시 드러나게 한다.
    logger.info("사용자유형 옵션 %s / target=%r → 해석 라벨=%r", options, target, label)
    return _Resolved(label=label, options=tuple(options), exact=True)


def _label_matches(observed: str, resolved: _Resolved) -> bool:
    """관측 텍스트(현재 유형/드롭다운 표시)가 해석된 라벨과 같은가.

    옵션에서 해석된 라벨은 **동등 비교** — 미래에 '회계'와 '회계-정산' 같은 접두 관계 라벨이
    공존해도 오판하지 않는다. 옵션 미확보 폴백일 때만 종전 부분문자열 판정을 유지한다.
    """
    obs, want = _norm(observed), _norm(resolved.label)
    if not want:
        return False
    return obs == want if resolved.exact else want in obs


async def is_user_panel_open(page: Any) -> bool:
    """사용자 패널이 이미 열려 있는가(판별 불가 시 False = '모른다')."""
    return bool(await safe_evaluate(page, js_lib.USER_PANEL_OPEN_JS, default=False))


async def open_user_panel(page: Any) -> None:
    """우상단 아바타를 실제 클릭해 사용자유형 패널을 연다(실패 시 JS 폴백).

    ⚠ 아바타 클릭은 **토글**이다 — 이미 열린 패널을 또 누르면 닫힌다. 실측(2026-08-01):
    ``ensure_logged_in`` → ``read_profile`` 이 패널을 연 채로 남기는데, 그 직후
    ``switch_user_type`` 첫 줄의 이 함수가 패널을 닫아 attempt 1 을 통째로 날렸다(H0).
    → 열려 있으면 클릭하지 않는다(idempotent). 판별 불가면 종전대로 클릭한다.
    """
    if await is_user_panel_open(page):
        return
    try:
        await page.click(selectors.AVATAR, timeout=4_000)
    except Exception:  # noqa: BLE001 — 실클릭 실패 시 JS 폴백
        await page.evaluate(js_lib.AVATAR_CLICK_JS)
    # 고정 1.5s 대신 유형 선택기가 읽히는(패널 렌더 완료) 즉시 진행 — 폴링(상한 1.5s 기준,
    # ERP 지연 시 배율 ≤×4 로만 확대 — latency.budget_ms).
    # ⚠ 시간축 규율(2026-08-07): 관찰창 폴 대기는 실시간 sleep — page.wait_for_timeout 은
    #   delay_scale(voucher 0.4/card 0.15)로 축소돼 명목 카운터 상한이 실효 40%/15%로 붕괴한다.
    waited = 0
    cap_ms = latency.budget_ms(1_500)
    while waited < cap_ms:
        await verify.DEFAULT_SLEEP(0.15)
        waited += 150
        if await safe_evaluate(page, js_lib.USER_TYPE_READ_JS, default="?") not in ("", "?"):
            return


async def _switch_user_type_real(page: Any, target: str, *, exact: bool = False) -> bool:
    """드롭다운 열기 → ``target`` **라벨 원문** 옵션 클릭 → 변경적용. 전부 좌표 실클릭.

    ``target`` 은 :func:`resolve_user_type_label` 로 해석된 실제 옵션 라벨이어야 한다
    (별칭을 그대로 넘기면 옵션 li 매칭이 '포함' 단계로 내려가 약해진다). ``exact`` 는
    표시 반영 판정 방식 — 해석된 라벨이면 True(동등), 폴백이면 False(부분문자열).
    """
    resolved = _Resolved(label=target, options=(), exact=exact)
    db = await safe_evaluate(page, js_lib.UT_DROPDOWN_BOX_JS, default=None)
    if not db:
        return False
    await mouse_click(page, db["x"], db["y"])  # 드롭다운 열기
    # 무엇을 기다리나: 드롭다운 **옵션 리스트 렌더 완료**(종전 고정 1s). target 옵션(li)이
    # 보이고 좌표가 2회 연속 동일해야 진행 — Kendo 열림 애니메이션 중의 움직이는 li 를
    # 클릭하면 옆 항목을 짚는다(좌표 안정 = 애니메이션 정착 신호). 상한 실시간(monotonic,
    # delay_scale 무관) × latency 배율(ERP 지연 시 ≤×4 확대).
    ob = None
    prev_y: Any = None
    t0 = time.monotonic()
    cap_ms = latency.budget_ms(1_500)
    while (time.monotonic() - t0) * 1_000 < cap_ms:
        cand = await safe_evaluate(page, js_lib.UT_OPTION_BOX_JS, target, default=None)
        if cand and prev_y == cand.get("y"):
            ob = cand
            break
        prev_y = cand.get("y") if cand else None
        await page.wait_for_timeout(150)
    if not ob:
        return False
    await mouse_click(page, ob["x"], ob["y"])  # target 옵션 선택(실제 Kendo change)
    # 무엇을 기다리나: 선택이 드롭다운 **표시(UT_DISPLAY_JS)에 반영**되는 것(종전 고정 1s 후
    # 1회 확인). 반영 즉시 진행, 상한 내 미반영이면 False — 기존 attempts=2 재시도가 처리.
    t0 = time.monotonic()
    cap_ms = latency.budget_ms(1_500)
    while True:
        disp = await safe_evaluate(page, js_lib.UT_DISPLAY_JS, default="")
        if _label_matches(disp or "", resolved):
            break
        if (time.monotonic() - t0) * 1_000 >= cap_ms:
            return False
        await page.wait_for_timeout(150)
    ab = await safe_evaluate(page, js_lib.UT_APPLY_BOX_JS, default=None)
    if not ab:
        return False
    # reload 감지 마커 — 변경적용은 페이지를 reload 하므로 새 document 에서는 이 마커가
    # 사라진다(_wait_reload_after_apply 의 1단계 신호). best-effort(실패해도 진행 —
    # 마커가 안 심겼으면 1단계는 즉시 통과하고 2단계(아바타)가 대기를 담당한다).
    await safe_evaluate(page, "() => { window.__nbUtApplyMark = true; return true; }", default=None)
    await mouse_click(page, ab["x"], ab["y"])  # 변경적용 → reload + 컨텍스트 적용
    return True


# 변경적용 reload 관찰 상한(ms) — 종전 networkidle 상한(12s)을 승계(latency 배율로만 확대).
_APPLY_RELOAD_CAP_MS = 12_000


async def _wait_reload_after_apply(page: Any) -> None:
    """변경적용 클릭 후 **reload 완료**를 조건 폴링으로 기다린다.

    종전 고정 2.5s + wait_networkidle(12s) + 고정 1.5s 를 대체한다 — 옴니솔은 networkidle
    을 거의 못 잡아(SPA 롱폴링·keepalive) 상한 12s 를 통째로 태우는 패턴으로 이미 문서화돼
    있고(OMNISOL_NOTES §6), 로그인(omnisol_login)이 같은 이유로 networkidle 을 폐기하고
    아바타 양성 신호로 바꾼 선례를 따른다. 2단계 조건:
      ① 이전 document 소멸 — 변경적용 직전에 심은 마커(window.__nbUtApplyMark) 소멸.
         (navigation 중 evaluate 실패는 safe_evaluate 가 default False 로 흡수 → 소멸 판정.)
      ② 새 화면 렌더 — 아바타(selectors.AVATAR) 재출현(로그인 웜 판정과 동일한 양성 신호).
    상한 내 미충족이어도 예외 없이 반환한다 — 전환 성공의 최종 판정은 호출자
    (switch_user_type)의 패널 재오픈 + USER_TYPE_READ_JS 재독 일치(더블체크, attempts=2)가
    담당한다. 상한은 실시간(monotonic, delay_scale 무관) × latency 배율(≤×4).
    """
    cap_ms = latency.budget_ms(_APPLY_RELOAD_CAP_MS)
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1_000 < cap_ms:
        marked = await safe_evaluate(page, "() => window.__nbUtApplyMark === true", default=False)
        if not marked:
            break  # 마커 소멸 = reload 시작(또는 이미 새 document).
        await page.wait_for_timeout(250)
    while (time.monotonic() - t0) * 1_000 < cap_ms:
        if await selector_present(page, selectors.AVATAR):
            return
        await page.wait_for_timeout(250)


async def switch_user_type(page: Any, target: str, *, attempts: int = 2) -> None:
    """사용자유형을 ``target``(별칭 '인사'·'회계'·'SCM' …)으로 보장. 실패 시 :class:`UserTypeError`.

    ``target`` 은 **별칭**이어도 된다 — ERP 가 실제로 제공하는 옵션 목록과 대조해 유일한
    라벨로 해석한다(:func:`resolve_user_type_label`). 유형이 추가돼도 이 함수는 그대로다.
    이미 해당 유형이면 전환하지 않는다. 전환은 실클릭(드롭다운→옵션→변경적용)으로만 하며,
    변경적용 후 reload+컨텍스트 적용을 기다린 뒤 **패널을 다시 열어 재확인**한다(더블체크).
    """
    await open_user_panel(page)
    cur = await read_current_user_type(page)
    if cur == "?":
        raise UserTypeError("사용자 유형 선택기를 찾을 수 없습니다.")
    resolved = await _resolve_target(page, target)  # 모호/미존재면 여기서 옵션 목록과 함께 실패.
    if _label_matches(cur, resolved):  # 이미 맞으면 전환 불필요
        logger.info("사용자유형 %s 확인됨(전환 불필요).", cur)
        return

    for attempt in range(1, attempts + 1):
        # 공지팝업 재출현 방어(사용자 실측 2026-07-23: 회계/인사 선택 화면에서 또 뜸) —
        # 서버 정책상 하루동안 보지 않기·닫기(로그인 직후)에도 화면 전환/리로드 후 재출현한다.
        # 공지는 화면 로드 ~1.5s 뒤 비동기 렌더라 JIT(0ms)로는 못 잡고, 직전 화면 로드에서
        # 늦게 뜬 공지를 패널 조작(드롭다운→옵션→변경적용) 직전 관찰창 2s 로 흡수한다.
        # 웜 경로(이미 target)는 위에서 조기 반환하므로 이 대기는 전환 실행 경로에만 생긴다.
        await dismiss_notice_popup(page, appear_cap_ms=2_000)
        if attempt > 1:
            logger.info("사용자유형 전환 재시도 (%s/%s)…", attempt, attempts)
            await open_user_panel(page)
        if not await _switch_user_type_real(page, resolved.label, exact=resolved.exact):
            continue
        # 변경적용 후 reload + 컨텍스트 적용 대기 — 조건 폴링(마커 소멸 → 아바타 재출현).
        # 종전 고정 2.5s + networkidle 12s + 고정 1.5s(정상 경로에서도 매번 소진)를 대체 —
        # 적용 확인 자체는 아래 패널 재오픈 + USER_TYPE_READ_JS 재독 일치가 담당한다.
        await _wait_reload_after_apply(page)
        # 공지팝업 재출현 방어(사용자 실측 2026-07-23): 변경적용 reload 마다 공지가 다시
        # 내려온다. reload 후 ~1.5s 비동기 렌더라 settle 지점에서 관찰창 2.5s 로 흡수해야
        # 재확인 패널 열기(아바타 클릭)가 백드롭(.k-overlay)에 막히지 않는다.
        await dismiss_notice_popup(page, appear_cap_ms=2_500)
        # 재확인: 패널 다시 열어 실제로 바뀌었는지.
        await open_user_panel(page)
        cur2 = await read_current_user_type(page)
        if _label_matches(cur2 or "", resolved):
            logger.info("사용자유형 전환 완료 → %s", resolved.label)
            return

    # ⚠ 'SCM-구매사용자' 같은 존재하지 않는 문구를 만들지 않는다 — 해석된 라벨과 실제 옵션
    # 목록을 그대로 노출해, 유형이 바뀌었는지 로그만 보고 판별할 수 있게 한다.
    detail = f" 실제 옵션: {list(resolved.options)}." if resolved.options else ""
    raise UserTypeError(
        f"사용자유형을 '{resolved.label}'(으)로 전환하지 못했습니다(현재 유형 미반영)."
        f"{detail} 잠시 후 다시 시도하세요."
    )
