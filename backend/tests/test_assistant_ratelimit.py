"""AssistantRateLimiter 단위 테스트 — 동시 슬롯 상한 + 최소 요청 간격."""

from __future__ import annotations

from app.core.assistant_ratelimit import AssistantRateLimiter


def test_try_acquire_allows_up_to_max_concurrent_then_denies():
    limiter = AssistantRateLimiter(max_concurrent=2, min_interval_s=0.0)
    assert limiter.try_acquire("u1") is None
    assert limiter.try_acquire("u1") is None
    denied = limiter.try_acquire("u1")
    assert denied is not None
    limiter.release("u1")
    assert limiter.try_acquire("u1") is None


def test_min_interval_blocks_rapid_successive_requests():
    now = [0.0]
    limiter = AssistantRateLimiter(max_concurrent=5, min_interval_s=1.0, clock=lambda: now[0])
    assert limiter.try_acquire("u1") is None
    limiter.release("u1")
    denied = limiter.try_acquire("u1")  # 같은 시각, 최소 간격 미달
    assert denied is not None
    now[0] = 1.5
    assert limiter.try_acquire("u1") is None


def test_users_are_independent():
    limiter = AssistantRateLimiter(max_concurrent=1, min_interval_s=0.0)
    assert limiter.try_acquire("u1") is None
    assert limiter.try_acquire("u2") is None  # 다른 사용자는 별도 카운터
