"""메뉴 진입 플로우 — navigate(page, …): 딥링크 진입 + 진행 이벤트.

navigator.navigate_menu 를 감싸 step/log/스냅샷을 emit. 실패 시 :class:`MenuError`.
:class:`MenuSchema` 로 진입하는 :func:`navigate_schema` 도 제공(딥링크·라벨·기대그리드 자동).

렌더러 크래시("Page crashed" 류) 한정 **1회 복구**를 내장한다(라이브 실증 2026-07-31:
gyeongjo-grant 런이 goto 중 "Page.goto: Page crashed" 로 즉사했고 2분 뒤 동일 경로가 1.2s에
정상 진입 — 일시적 크래시라 1회 재시도만 있었어도 런이 살았다). 같은 컨텍스트에 새 페이지를
만들어 진입을 1회 재시도하고, 성공 시 **사용 중인 page 를 반환**해 호출부(에이전트 menu_nav
노드)가 이후 플로우에 전파할 수 있게 한다. 일반 타임아웃·권한 오류(MenuError)는 기존대로
즉시 실패한다(재시도 없음).
"""

from __future__ import annotations

import time
from typing import Any, Optional

from nbkit.omnisol.errors import MenuError
from nbkit.omnisol.menu_schemas import MenuSchema
from nbkit.omnisol.navigator import navigate_menu
from nbkit.patterns import EmitFn, emit_log, emit_shot, emit_step

# 렌더러 크래시 계열 Playwright 오류 메시지 마커 — 이때만 새 페이지로 1회 재시도한다.
# 일반 타임아웃("Timeout … exceeded")은 매칭되지 않아 기존 즉시 실패 동작이 유지된다.
_CRASH_MARKERS = (
    "Page crashed",
    "Target crashed",
    "Target closed",
    "Target page, context or browser has been closed",
)


def _is_crash_error(exc: BaseException) -> bool:
    """일시적 렌더러 크래시 계열 오류인지 메시지로 판정(도메인 오류 MenuError 는 제외)."""
    if isinstance(exc, MenuError):
        return False
    msg = str(exc)
    return any(marker in msg for marker in _CRASH_MARKERS)


async def _replace_crashed_page(page: Any) -> Any:
    """크래시한 page 를 같은 컨텍스트의 새 페이지로 교체(세션 쿠키·컨텍스트 뷰포트 유지).

    러너의 대기 배율 프록시(_ScaledPage: ``_page``/``_scale`` 보유)면 새 페이지도 같은
    배율로 재래핑한다 — 교체로 배율이 유실되면 이후 대기가 원속도로 돌아간다. 크래시한
    원본 페이지는 베스트에포트로 닫는다(렌더러 자원 반환) — 실패는 무시.
    """
    fresh = await page.context.new_page()  # 프록시면 context 접근이 원본 page 로 위임된다.
    raw = getattr(page, "_page", None)
    scale = getattr(page, "_scale", None)
    old = page
    if raw is not None and scale is not None:
        fresh = type(page)(fresh, scale)
        old = raw
    try:
        await old.close()
    except Exception:  # noqa: BLE001 — 크래시 페이지 close 실패는 무해(브라우저 종료 시 회수).
        pass
    return fresh


async def _navigate_with_crash_recovery(
    page: Any,
    menu_path: str,
    base: str,
    *,
    label: str,
    grids_required: int,
    emit: Optional[EmitFn],
) -> Any:
    """navigate_menu + 크래시 한정 1회 복구. 진입에 **사용된 page**(원본 또는 교체본) 반환."""
    try:
        await navigate_menu(page, menu_path, base, label=label, grids_required=grids_required)
        return page
    except Exception as exc:
        if not _is_crash_error(exc):
            raise  # 크래시가 아닌 오류(타임아웃·권한 등)는 기존대로 즉시 실패.
        await emit_log(emit, "페이지 크래시 감지 — 새 페이지로 1회 재시도합니다.", "warn")
        try:
            fresh = await _replace_crashed_page(page)
        except Exception:  # noqa: BLE001 — 컨텍스트/브라우저까지 죽어 새 페이지 생성 불가.
            await emit_log(emit, "페이지 크래시 복구 실패 — 새 페이지를 만들지 못했습니다.", "error")
            raise exc  # 원인(크래시) 예외를 그대로 올려 기존 실패 메시지를 유지한다.
        try:
            await navigate_menu(fresh, menu_path, base, label=label, grids_required=grids_required)
        except Exception:
            await emit_log(
                emit, "페이지 크래시 복구 실패 — 새 페이지 재시도에서도 진입하지 못했습니다.", "error"
            )
            raise
        # 스크린캐스트는 러너 소유(구 page 에 CDP 부착)라 여기서 재부착할 수 없다 —
        # 러너의 context.on("page") 리스너가 새 페이지를 자식 창 캐스트로 잡아주지만,
        # 기존(부모) 미리보기 프레임은 마지막 화면에서 멈출 수 있음을 사용자에게 알린다.
        await emit_log(
            emit,
            "페이지 크래시 복구 성공 — 새 페이지로 진입을 계속합니다. "
            "라이브 미리보기가 잠시 중단되거나 새 창 탭으로 전환될 수 있습니다.",
            "warn",
        )
        return fresh


async def navigate(
    page: Any,
    menu_path: str,
    base: str,
    *,
    label: str = "메뉴",
    grids_required: int = 1,
    emit: Optional[EmitFn] = None,
    step_id: Optional[str] = "menu_nav",
) -> Any:
    """``base+menu_path`` 딥링크로 진입(그리드 로드 폴링·권한팝업 즉시실패).

    반환: 진입에 실제 사용된 page — 크래시 복구로 교체됐으면 **새 page**(호출부는 이후
    조작에 반환값을 써야 한다), 아니면 인자로 받은 page 그대로(기존 호출부는 반환값을
    무시해도 동작 불변).

    step_id=None 이면 **스텝 프레임만 억제**한다(로그·스냅샷은 유지) — 병렬 워커·단계 중간
    재진입이 완료된 menu_nav 스텝을 running 으로 되돌려 진행 타임라인이 뒤로 점프하던
    문제의 근본 수정(2026-09-01, 구매발주 3세션 병렬화 실측).
    """
    if step_id:
        await emit_step(emit, step_id, "running")
    await emit_log(emit, f"{label} 메뉴 진입 중…", "info")
    t0 = time.monotonic()
    try:
        active = await _navigate_with_crash_recovery(
            page, menu_path, base, label=label, grids_required=grids_required, emit=emit
        )
    except Exception:
        if step_id:
            await emit_step(emit, step_id, "failed")
        raise
    await emit_shot(emit, active)
    if step_id:
        await emit_step(emit, step_id, "done", int((time.monotonic() - t0) * 1000))
    return active


async def navigate_schema(
    page: Any,
    schema: MenuSchema,
    base: str,
    *,
    emit: Optional[EmitFn] = None,
    step_id: Optional[str] = "menu_nav",
) -> Any:
    """:class:`MenuSchema` 로 진입(딥링크·라벨·기대 그리드 수를 스키마에서).

    반환: :func:`navigate` 와 동일 — 진입에 실제 사용된 page(크래시 복구 시 새 page).
    step_id=None 은 :func:`navigate` 와 같은 의미(스텝 프레임 억제 — 워커 재진입용).
    """
    return await navigate(
        page,
        schema.deeplink,
        base,
        label=schema.label,
        grids_required=schema.grids_expected,
        emit=emit,
        step_id=step_id,
    )
