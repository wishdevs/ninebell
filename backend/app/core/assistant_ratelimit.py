"""AI 어시스턴트 채팅 레이트리밋 — 사용자당 동시 스트림·최소 간격·누적 사용량 제한.

각 요청이 유료 Gemini API 로 최대 120초 스트림을 여는데 제한이 없으면 한 사용자가
동시/연속/지속 요청으로 비용을 무제한 소모할 수 있다. 그래서 (1) 동시 스트림 수,
(2) 최소 요청 간격(버스트), (3) 롤링 윈도우당 누적 요청 수(지속 남용)를 함께 제한한다.
LoginRateLimiter(ratelimit.py)와 동일하게 인프로세스(단일 워커) 전제 — 다중 워커/재시작 시
카운터는 공유·유지되지 않는다. 유휴 엔트리는 release 시점에 정리해 무한 증식을 막는다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class _UserState:
    active: int = 0
    last_start: float = field(default=float("-inf"))
    window_start: float = field(default=float("-inf"))
    window_count: int = 0


class AssistantRateLimiter:
    """사용자당 동시 스트림 수·최소 요청 간격·롤링 윈도우 누적 요청 수를 제한한다."""

    def __init__(
        self,
        *,
        max_concurrent: int = 2,
        min_interval_s: float = 1.0,
        max_per_window: int = 120,
        window_s: float = 3600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_concurrent = max_concurrent
        self._min_interval = min_interval_s
        self._max_per_window = max_per_window
        self._window_s = window_s
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
        # 롤링 고정 윈도우: 경과했으면 카운터를 리셋한 뒤 누적 한도를 판정한다.
        if now - state.window_start >= self._window_s:
            state.window_start = now
            state.window_count = 0
        if state.window_count >= self._max_per_window:
            return "요청 한도를 초과했습니다. 잠시 후 다시 시도하세요."
        state.active += 1
        state.last_start = now
        state.window_count += 1
        return None

    def release(self, user_id: str) -> None:
        state = self._by_user.get(user_id)
        if state is None:
            return
        if state.active > 0:
            state.active -= 1
        # 진행 중 요청이 없고 윈도우까지 경과한 유휴 엔트리는 제거해 dict 무한 증식을 막는다.
        if state.active == 0 and self._clock() - state.last_start >= self._window_s:
            self._by_user.pop(user_id, None)
