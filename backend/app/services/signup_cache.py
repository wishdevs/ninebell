"""회원가입 대기 캐시 — 서버 RAM 에 pending-signup 을 TTL 로 보관 (CredCache 패턴 이식).

★ 옴니솔 인증엔 성공했지만 DB 에 계정이 없는 '첫 접속' 사용자의 자격증명·프로필을
  회원가입 완료 전까지 잠깐(기본 10분) 서버 메모리에 보관한다. 쿠키/DB 저장 없음.
  서버 재시작 시 소실 무방 — 사용자가 재로그인하면 새 토큰이 재발급된다.

⚠ 인프로세스(단일 워커) 전제. 다중 워커/수평확장 시 공유 저장소 필요.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass

# pending-signup 유효기간(초). 회원가입 화면에서 이메일/약관 입력에 충분한 여유.
_TTL_SECONDS = 600.0
_REAP_INTERVAL_S = 120.0


@dataclass
class _Entry:
    data: dict
    expires_at: float


class SignupCache:
    """signup_token → {userid, password, display_name, department}.

    만료는 접근 시(get) + 저장 시(put) + 주기 reaper 로 청소한다.
    """

    def __init__(self, ttl_seconds: float = _TTL_SECONDS) -> None:
        self._store: dict[str, _Entry] = {}
        self._ttl = ttl_seconds

    def put(self, userid: str, password: str, display_name: str, department: str) -> str:
        """pending 을 저장하고 새 signup_token 을 반환."""
        self._sweep()
        token = uuid.uuid4().hex
        self._store[token] = _Entry(
            {
                "userid": userid,
                "password": password,
                "display_name": display_name,
                "department": department,
            },
            time.monotonic() + self._ttl,
        )
        return token

    def get(self, token: str) -> dict | None:
        entry = self._store.get(token)
        if entry is None:
            return None
        if time.monotonic() > entry.expires_at:
            self._store.pop(token, None)
            return None
        return entry.data

    def delete(self, token: str) -> None:
        self._store.pop(token, None)

    def _sweep(self) -> None:
        now = time.monotonic()
        for token in [k for k, e in self._store.items() if now > e.expires_at]:
            self._store.pop(token, None)

    async def reaper(self) -> None:
        """lifespan 백그라운드 태스크 — 주기적으로 만료 엔트리 청소."""
        while True:
            await asyncio.sleep(_REAP_INTERVAL_S)
            self._sweep()
