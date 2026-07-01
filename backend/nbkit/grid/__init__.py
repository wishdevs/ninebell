"""nbkit.grid — 더존 dews/RealGrid 그리드 읽기.

provider(GridProvider: 인스턴스 접근·행 읽기·off-by-one 정규화) ·
strategies(CollectionStrategy·GridExtractor: 병렬 함수호출 vs 키보드 폴백) ·
validation(순수 범위 정규화·off-by-one 검출).
"""

from __future__ import annotations
