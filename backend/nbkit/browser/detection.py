"""상태 감지 프리미티브 — 인증 여부·팝업/에러·요소 카운트(앱-불문 일반).

옴니솔 로그인은 성공해도 URL 이 그대로일 수 있다(flow 문서 §1). 따라서 성공 판정은
**URL 이 아니라 요소 상태**로 한다: (a) 로그인 폼이 사라졌는가, (b) 대시보드 요소 수가
임계값을 넘었는가. 옴니솔 특화 셀렉터는 상위 계층(:mod:`nbkit.omnisol.selectors`)에서
주입받아 이 모듈 자체는 앱 독립적으로 둔다.
"""

from __future__ import annotations

from typing import Any, Optional

from nbkit.browser.actions import safe_evaluate

# 로그인 후 대시보드 위젯이 채워지며 요소 수가 이 임계값을 넘는다(login skill v3).
DEFAULT_AUTH_ELEMENT_THRESHOLD = 200


async def count_elements(page: Any) -> int:
    """``document.querySelectorAll('*').length`` — 대시보드 로드 판정용 요소 수."""
    n = await safe_evaluate(page, "() => document.querySelectorAll('*').length", default=0)
    return int(n or 0)


async def selector_present(page: Any, selector: str) -> bool:
    """``selector`` 요소가 하나라도 존재하는지."""
    ok = await safe_evaluate(
        page, "(s) => !!document.querySelector(s)", selector, default=False
    )
    return bool(ok)


async def selector_count(page: Any, selector: str) -> int:
    """``selector`` 매칭 요소 수(예: '.dews-ui-grid' 그리드 개수로 메뉴 로드 판정)."""
    n = await safe_evaluate(
        page, "(s) => document.querySelectorAll(s).length", selector, default=0
    )
    return int(n or 0)


async def is_authenticated(
    page: Any,
    *,
    login_selector: Optional[str] = None,
    min_elements: int = DEFAULT_AUTH_ELEMENT_THRESHOLD,
) -> bool:
    """인증 여부 판정.

    - ``login_selector`` 주어지면: 그 로그인 폼 요소가 **사라졌으면** 인증됨(폼-소멸 전략,
      옴니솔 실측 경로).
    - 아니면: 요소 수가 ``min_elements`` 를 넘으면 인증됨(요소-카운트 전략, warm 재사용 판정).
    """
    if login_selector is not None:
        return not await selector_present(page, login_selector)
    return await count_elements(page) > min_elements


# 화면을 막는 가시 다이얼로그(권한 없음·에러·Kendo 윈도우) 후보 셀렉터.
_DIALOG_SELECTORS = ".k-window, [role=dialog], .modal"


async def detect_dialog(page: Any, *, selectors: str = _DIALOG_SELECTORS) -> dict:
    """가시(offsetParent!==null) 다이얼로그의 텍스트를 best-effort 로 읽어 반환.

    반환: ``{"visible": bool, "text": str}``. 권한/에러 팝업을 상위에서 도메인 오류로
    승격시키는 데 쓴다(예: 메뉴 접근 불가 판정).
    """
    js = (
        "(sel) => { const dlg = [...document.querySelectorAll(sel)]"
        ".find(x => x.offsetParent !== null);"
        " if (!dlg) return { visible: false, text: '' };"
        " return { visible: true, text: (dlg.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 120) }; }"
    )
    res = await safe_evaluate(page, js, selectors, default={"visible": False, "text": ""})
    return res or {"visible": False, "text": ""}
