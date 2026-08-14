"""지연 배율 모듈(nbkit.omnisol.latency) 계약 — 프로세스 전역 EMA·클램프·예산.

고정하는 계약:
  1. 초기/리셋 상태 factor=1.0 — 평시(빠른 관측)에는 어떤 상한도 확대하지 않는다.
  2. record 는 비율(actual/expected)을 EMA(α=0.3)로 누적 — 느린 관측이면 상승,
     빠른 관측(비율 하한 1.0)이면 1.0 으로 감쇠한다(자기되먹임).
  3. factor 는 [1.0, 4.0] 클램프 — 하한(현재보다 빨라지지 않음)·상한(폭주 방지).
  4. budget_ms/budget_polls = base × factor — 상한/회수에만 곱한다(폴 간격 불변은 호출부 계약).
  5. 관측성 — factor 가 1.5 를 넘으면 0.5 버킷 전이마다 1회만 경고(스팸 방지).
"""

from __future__ import annotations

import logging

import pytest

from nbkit.omnisol import latency

# conftest 의 autouse _reset_latency 가 매 테스트 factor=1.0 에서 시작을 보장한다.


def test_initial_factor_is_one_and_budget_identity():
    assert latency.factor() == 1.0
    assert latency.budget_ms(4_500) == 4_500  # 평시 상한 불변.
    assert latency.budget_polls(33) == 33  # 평시 회수 불변.


def test_slow_observations_raise_factor_by_ema():
    latency.record(1_000, 4_000)  # 비율 4.0 → EMA = 1 + 0.3×(4−1) = 1.9
    assert latency.factor() == pytest.approx(1.9)
    latency.record(1_000, 4_000)  # EMA = 1.9 + 0.3×(4−1.9) = 2.53
    assert latency.factor() == pytest.approx(2.53)


def test_fast_observations_decay_factor_toward_one():
    for _ in range(5):
        latency.record(1_000, 4_000)
    high = latency.factor()
    assert high > 2.0
    for _ in range(50):
        latency.record(1_000, 100)  # 비율 하한 1.0(빠름 신호) → 감쇠.
    assert latency.factor() < high
    assert latency.factor() == pytest.approx(1.0, abs=0.01)


def test_ratio_below_one_is_floored_never_speeds_up():
    latency.record(1_000, 10)  # 아무리 빨라도 배율은 1.0 밑으로 안 내려간다.
    assert latency.factor() == 1.0
    assert latency.budget_ms(900) == 900


def test_factor_clamped_at_ceiling_even_for_extreme_outliers():
    for _ in range(100):
        latency.record(100, 1_000_000)  # 단발 이상치도 관측 자체가 CEIL 로 클램프.
    assert latency.factor() == pytest.approx(4.0, abs=0.01)
    assert latency.factor() <= latency.CEIL
    # 이상치 이후에도 빠른 관측이면 즉시 감쇠 반응한다(EMA 가 CEIL 밖으로 안 나갔으므로).
    latency.record(1_000, 100)
    assert latency.factor() < 4.0


def test_budget_scales_with_factor():
    for _ in range(100):
        latency.record(1_000, 2_000)  # 비율 2.0 수렴.
    f = latency.factor()
    assert f == pytest.approx(2.0, abs=0.01)
    assert latency.budget_ms(4_500) == int(4_500 * f)
    assert latency.budget_polls(33) == int(33 * f)
    assert latency.budget_polls(33) >= 33  # 회수 상한은 절대 줄지 않는다.


def test_invalid_observations_are_ignored():
    latency.record(0, 1_000)  # expected<=0 무시.
    latency.record(-1, 1_000)
    latency.record(1_000, -1)  # actual<0 무시.
    assert latency.factor() == 1.0


def test_reset_restores_initial_state():
    latency.record(100, 10_000)
    assert latency.factor() > 1.0
    latency.reset()
    assert latency.factor() == 1.0


def test_warns_once_per_half_step_bucket(caplog):
    with caplog.at_level(logging.WARNING, logger="nbkit.omnisol.latency"):
        latency.record(1_000, 2_000)  # EMA 1.3 — 1.5 이하, 경고 없음.
        assert not caplog.records
        latency.record(1_000, 2_000)  # EMA 1.51 — 1.5 초과 첫 전이 → 경고 1회.
        assert len(caplog.records) == 1
        assert "대기 상한" in caplog.records[0].message
        latency.record(1_000, 2_000)  # EMA ~1.657 — 같은 0.5 버킷 → 추가 경고 없음.
        assert len(caplog.records) == 1
        for _ in range(3):
            latency.record(1_000, 4_000)  # 버킷 상승 전이 → 새 경고.
        assert len(caplog.records) >= 2
