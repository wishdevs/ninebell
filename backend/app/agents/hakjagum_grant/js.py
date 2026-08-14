"""detail 그리드 조작 JS 프리미티브 — trip_domestic.js 재사용(재수출).

학자금 결의서(GLDDOC00300)는 경조금의 형제 클론으로 detail 그리드가 국내출장/경조금과 동형(동일
GLDDOC00300 스키마 가정, 라이브 프로브 대기)이라 JS 상수를 새로 만들지 않고 trip_domestic.js 를
그대로 재노출한다(단일소스 유지 — 리스킨 시 국내출장 한 곳만 고치면 됨). 향후 학자금 고유 JS 가
필요해지면 이 모듈에만 추가한다.
"""

from __future__ import annotations

from app.agents.trip_domestic import js as _trip_js
from app.agents.trip_domestic.js import *  # noqa: F401,F403 — detail 조작 JS 상수 전량 재수출.

__all__ = [n for n in vars(_trip_js) if n.isupper() and not n.startswith("_")]
