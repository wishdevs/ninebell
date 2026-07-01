"""grid/validation 순수 로직 — off-by-one end-inclusive 정규화(핵심 노하우)."""

from __future__ import annotations

import pytest

from nbkit.grid import validation


def test_end_index_inclusive_gives_correct_last_index():
    # 20행 = getJsonRows(0, 19) — (0, 20) 이면 21행 off-by-one.
    assert validation.end_index_inclusive(0, 20) == 19
    assert validation.end_index_inclusive(0, 1) == 0
    assert validation.end_index_inclusive(5, 3) == 7


def test_end_index_inclusive_empty_range_returns_below_start():
    # count 0 → start-1 (< start) 로 빈 범위 신호.
    assert validation.end_index_inclusive(0, 0) == -1
    assert validation.end_index_inclusive(7, 0) == 6


def test_end_index_inclusive_rejects_negative():
    with pytest.raises(ValueError):
        validation.end_index_inclusive(-1, 5)
    with pytest.raises(ValueError):
        validation.end_index_inclusive(0, -3)


def test_normalize_range_basic_20_of_100():
    assert validation.normalize_range(0, 20, 100) == (0, 19, 20)


def test_normalize_range_clamps_to_total():
    # 50 요청하지만 20행뿐 → 20행으로 클램프(0..19).
    assert validation.normalize_range(0, 50, 20) == (0, 19, 20)


def test_normalize_range_count_none_takes_all_available():
    assert validation.normalize_range(0, None, 20) == (0, 19, 20)
    assert validation.normalize_range(10, None, 20) == (10, 19, 10)


def test_normalize_range_start_offset_and_partial_tail():
    assert validation.normalize_range(10, 5, 20) == (10, 14, 5)
    # start 18 에서 5 요청하지만 2행만 남음.
    assert validation.normalize_range(18, 5, 20) == (18, 19, 2)


def test_normalize_range_empty_when_start_past_total():
    start, end_inc, take = validation.normalize_range(30, 5, 20)
    assert take == 0
    assert end_inc < start  # 빈 범위


def test_clamp_count():
    assert validation.clamp_count(50, 20) == 20
    assert validation.clamp_count(10, 20) == 10
    assert validation.clamp_count(-5, 20) == 0
    assert validation.clamp_count(5, 0) == 0


def test_is_off_by_one_detects_overcollection():
    assert validation.is_off_by_one(20, 21) is True  # 전형적 +1(0025 끼어듦)
    assert validation.is_off_by_one(20, 20) is False
    assert validation.is_off_by_one(20, 19) is False


def test_validate_master_count_passes_on_exact():
    validation.validate_master_count(20, 20)  # no raise


def test_validate_master_count_flags_off_by_one():
    with pytest.raises(ValueError, match="off-by-one"):
        validation.validate_master_count(20, 21)


def test_validate_master_count_flags_shortfall():
    with pytest.raises(ValueError, match="불일치"):
        validation.validate_master_count(20, 18)
