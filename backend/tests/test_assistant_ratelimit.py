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


def test_max_per_window_caps_cumulative_requests():
    now = [0.0]
    limiter = AssistantRateLimiter(
        max_concurrent=100,
        min_interval_s=0.0,
        max_per_window=3,
        window_s=100.0,
        clock=lambda: now[0],
    )
    for _ in range(3):  # 윈도우 한도까지는 허용
        assert limiter.try_acquire("u1") is None
        limiter.release("u1")
    denied = limiter.try_acquire("u1")  # 4번째 — 윈도우 누적 한도 초과
    assert denied is not None
    now[0] = 100.0  # 윈도우 경과 → 카운터 리셋
    assert limiter.try_acquire("u1") is None


def test_idle_entry_pruned_after_window_elapses():
    now = [0.0]
    limiter = AssistantRateLimiter(min_interval_s=0.0, window_s=10.0, clock=lambda: now[0])
    assert limiter.try_acquire("u1") is None
    now[0] = 20.0
    limiter.release("u1")  # active 0 & 윈도우 경과 → 엔트리 제거(무한 증식 방지)
    assert "u1" not in limiter._by_user
