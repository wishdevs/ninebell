"""옴니솔 메뉴 진입 — 딥링크 goto + 그리드/권한팝업 폴링.

딥링크 우선(``{base}/IM/IMIIRM00700_X20616`` 등). 진입 성공 판정은 URL 이 아니라
**그리드 로드**(``.dews-ui-grid`` 개수)로 한다. 권한 없음 팝업("메뉴를 찾을 수 없습니다")이
뜨면 90초 헛돌지 않고 **즉시** :class:`MenuError` 로 실패한다(graph.py 검증 패턴).

사이드바 플라이아웃 폴백(딥링크 실패 시 아이콘 사이드바를 path 순서로 클릭)은 라이브
전용이라 여기서는 딥링크+폴링만 구현한다. 폴백 절차는 ``OMNISOL_NOTES.md`` §메뉴 참고.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from nbkit.omnisol import js_lib, latency
from nbkit.omnisol.errors import MenuError
from nbkit.omnisol.menu_schemas import MenuSchema
from nbkit.omnisol.modals import watch_notice_popup

logger = logging.getLogger("nbkit.omnisol.navigator")

MENU_TIMEOUT_MS = 25_000
# 그리드 출현 되먹임의 평시 기준선(ms) — goto(domcontentloaded) 반환 후 그리드 로드까지.
# 이보다 빠르면 비율 하한 1.0(빠름 신호)이라 기준선을 약간 후하게 잡아도 평시 factor 는
# 1.0 에 붙는다(과소 추정만이 평시 factor 를 헛되이 올린다 — 보수적으로 4s).
GRID_APPEAR_EXPECTED_MS = 4_000


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
    # networkidle 대기 금지 — 옴니솔 SPA 는 롱폴링을 유지해 networkidle 이 거의 안정되지
    # 않아 상한까지 태운다(실측 menu_nav ~7s). domcontentloaded 로 즉시 반환하고, 아래
    # 그리드 로드 폴링(MENU_CHECK_JS)을 준비 신호로 삼는다(그게 이미 진입 성공 판정 기준).
    await page.goto(
        f"{base.rstrip('/')}{menu_path}", wait_until="domcontentloaded", timeout=timeout_ms
    )
    # 적응형 상한 — ERP 지연 시 폴 간격(300ms)은 불변, **회수 상한만** 배율(≤×4)로 확대.
    t0 = time.monotonic()
    for _ in range(latency.budget_polls(tries)):
        chk = await page.evaluate(js_lib.MENU_CHECK_JS)
        if int(chk.get("grids", 0)) >= grids_required:
            # 되먹임 — 그리드 출현 실소요는 매 런 반드시 지나는 좋은 지연 관측점.
            latency.record(GRID_APPEAR_EXPECTED_MS, (time.monotonic() - t0) * 1_000)
            logger.info("%s 진입 성공(grids=%s)", label, chk.get("grids"))
            # 공지팝업 재출현 방어(사용자 실측 2026-07-23: 결의서작성 진입 후 또 뜸) — 화면
            # 전환마다 재출현할 수 있어 관찰창을 둔다. 다만 **차단형으로 기다리지 않는다**:
            # 실측(2026-07-28) 이 관찰창 2.5s 가 진입 시간에 통째로 얹혔는데, 재출현이 없는
            # 경우가 대부분이라 매 실행 ~2.8s 를 헛대기했다. 배경으로 돌리면 재출현 시에는
            # 그대로 닫히고, 안 뜨면 아무 비용이 없다. 실제 클릭 직전 JIT 확인(피커·탭 열기)은
            # 차단형으로 남아 있어 레이스 방어는 불변.
            watch_notice_popup(page, appear_cap_ms=2_500)
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
