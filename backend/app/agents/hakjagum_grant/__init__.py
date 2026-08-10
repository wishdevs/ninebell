"""학자금신청서 결의서입력(hakjagum-grant) — 경조금(gyeongjo_grant) 형제 클론(단건·본인 거래처).

결의서입력(GLDDOC00300) 문서 종류 중 학자금신청서. 경조금과 기본틀 동일(detail 그리드 동형 가정,
라이브 프로브 대기)이라 steps/js/save/state 는 trip_domestic 을 재사용하고, 학자금 고유 델타
(단건 스키마·결의구분 라벨 '학자금신청서'·예산계정 '복리후생비-기타'·적요 '학자금-{본인}'·
공급가액=사용자 입력 금액 그대로 — 근속<1년 50% 규칙 없음)만 신규다. 정식 명세: PROCESS.md.
"""

from __future__ import annotations
