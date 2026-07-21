"""CDP 스크린캐스트 펌프 — 헤드리스 페이지의 화면 변화를 events 로 흘린다(라이브 뷰).

주기 캡처(노드별 스냅샷) 대신 CDP `Page.startScreencast` 로 화면이 바뀔 때마다 jpeg
프레임을 받아 `{"screenshot": "data:..."}` 프레임으로 방출한다. 옴니솔이 정적이라 변화가
있을 때만 프레임이 와서 효율적이다. 러너가 종료 시 이 태스크를 cancel → stopScreencast.

⚠ 프레임 ack(`Page.screencastFrameAck`)를 하지 않으면 CDP 가 몇 프레임 뒤 캐스트를 멈춘다.
   반드시 프레임마다 ack 해야 스트림이 지속된다.

ninebell-bak `erp/graph.py` 의 `_screencast_pump`/`_ack` 를 이식했다. 원본은 login 노드가
만든 페이지를 browser 에서 집어왔지만, 여기선 러너가 만든 page 를 직접 받는다.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


async def _ack(cdp: Any, session_id: str) -> None:
    try:
        await cdp.send("Page.screencastFrameAck", {"sessionId": session_id})
    except Exception:
        pass


async def screencast_pump(page: Any, events: asyncio.Queue, window: str = "parent") -> None:
    """page 의 화면 변화 프레임을 events 로 흘린다. page 가 없거나 CDP 실패 시 조용히 종료.

    window: 이 캐스트가 어느 브라우저 창을 담는지('parent'=주 페이지 / 'child'=팝업·자식 창).
    기본 'parent' 이면 프레임에 window 키를 넣지 않아 기존 단일 페이지 계약과 바이트 동일하다
    (하위 호환). 'child' 일 때만 프레임에 ``"window": "child"`` 를 실어 FE 가 자식 탭으로 라우팅.
    """
    if page is None:
        return
    try:
        cdp = await page.context.new_cdp_session(page)
    except Exception:
        logger.warning("screencast: CDP 세션 생성 실패")
        return

    def on_frame(params: dict) -> None:
        # 자식 페이지가 닫힌 뒤 늦게 도착한 CDP 프레임(인플라이트)은 무시한다 — closed 전이 이후
        # 자식 슬롯을 되살려 스테일 탭이 재활성되는 레이스의 1차 방어(HIGH-3). 닫힌 page 프레임 no-op.
        if page.is_closed():
            return
        data = params.get("data")
        if data:
            frame: dict = {"screenshot": "data:image/jpeg;base64," + data}
            if window != "parent":
                frame["window"] = window
            try:
                events.put_nowait(frame)
            except Exception:
                pass
        sid = params.get("sessionId")
        if sid is not None:  # ack 안 하면 몇 프레임 후 캐스트가 멈춤
            asyncio.create_task(_ack(cdp, sid))

    cdp.on("Page.screencastFrame", on_frame)
    s = get_settings()
    try:
        await cdp.send(
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": s.screencast_quality,
                "maxWidth": s.screencast_max_width,
                "maxHeight": s.screencast_max_height,
                "everyNthFrame": s.screencast_every_nth_frame,
            },
        )
    except Exception:
        logger.warning("screencast: startScreencast 실패")
        return
    try:  # 러너가 끝날 때까지 유지(취소되면 캐스트 정리)
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        try:
            await cdp.send("Page.stopScreencast")
        except Exception:
            pass
        raise
