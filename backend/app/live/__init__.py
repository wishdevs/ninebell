"""라이브 세션 엔진 — 워크플로우 무관 브라우저 풀·SSE 세션·스크린캐스트.

ninebell-bak 의 헤드리스 세션/스트리밍 노하우를 단일 테넌트 대시보드용으로 이식한
워크플로우 비의존 계층. 실제 워크플로우(그래프)는 `registry.register_workflow` 로 등록한다.
"""

from __future__ import annotations
