"""nbkit.omnisol — 더존 OmniEsol 특화 계층(취약 셀렉터·JS·플로우의 단일 소스).

auth(로그인·사용자유형 실클릭 전환) · navigator(딥링크 메뉴 진입·공장확인) ·
profile(기본정보 추출) · selectors(CSS 셀렉터 상수) · js_lib(in-page JS 상수) ·
menu_schemas(메뉴ID↔딥링크↔상세URL↔사용자유형) · errors(도메인 예외).
"""

from __future__ import annotations
