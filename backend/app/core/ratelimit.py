"""로그인 시도 제한 — 인메모리(단일 워커 전제) 브루트포스 방어.

★ userid 와 IP 를 **독립 창**으로 카운트한다: userid 창은 한 계정 집중 추측(스터핑)을,
  IP 창은 한 소스가 여러 계정을 훑는 스프레이를 막는다. **실패만** 카운트하고 성공하면
  해당 userid 창을 리셋한다. 창 내 실패가 임계치를 넘으면 지수 백오프로 잠근다.

⚠ CredCache 와 동일하게 인프로세스(단일 워커) 전제 — 다중 워커/재시작 시 카운터는 공유·유지되지
  않는다(재시작 시 소실은 허용). 별도 reaper 없이 check/record 시 lazy prune 한다.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class _Entry:
    # 창(window_s) 내 실패 시각들(monotonic). 오래된 것은 prune.
    failures: deque[float] = field(default_factory=deque)
    # 잠금 해제 시각(monotonic). 0 이면 잠금 없음.
    locked_until: float = 0.0
    # 연속 잠금 횟수(백오프 지수).
    strikes: int = 0


class LoginRateLimiter:
    """로그인 시도 제한기. clock 주입으로 테스트 가능."""

    def __init__(
        self,
        *,
        max_attempts: int = 5,
        window_s: float = 900.0,
        ip_max_attempts: int = 20,
        lockout_base_s: float = 30.0,
        lockout_max_s: float = 900.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_attempts
        self._window = window_s
        self._ip_max = ip_max_attempts
        self._base = lockout_base_s
        self._cap = lockout_max_s
        self._clock = clock
        self._by_user: dict[str, _Entry] = {}
        self._by_ip: dict[str, _Entry] = {}

    @staticmethod
    def _norm(userid: str) -> str:
        return userid.strip().lower()

    def _prune(self, entry: _Entry, now: float) -> None:
        cutoff = now - self._window
        while entry.failures and entry.failures[0] < cutoff:
            entry.failures.popleft()

    def _remaining_lock(self, entry: _Entry | None, now: float) -> float:
        if entry is None or entry.locked_until <= now:
            return 0.0
        return entry.locked_until - now

    def check(self, ip: str | None, userid: str) -> int | None:
        """차단 중이면 남은 초(올림, 최소 1)를 반환, 아니면 None."""
        now = self._clock()
        remaining = 0.0
        u = self._by_user.get(self._norm(userid))
        if u is not None:
            self._prune(u, now)
            remaining = max(remaining, self._remaining_lock(u, now))
        if ip:
            i = self._by_ip.get(ip)
            if i is not None:
                self._prune(i, now)
                remaining = max(remaining, self._remaining_lock(i, now))
        if remaining > 0:
            return max(1, int(remaining + 0.999))
        return None

    def _record(self, store: dict[str, _Entry], key: str, threshold: int, now: float) -> None:
        entry = store.setdefault(key, _Entry())
        self._prune(entry, now)
        entry.failures.append(now)
        if len(entry.failures) >= threshold:
            lock = min(self._base * (2**entry.strikes), self._cap)
            entry.locked_until = now + lock
            entry.strikes += 1
            entry.failures.clear()  # 잠금 시작 시 창 리셋(잠금 후 즉시 재잠금 방지).

    def record_failure(self, ip: str | None, userid: str) -> None:
        """자격증명 실패 1건 기록(임계 초과 시 잠금)."""
        now = self._clock()
        self._record(self._by_user, self._norm(userid), self._max, now)
        if ip:
            self._record(self._by_ip, ip, self._ip_max, now)

    def reset(self, userid: str) -> None:
        """로그인 성공 — 해당 userid 창을 제거(IP 창은 다른 계정 보호 위해 유지)."""
        self._by_user.pop(self._norm(userid), None)
