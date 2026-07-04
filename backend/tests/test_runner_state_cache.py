"""runner 세션 워밍(storage_state 캐시) — Phase 2b 속도 최적화 회귀 테스트.

캐시는 RAM 전용·TTL 기반이며, 저장은 로그인 폼이 없을 때(인증됨)만 일어난다.
만료/무효 상태는 login 노드가 폼을 보고 정상 로그인하므로 순수 최적화다.
"""

from __future__ import annotations

import pytest

from app.live import runner

pytestmark = pytest.mark.asyncio


class _Ctx:
    def __init__(self, state: dict):
        self._state = state

    async def storage_state(self):
        return self._state


class _Page:
    def __init__(self, *, authed: bool, state: dict | None = None):
        self._authed = authed
        self.context = _Ctx(state or {"cookies": [{"name": "JSESSIONID"}]})

    async def evaluate(self, script, arg=None):
        # _save_state 의 로그인 폼 부재 체크: 인증됨 → true.
        return self._authed


@pytest.fixture(autouse=True)
def _clean_cache():
    runner._state_cache.clear()
    yield
    runner._state_cache.clear()


async def test_save_state_caches_only_when_authenticated():
    await runner._save_state(_Page(authed=False), "u1")
    assert runner._cached_state("u1") is None  # 로그인 폼 보임 → 저장 안 함
    await runner._save_state(_Page(authed=True), "u1")
    assert runner._cached_state("u1") is not None


async def test_cached_state_expires_after_ttl(monkeypatch):
    await runner._save_state(_Page(authed=True), "u2")
    assert runner._cached_state("u2") is not None
    # TTL 경과를 시뮬레이션 — monotonic 을 미래로.
    saved_at, state = runner._state_cache["u2"]
    runner._state_cache["u2"] = (saved_at - runner._STATE_TTL_S - 1, state)
    assert runner._cached_state("u2") is None  # 만료 → 제거·None
    assert "u2" not in runner._state_cache


async def test_save_state_tolerates_broken_page():
    class _Broken:
        context = None

        async def evaluate(self, *a):
            raise RuntimeError("browser gone")

    await runner._save_state(_Broken(), "u3")  # 예외를 삼켜야 한다
    assert runner._cached_state("u3") is None


async def test_cached_state_none_for_missing_userid():
    assert runner._cached_state(None) is None
    assert runner._cached_state("") is None
