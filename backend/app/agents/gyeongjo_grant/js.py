"""detail 그리드 조작 JS 프리미티브 — trip_domestic.js 재사용(재수출).

경조금 결의서(GLDDOC00300)의 detail 그리드가 국내출장과 84필드 완전 동일(2026-07-13 프로브)이라
JS 상수를 새로 만들지 않고 trip_domestic.js 를 그대로 재노출한다(단일소스 유지 — 리스킨 시 국내
출장 한 곳만 고치면 됨). 향후 경조금 고유 JS 가 필요해지면 이 모듈에만 추가한다.
"""

from __future__ import annotations

from app.agents.trip_domestic import js as _trip_js
from app.agents.trip_domestic.js import *  # noqa: F401,F403 — detail 조작 JS 상수 전량 재수출.

__all__ = [n for n in vars(_trip_js) if n.isupper() and not n.startswith("_")]
