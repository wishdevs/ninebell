"""그리드 범위 정규화·off-by-one 검출 — **순수 로직**(브라우저 불필요, 단위테스트 대상).

★ 옴니솔 핵심 함정: ``getJsonRows(start, end)`` 는 **end-inclusive**.
  20행을 원하면 ``getJsonRows(0, 19)``. 실수로 ``(0, 20)`` 하면 21행이 되어 다음 행(0025)이
  끼어드는 off-by-one 버그가 난다(collection-strategies §핵심발견 — S1/S3/S8 실측).

이 모듈은 그 정규화를 **한 곳에** 두어 provider/strategies 가 재구현하지 않게 한다.
"""

from __future__ import annotations


def end_index_inclusive(start: int, count: int) -> int:
    """start 에서 count 개를 원할 때의 **end-inclusive** 인덱스.

    ``getJsonRows(start, end_index_inclusive(start, count))`` 가 정확히 count 행을 준다.
    count==0 이면 ``start-1``(< start) 을 돌려줘 '빈 범위'를 나타낸다(JS 쪽에서 [] 처리).
    """
    if start < 0:
        raise ValueError(f"start 는 0 이상이어야 합니다: {start}")
    if count < 0:
        raise ValueError(f"count 는 0 이상이어야 합니다: {count}")
    return start + count - 1


def clamp_count(requested: int, available: int) -> int:
    """요청 수를 [0, available] 로 클램프(ninebell ``take=min(limit,total)`` 와 동일)."""
    if requested < 0:
        return 0
    return min(requested, max(0, available))


def normalize_range(start: int, count: int | None, total: int) -> tuple[int, int, int]:
    """(start, count, total) → ``(start, end_inclusive, take)`` 정규화.

    - ``count is None`` → start 부터 끝까지(available 전부).
    - available = ``max(0, total - start)`` 로 클램프.
    - ``take==0`` → end_inclusive = start-1(빈 범위).

    이 튜플 하나로 in-page ``getJsonRows(start, end_inclusive)`` 를 안전하게 호출한다.
    """
    if start < 0:
        raise ValueError(f"start 는 0 이상이어야 합니다: {start}")
    if total < 0:
        raise ValueError(f"total 은 0 이상이어야 합니다: {total}")
    available = max(0, total - start)
    want = available if count is None else count
    take = clamp_count(want, available)
    return start, end_index_inclusive(start, take), take


def is_off_by_one(requested_count: int, returned_count: int) -> bool:
    """수집 결과가 요청보다 **더 많이** 왔는지(off-by-one 과수집 신호).

    가장 흔한 형태는 ``returned == requested + 1``(end-inclusive 오용). 여기서는 과수집
    전반(returned > requested)을 True 로 본다 — 어느 쪽이든 정규화 오류다.
    """
    return returned_count > requested_count


def validate_master_count(expected: int, actual: int) -> None:
    """수집 마스터 수가 기대와 다르면 ValueError(off-by-one 포함). 정상이면 통과.

    상위(strategies/patterns)가 이를 잡아 GridError 로 승격한다.
    """
    if actual == expected:
        return
    if is_off_by_one(expected, actual):
        raise ValueError(
            f"off-by-one 과수집: 요청 {expected}행인데 {actual}행 반환 "
            "(getJsonRows end-inclusive 오용 가능)"
        )
    raise ValueError(f"마스터 수 불일치: 기대 {expected}, 실제 {actual}")
