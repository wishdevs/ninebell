"""확인(verify) 커널 — "값을 선택했으면 **선택됐는지 확인하고** 다음으로 간다".

옴니솔 자동화의 조용한 실패 대부분은 *클릭/세팅 호출이 성공했다* 를 *값이 반영됐다* 로
착각하는 데서 나온다(피커 '적용'이 폼에 안 붙음, 드롭다운이 change 핸들러에 되돌려짐,
조회 버튼을 눌렀지만 그리드가 아직 이전 결과, 탭이 안 열렸는데 그 화면을 조작…).
이 모듈은 그 확인을 **에이전트 공용 프리미티브**로 만든다.

분류 체계(3축)
==============
**축 1 — 무엇을 읽어 확인하나(kind)**: :func:`confirm_select` / :func:`confirm_display` /
:func:`confirm_popup_count` / :func:`confirm_grid_rows` / :func:`confirm_visible_text`.
전부 읽기 전용 리더(js_lib §C)를 쓰고, 같은 재시도 커널(:func:`confirm`)을 공유한다.

**축 2 — 언제 반영되나(timing)** → 재시도 스케줄. 전부 **즉시 1회 확인 + 실패 시 점증 대기
3회 재시도**(사용자 지시 2026-07-27)다. 반영이 빠른 값은 첫 read(대기 0ms)에서 끝나므로
**정상 경로에서 추가 지연이 0** 이다.

===========  ==========================  ==============================================
timing       대기(ms) 0→1→2→3회차         대표 대상
===========  ==========================  ==============================================
``INSTANT``  0, 120, 360, 900            native select 선택값, input readback (DOM 즉시)
``ASYNC``    0, 300, 900, 2400           피커 적용 표시값, 팝업 개폐, dialog 렌더(위젯 왕복)
``HEAVY``    0, 600, 1800, 4500          화면·탭 전환, 조회 결과 그리드(서버 왕복)
===========  ==========================  ==============================================

**축 3 — 다른 값에 영향을 주나(cascade)**: 값 A 세팅이 B 를 리셋하거나 그리드 재조회를
트리거하는 자리가 있다(결의구분 변경 → 조회조건 재구성, checkRow → 디테일 재조회 로딩,
부서 전체선택 → 팝업 레이아웃 이동). 두 가지 훅으로 다룬다:
  * ``settle`` — 매 read **직전**에 await 할 정착 코루틴(예: 로딩 오버레이 소멸 대기).
    확인이 "로딩 중 스냅샷"을 읽고 오판하는 것을 막는다.
  * ``reapply`` — 재시도 때 액션을 **다시 실행**(예: '적용' 재클릭, 드롭다운 재세팅).
    한 번 튕겨나간 값은 기다린다고 붙지 않으므로, 되돌려지는 성격의 값에만 준다.
그리고 A 가 B 를 바꾼다면 **A 확인 뒤 B 를 다시 확인**한다(호출부에서 confirm 을 이어 붙임).

⚠ 대기는 **실시간**(:func:`asyncio.sleep`)이다 — ``page.wait_for_timeout`` 을 쓰면
  워크플로우 ``delay_scale``(예: 0.4)로 대기창이 줄어들어 느린 세션에서 확인이 조기 실패한다
  (공지 팝업 관찰창이 같은 이유로 붕괴됐던 2026-07-26 사례). 이 대기는 **실패했을 때만**
  발생하므로 delay_scale 의 목적(정상 경로 단축)과 충돌하지 않는다.

⚠ 이 모듈은 **아무것도 클릭·저장하지 않는다**. 확인(read)과 재시도 오케스트레이션만 한다 —
  실제 액션은 호출자가 넘긴 ``apply``/``reapply`` 안에 있다.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Sequence

from nbkit.omnisol import js_lib

logger = logging.getLogger(__name__)

# ── 축 2: 반영 타이밍별 재시도 스케줄(ms) ──────────────────────────────────────
# 첫 원소 0 = "가능하면 딜레이 없이 확인", 이후 3회는 점증 대기 재시도.
INSTANT: tuple[int, ...] = (0, 120, 360, 900)
ASYNC: tuple[int, ...] = (0, 300, 900, 2_400)
HEAVY: tuple[int, ...] = (0, 600, 1_800, 4_500)

# 재시도 대기 구현 — 기본은 **실시간**(delay_scale 무관, 위 모듈 docstring 참조).
# 단위 테스트는 conftest 에서 이 값을 no-op 으로 갈아끼워 실패 경로가 실시간을 태우지 않게 한다
# (커널 자체의 대기 규율은 sleep= 을 직접 주입하는 전용 테스트에서 검증한다).
DEFAULT_SLEEP: Callable[[float], Awaitable[None]] = asyncio.sleep

ReadFn = Callable[[], Awaitable[Any]]
OkFn = Callable[[Any], bool]
ActionFn = Callable[[], Awaitable[Any]]


@dataclass(frozen=True)
class Confirmed:
    """확인 결과 — ``bool(result)`` 로 성공 여부를 바로 쓸 수 있다.

    actual: 마지막으로 읽은 실제 값(실패 사유 로그에 그대로 실린다).
    attempts: 수행한 read 횟수(1 = 대기 없이 첫 확인에서 성공).
    waited_ms: 재시도로 실제 대기한 총 시간(정상 경로는 0).
    """

    ok: bool
    actual: Any = None
    attempts: int = 0
    waited_ms: int = 0
    reason: Optional[str] = None
    unknown: bool = False

    def __bool__(self) -> bool:
        return self.ok

    @property
    def mismatch(self) -> bool:
        """확인은 됐는데 값이 다르다 — 하드 실패 근거(확인 불가와 구분)."""
        return not self.ok and not self.unknown


async def confirm(
    read: ReadFn,
    ok: OkFn,
    *,
    timing: Sequence[int] = ASYNC,
    what: str = "값",
    expected: Any = None,
    reapply: Optional[ActionFn] = None,
    settle: Optional[ActionFn] = None,
    unknown_when: Optional[OkFn] = None,
    sleep: Optional[Callable[[float], Awaitable[None]]] = None,
) -> Confirmed:
    """``read`` 결과가 ``ok`` 를 만족할 때까지 즉시 1회 + 점증 대기 3회 재시도로 확인한다.

    :param read: 현재 값을 읽는 코루틴(부작용 없어야 한다).
    :param ok: 읽은 값이 목표에 도달했는지 판정.
    :param timing: 재시도 스케줄(:data:`INSTANT`/:data:`ASYNC`/:data:`HEAVY`).
    :param what: 실패 메시지에 들어갈 대상 이름(예 "전표상태").
    :param expected: 실패 메시지에 들어갈 기대값(로깅 전용).
    :param reapply: 재시도 직전 액션 재실행(되돌려지는 값 전용 — 없으면 대기 후 재확인만).
    :param settle: 매 read 직전 정착 대기(연쇄 로딩 대응).
    :param unknown_when: 마지막 실패값이 "값이 다름"이 아니라 **확인 자체가 불가**(필드/위젯을
        못 읽음)임을 판정. True 면 결과에 ``unknown=True`` 가 붙어 호출자가 **하드 실패 대신
        경고 후 진행**을 택할 수 있다 — DOM 구조가 세션/버전에 따라 다를 수 있는 리더에서
        오탐이 플로우를 끊지 않게 하는 안전판(기존 D7 체크행수 판정과 같은 규율).
    :param sleep: 대기 구현 주입(테스트용). 기본은 실시간 :func:`asyncio.sleep`.

    읽기 자체가 예외를 던지면(스텁/버전차/네비게이션 중) 그 회차는 실패로 보고 재시도한다 —
    확인 코드가 런을 죽이지 않는다.
    """
    nap = sleep or DEFAULT_SLEEP
    actual: Any = None
    last_err: Optional[str] = None
    waited = 0
    for attempt, delay in enumerate(timing, start=1):
        if delay:
            await nap(delay / 1000)
            waited += delay
            if reapply is not None:
                try:
                    await reapply()
                except Exception as exc:  # noqa: BLE001 — 재실행 실패는 재확인으로 판정.
                    last_err = f"재시도 실행 실패: {exc}"
        if settle is not None:
            try:
                await settle()
            except Exception:  # noqa: BLE001 — 정착 훅은 best-effort.
                pass
        try:
            actual = await read()
        except Exception as exc:  # noqa: BLE001 — 읽기 실패는 이번 회차 실패로만 취급.
            last_err = str(exc)[:200]
            continue
        if ok(actual):
            if attempt > 1:
                logger.info("확인 성공 — %s (%s회차, %sms 대기)", what, attempt, waited)
            return Confirmed(True, actual, attempt, waited)
    unknown = bool(unknown_when(actual)) if unknown_when else False
    reason = (
        f"{what} " + ("확인 불가" if unknown else "확인 실패")
        + (f"(기대 {expected!r}" if expected is not None else "(")
        + f" / 실제 {actual!r}, {len(timing)}회 시도 {waited}ms 대기)"
        + (f" — {last_err}" if last_err else "")
    )
    logger.warning("%s", reason)
    return Confirmed(False, actual, len(timing), waited, reason, unknown)


# ══════════════════════════════════════════════════════════════════════════════
# 축 1 — 종류별 확인 헬퍼(전부 위 커널 재사용). page 는 Playwright Page 또는 자식 Page.
# ══════════════════════════════════════════════════════════════════════════════
def _norm(v: Any) -> str:
    return " ".join(str("" if v is None else v).split())


async def confirm_select(
    page: Any, selector: str, text: str, *, timing: Sequence[int] = INSTANT, **kw: Any
) -> Confirmed:
    """드롭다운(native/kendo)의 **현재 선택 텍스트**가 ``text`` 인지 확인(즉시 반영 계열).

    ⚠ 세팅 JS 의 ``{ok:true}`` 는 "옵션을 찾아 값을 넣었다"까지다 — change 핸들러가 값을
    되돌리는 자리(연쇄 필드)가 있어 이 리더로 실제 선택값을 재확인해야 확정된다.
    """
    want = _norm(text)

    async def read() -> Any:
        return await page.evaluate(js_lib.SELECTED_TEXT_JS, selector)

    def ok(v: Any) -> bool:
        return isinstance(v, dict) and bool(v.get("ok")) and _norm(v.get("text")) == want

    return await confirm(read, ok, timing=timing, what=f"드롭다운 {selector}", expected=text, **kw)


async def confirm_display(
    page: Any,
    label: str,
    *,
    contains: str | None = None,
    timing: Sequence[int] = ASYNC,
    **kw: Any,
) -> Confirmed:
    """조회조건 필드(코드피커)의 **표시값**을 확인 — 팝업 '적용'이 폼에 붙었는지의 단일 근거.

    ``contains`` 를 주면 표시값에 그 문자열이 포함되는지, 없으면 **비어있지 않은지**만 본다
    (전체선택·다중선택처럼 표시 형식이 세션마다 달라 정확일치를 요구할 수 없는 자리를 위해).

    리더가 ``null`` 을 주면(라벨/피커 미발견) '값이 다름'이 아니라 **확인 불가**로 분류한다.
    """
    need = _norm(contains) if contains else None
    kw.setdefault("unknown_when", lambda v: v is None)

    async def read() -> Any:
        return await page.evaluate(js_lib.FIELD_DISPLAY_JS, label)

    def ok(v: Any) -> bool:
        s = _norm(v)
        if not s:
            return False
        return need in s if need else True

    return await confirm(
        read, ok, timing=timing, what=f"'{label}' 표시값", expected=contains or "(비어있지 않음)", **kw
    )


async def confirm_display_empty(
    page: Any, label: str, *, timing: Sequence[int] = ASYNC, **kw: Any
) -> Confirmed:
    """조회조건 필드가 **비워졌는지** 확인(작성자/결의자 clear 계열).

    ⚠ ``null``(필드 미발견)을 '비었다'로 통과시키면 clear 실패를 못 잡는다 — 필드를 **읽었는데
    값이 빈 문자열**일 때만 성공이고, null 은 확인 불가로 분류한다.
    """
    kw.setdefault("unknown_when", lambda v: v is None)

    async def read() -> Any:
        return await page.evaluate(js_lib.FIELD_DISPLAY_JS, label)

    return await confirm(
        read,
        lambda v: v is not None and not _norm(v),
        timing=timing,
        what=f"'{label}' 비움",
        expected="(빈 값)",
        **kw,
    )


async def confirm_popup_count(
    page: Any,
    *,
    more_than: int | None = None,
    less_than: int | None = None,
    timing: Sequence[int] = ASYNC,
    **kw: Any,
) -> Confirmed:
    """보이는 k-window 팝업 개수로 **열림/닫힘**을 확인.

    ``more_than=before`` = 새 팝업이 떴다, ``less_than=before`` = 팝업이 닫혔다.
    (스테일 잔여 팝업을 새 팝업으로 오독하는 사고를 개수 변화로 차단한다.)
    """

    async def read() -> Any:
        return await page.evaluate(js_lib.POPUP_COUNT_JS)

    def ok(v: Any) -> bool:
        if not isinstance(v, int):
            return False
        if more_than is not None and v <= more_than:
            return False
        if less_than is not None and v >= less_than:
            return False
        return True

    want = f">{more_than}" if more_than is not None else f"<{less_than}"
    return await confirm(read, ok, timing=timing, what="팝업 개수", expected=want, **kw)


async def confirm_grid_rows(
    page: Any,
    *,
    index: int = 0,
    min_rows: int = 0,
    timing: Sequence[int] = HEAVY,
    **kw: Any,
) -> Confirmed:
    """그리드[index] 가 **로딩을 마치고** rowcount 를 낼 때까지 확인(조회 실행 계열).

    기본 ``min_rows=0`` — 0건도 정상 결과다(대상 없음). 확인하는 것은 "그리드가 응답 가능한
    상태"이지 "행이 있다"가 아니다. 결과 존재까지 요구할 때만 ``min_rows=1``.
    """

    async def read() -> Any:
        return await page.evaluate(js_lib.ROWCOUNT_BY_INDEX_JS, index)

    return await confirm(
        read,
        lambda v: isinstance(v, int) and v >= min_rows,
        timing=timing,
        what=f"그리드[{index}] rowcount",
        expected=f">={min_rows}",
        **kw,
    )


async def confirm_visible_element(
    page: Any, selector: str, *, present: bool = True, timing: Sequence[int] = HEAVY, **kw: Any
) -> Confirmed:
    """지정 컨트롤이 화면에 **보이는지**로 화면·탭 도착을 확인(``present=False`` 면 벗어남).

    ⚠ 다중 메뉴 탭에서는 다른 탭의 DOM 이 그대로 남아 있어 '존재'가 아니라 **가시성**으로
    판정해야 한다(엉뚱한 탭을 조작하는 사고 차단).

    ⚠⚠ **native select 를 앵커로 쓰지 말 것**(2026-07-27 라이브 실패): kendo DropDownList 는
    원본 ``<select>`` 를 ``display:none`` 으로 숨기고 위젯을 대신 그린다 — 올바른 화면에
    도착해도 select 는 영원히 '안 보임'이라 이 확인이 **항상 실패**한다(세팅은 jQuery 위젯
    API 라 숨은 select 에서도 정상 동작하므로, 가시성 앵커로만 부적합하다).
    화면 앵커는 :func:`confirm_visible_label`(조회조건 라벨)이나 실제 버튼 rect 처럼
    **눈에 보이는 것**으로 잡는다.
    """

    async def read() -> Any:
        return await page.evaluate(js_lib.VISIBLE_ELEMENT_JS, selector)

    return await confirm(
        read,
        lambda v: bool(v) is present,
        timing=timing,
        what=f"컨트롤 {selector}",
        expected="표시" if present else "숨김",
        **kw,
    )


async def confirm_visible_label(
    page: Any, label: str, *, present: bool = True, timing: Sequence[int] = HEAVY, **kw: Any
) -> Confirmed:
    """조회조건 **라벨**(+ 그 필드의 돋보기 버튼)이 렌더돼 있는지 — 화면·탭 도착 확인의 기본기.

    비활성 메뉴 탭의 라벨은 렌더되지 않으므로 "그 화면에 있다"의 신뢰할 수 있는 근거이고,
    kendo 가 숨기는 native select 와 달리 **실제로 보이는 요소**라 도착 판정에 안전하다.
    (같은 리더가 optional-area 접힘 감지에도 쓰인다 — `ensure_field_visible`.)
    """

    async def read() -> Any:
        return await page.evaluate(js_lib.FIELD_LABEL_VISIBLE_JS, label)

    return await confirm(
        read,
        lambda v: bool(v) is present,
        timing=timing,
        what=f"조회조건 '{label}' 라벨",
        expected="표시" if present else "숨김",
        **kw,
    )


async def confirm_visible_text(
    page: Any, text: str, *, present: bool = True, timing: Sequence[int] = HEAVY, **kw: Any
) -> Confirmed:
    """화면에 ``text`` 가 보이는지(=화면·탭 전환, dialog 렌더) 확인. ``present=False`` 면 사라짐."""

    async def read() -> Any:
        return await page.evaluate(js_lib.VISIBLE_TEXT_JS, text)

    return await confirm(
        read,
        lambda v: bool(v) is present,
        timing=timing,
        what=f"화면 텍스트 '{text}'",
        expected="표시" if present else "사라짐",
        **kw,
    )


async def apply_confirm(
    apply: ActionFn,
    verify: Callable[..., Awaitable[Confirmed]],
    *,
    retry_apply: bool = False,
    **verify_kw: Any,
) -> Confirmed:
    """"실행 → 확인" 한 줄 조립 — ``apply`` 를 실행한 뒤 ``verify`` 로 확인한다.

    ``retry_apply=True`` 면 재시도 회차마다 ``apply`` 를 다시 실행한다(되돌려지는 값 전용).
    ``verify`` 는 위 ``confirm_*`` 중 하나를 :func:`functools.partial` 로 묶어 넘긴다.
    """
    await apply()
    if retry_apply:
        verify_kw.setdefault("reapply", apply)
    return await verify(**verify_kw)
