"""AI 어시스턴트 채팅 레이트리밋 — 사용자당 동시 스트림 수 + 최소 요청 간격 제한.

각 요청이 유료 Gemini API 로 최대 120초 스트림을 여는데 별도 제한이 없으면 한 사용자가
동시/연속 요청으로 비용을 무제한 소모할 수 있다. LoginRateLimiter(ratelimit.py)와 동일하게
인프로세스(단일 워커) 전제 — 다중 워커/재시작 시 카운터는 공유·유지되지 않는다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class _UserState:
    active: int = 0
    last_start: float = field(default=float("-inf"))


class AssistantRateLimiter:
    """사용자당 동시 스트림 수·최소 요청 간격을 제한한다."""

    def __init__(
        self,
        *,
        max_concurrent: int = 2,
        min_interval_s: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_concurrent = max_concurrent
        self._min_interval = min_interval_s
        self._clock = clock
        self._by_user: dict[str, _UserState] = {}

    def try_acquire(self, user_id: str) -> str | None:
        """허용되면 None 을 반환하고 슬롯을 점유한다. 거부면 사유 문자열을 반환(상태 불변)."""
        now = self._clock()
        state = self._by_user.setdefault(user_id, _UserState())
        if state.active >= self._max_concurrent:
            return "동시 요청이 너무 많습니다. 이전 응답이 끝난 뒤 다시 시도하세요."
        if now - state.last_start < self._min_interval:
            return "요청이 너무 빠릅니다. 잠시 후 다시 시도하세요."
        state.active += 1
        state.last_start = now
        return None

    def release(self, user_id: str) -> None:
        state = self._by_user.get(user_id)
        if state is not None and state.active > 0:
            state.active -= 1
