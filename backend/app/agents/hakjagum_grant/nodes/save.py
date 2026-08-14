"""최종 저장(F7) 노드 — trip_domestic save_doc 그대로 재사용(학자금 델타 없음).

저장 경로(F7 게이트·팬텀 저장 방지·재조회 지속 검증·ERP 거부 재시도)가 국내/해외출장·경조금과
동일한 GLDDOC00300 스키마라 재구현하지 않고 import 한다. 저장(F7)은 이 노드에서 filled>0 ·
confirm=True 일 때만 1회 실행한다(selectors.BTN_SAVE 직접 클릭 금지 — save_document 게이트 경유).
"""

from __future__ import annotations

from app.agents.trip_domestic.nodes.save import MAX_SAVE_RETRIES, make_save_doc_node

__all__ = ["MAX_SAVE_RETRIES", "make_save_doc_node"]
