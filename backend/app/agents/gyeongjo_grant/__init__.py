"""경조금신청서 결의서입력(gyeongjo-grant) — trip_domestic 포팅(단건·본인 거래처).

결의서입력(GLDDOC00300) 문서 종류 중 경조금신청서. detail 그리드가 국내출장과 84필드 완전
동일(2026-07-13 프로브)이라 steps/js/save/state 는 trip_domestic 을 재사용하고, 경조금 고유
델타(단건 스키마·근속<1년 50% 공급가액·결의구분 55·예산계정 '복리후생비-경조'·적요 '경조금-{본인}')
만 신규다. 정식 명세: PROCESS.md.
"""

from __future__ import annotations
