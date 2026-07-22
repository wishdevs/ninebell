"""리스트 순서변경 공용 알고리즘 — 클라이언트 orderedIds 로 sort_order 재부여.

org_units(형제 조직 재정렬)와 me_codes(즐겨찾기 재정렬)에 복붙돼 있던 동일 알고리즘을 단일화.
부분/stale/중복 orderedIds 여도 전체 순열을 재구성해 중복·간극 없는 sort_order 를 보장한다.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Protocol


class _Orderable(Protocol):
    id: Any  # str PK(OrgUnit) 또는 uuid PK(UserCodeFavorite) — 비교는 str 기준.
    sort_order: int


def reorder_by_client_order(rows: Sequence[_Orderable], ordered_ids: Iterable[str]) -> None:
    """rows 의 sort_order 를 0..n-1 로 재부여(커밋은 호출자 몫).

    by_id 맵 → 클라 순서 중 실재하는 것만(중복 제거) → 목록에 빠진 나머지는 현재 순서대로
    뒤에 → enumerate 재부여. id 비교는 str 기준(uuid PK 도 wire 의 문자열 id 와 동일 취급).
    """
    by_id = {str(r.id): r for r in rows}
    ordered: list[str] = []
    for rid in ordered_ids:  # 클라가 준 순서 중 실재하는 것만, 중복 제거.
        if rid in by_id and rid not in ordered:
            ordered.append(rid)
    for r in rows:  # 목록에 빠진 나머지는 현재 순서대로 뒤에 붙인다.
        if str(r.id) not in ordered:
            ordered.append(str(r.id))
    for index, rid in enumerate(ordered):
        by_id[rid].sort_order = index
