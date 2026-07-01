"""Trusted 키보드 프리미티브 — 캔버스 그리드의 상세 로딩을 깨우는 실제 키 입력.

★ 핵심 함정(experience-grid-data-extraction.md §3-B):
  더존 RealGrid(캔버스)의 **디테일 로드 핸들러는 실제 키보드 입력(trusted)에만 반응**한다.
  ``setCurrent()``(JS)·좌표 클릭은 디테일 로딩을 트리거하지 않는다. 따라서 마스터 행을
  옮겨 상세를 불러올 때는 반드시 ``page.keyboard.press('ArrowDown')`` 같은 trusted 키를 쓴다.
  누락 시 :func:`jiggle`(ArrowUp→ArrowDown)로 재요청을 유도한다.

이름이 ``frames`` 인 이유: 그리드/모달 등 활성 프레임에 대한 저수준 입력 접점을 모은 곳.
"""

from __future__ import annotations

from typing import Any


async def press_arrow_down(page: Any) -> None:
    """실제 ArrowDown — 마스터 다음 행으로 이동 → 앱이 해당 상세를 로드/렌더."""
    await page.keyboard.press("ArrowDown")


async def press_arrow_up(page: Any) -> None:
    """실제 ArrowUp — 이전 행으로. jiggle 재시도의 앞 절반."""
    await page.keyboard.press("ArrowUp")


async def press_enter(page: Any) -> None:
    """실제 Enter — 팝업 검색 실행 등(예: 프로젝트 검색 #s_search_key 입력 후)."""
    await page.keyboard.press("Enter")


async def press_escape(page: Any) -> None:
    """실제 Escape — 모달/에디터 닫기."""
    await page.keyboard.press("Escape")


async def jiggle(page: Any, *, settle_ms: int = 400) -> None:
    """ArrowUp→ArrowDown 지글 — 상세 누락 시 같은 행을 다시 앵커링해 재로딩을 유도.

    experience 문서의 검증된 복구 동작. ``settle_ms`` 는 각 키 사이 렌더 정착 대기.
    """
    await page.keyboard.press("ArrowUp")
    await page.wait_for_timeout(settle_ms)
    await page.keyboard.press("ArrowDown")
    await page.wait_for_timeout(settle_ms)
