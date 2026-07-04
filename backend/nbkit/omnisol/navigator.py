"""옴니솔 메뉴 진입 — 딥링크 goto + 그리드/권한팝업 폴링.

딥링크 우선(``{base}/IM/IMIIRM00700_X20616`` 등). 진입 성공 판정은 URL 이 아니라
**그리드 로드**(``.dews-ui-grid`` 개수)로 한다. 권한 없음 팝업("메뉴를 찾을 수 없습니다")이
뜨면 90초 헛돌지 않고 **즉시** :class:`MenuError` 로 실패한다(graph.py 검증 패턴).

사이드바 플라이아웃 폴백(딥링크 실패 시 아이콘 사이드바를 path 순서로 클릭)은 라이브
전용이라 여기서는 딥링크+폴링만 구현한다. 폴백 절차는 ``OMNISOL_NOTES.md`` §메뉴 참고.
"""

from __future__ import annotations

import logging
from typing import Any

from nbkit.omnisol import js_lib
from nbkit.omnisol.errors import MenuError
from nbkit.omnisol.menu_schemas import MenuSchema

logger = logging.getLogger("nbkit.omnisol.navigator")

MENU_TIMEOUT_MS = 25_000


async def navigate_menu(
    page: Any,
    menu_path: str,
    base: str,
    *,
    label: str = "메뉴",
    grids_required: int = 1,
    tries: int = 33,
    timeout_ms: int = MENU_TIMEOUT_MS,
) -> None:
    """``base+menu_path`` 딥링크로 진입하고 그리드 로드/권한팝업을 폴링.

    - 그리드가 ``grids_required`` 이상 뜨면 성공.
    - "찾을 수 없/권한이 없/접근" 팝업이면 즉시 :class:`MenuError`.
    - tries 회 폴링에도 그리드 미로드면 :class:`MenuError`(타임아웃).
    """
    logger.info("%s 메뉴 진입: %s%s", label, base.rstrip("/"), menu_path)
    await page.goto(
        f"{base.rstrip('/')}{menu_path}", wait_until="networkidle", timeout=timeout_ms
    )
    for _ in range(tries):
        chk = await page.evaluate(js_lib.MENU_CHECK_JS)
        if int(chk.get("grids", 0)) >= grids_required:
            logger.info("%s 진입 성공(grids=%s)", label, chk.get("grids"))
            return
        if chk.get("notFound"):
            raise MenuError(
                f"{label} 메뉴에 접근할 수 없습니다 — \"{chk.get('popup')}\". "
                "이 계정에 해당 모듈 권한이 없거나 메뉴가 이동/변경되었습니다."
            )
        await page.wait_for_timeout(300)  # 300ms 폴링(기존 1s — 상한 ~10s 유지, tries=33)
    raise MenuError(f"{label} 메뉴가 로드되지 않았습니다(그리드 미출현, 타임아웃).")


async def navigate_to(page: Any, schema: MenuSchema, base: str) -> None:
    """:class:`MenuSchema` 로 진입(딥링크·라벨·기대 그리드 수를 스키마에서 취함)."""
    await navigate_menu(
        page,
        schema.deeplink,
        base,
        label=schema.label,
        grids_required=schema.grids_expected,
    )


async def verify_plant(page: Any, *, keyword: str = "나인벨", tries: int = 8) -> dict:
    """조회 폼/타이틀에서 공장이 ``keyword``('나인벨')인지 확인. ``{ok, plant}`` 반환.

    공장이 확인될 때까지 폴링(최대 tries 초). 실패해도 예외 없이 ``ok=False`` — 상위에서
    진행 중단 여부를 결정한다(잘못된 공장 데이터 방지).
    """
    result = {"ok": False, "plant": "?"}
    for _ in range(tries):
        result = await page.evaluate(js_lib.PLANT_CHECK_JS)
        if result.get("ok"):
            break
        await page.wait_for_timeout(1_000)
    return result
