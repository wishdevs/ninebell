"""세션 한정 서버 메모리 자격증명 캐시 (ninebell-bak `auth/credcache.py` 이식).

★ 더존 비밀번호를 디스크/DB 가 아니라 '서버 RAM'에, '활성 세션 동안만' 보관한다.
  쿠키는 불투명 식별자(세션 jti)만 운반하고 비밀번호는 서버 경계를 벗어나지 않는다.
  로그아웃/TTL 만료/서버 재시작 시 소멸 → at-rest 저장 0.

⚠ 인프로세스(단일 워커) 전제. 다중 워커/수평확장 시 sticky 세션 또는 공유 비밀저장소 필요.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

_REAP_INTERVAL_S = 60.0


@dataclass
class _Entry:
    data: dict
    expires_at: float


class CredCache:
    """jti → {"u": userid, "p": password}. 만료는 접근 시 + put 시 + 주기 reaper 로 청소."""

    def __init__(self) -> None:
        self._store: dict[str, _Entry] = {}

    def put(self, jti: str, userid: str, password: str, ttl_seconds: float) -> None:
        self._sweep()
        self._store[jti] = _Entry({"u": userid, "p": password}, time.monotonic() + ttl_seconds)

    def get(self, jti: str) -> dict | None:
        entry = self._store.get(jti)
        if entry is None:
            return None
        if time.monotonic() > entry.expires_at:
            self._store.pop(jti, None)
            return None
        return entry.data

    def delete(self, jti: str) -> None:
        self._store.pop(jti, None)

    def evict_user(self, userid: str) -> int:
        """이 userid 의 기존 엔트리 전부 제거(재로그인 시 이전 세션 고아 정리). 제거 수 반환.

        단일워커 last-login-wins: 같은 계정으로 새로 로그인하면 이전 jti 자격증명을 무효화해
        무한 누적·유령 세션을 막는다. get_current_user 의 CredCache 검사와 맞물려 이전 세션 종료.
        """
        stale = [jti for jti, e in self._store.items() if e.data.get("u") == userid]
        for jti in stale:
            self._store.pop(jti, None)
        return len(stale)

    def sweep(self) -> None:
        """만료 엔트리 전체 청소(1회)."""
        self._sweep()

    def _sweep(self) -> None:
        now = time.monotonic()
        for jti in [k for k, e in self._store.items() if now > e.expires_at]:
            self._store.pop(jti, None)

    async def reaper(self) -> None:
        """lifespan 백그라운드 태스크 — 주기적으로 만료 자격증명 청소."""
        while True:
            await asyncio.sleep(_REAP_INTERVAL_S)
            self._sweep()
