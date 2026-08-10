"""미지급금 법인카드(voucher-card) 에이전트 패키지 — 공유 백본 + 카드 3대 확장.

⚠ 실제 상신·참조문서 확인·저장 없음. 결제창을 열어 참조문서 선택(선택+아래버튼)까지만 하고
   '가상 상신' 로그만 남기고 닫는다(비영속). 참조문서 확인은 allow_confirm 게이트(기본 미클릭).
"""

from __future__ import annotations

from .graph import build_voucher_card_graph

__all__ = ["build_voucher_card_graph"]
