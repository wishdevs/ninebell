"""전자결재 상신 취소(eap-approval-cancel) 에이전트 패키지 — EAP 취소 아키타입.

⚠ 비가역: 사용자가 체크한 문서를 결재취소 → 상신취소 → 삭제까지 처리한다(문서가 사라진다).
   상신·저장(F7)·보관은 클릭하지 않는다. hidden 워크플로우(관리자 + 디버그 모드 전용).
"""

from __future__ import annotations

from .graph import build_eap_cancel_graph

__all__ = ["build_eap_cancel_graph"]
