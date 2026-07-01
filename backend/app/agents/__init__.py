"""app.agents — 실 옴니솔 워크플로우 에이전트 패키지.

import 시 워크플로우를 엔진 레지스트리(app.live.registry)에 등록한다. main.py 가
`import app.agents` 한 줄로 등록을 트리거한다(demo-echo 는 app.live.registry 가 기본 등록).

컴파일된 LangGraph 는 stateless·재사용 가능 → 1회 컴파일 후 팩토리는 그걸 반환한다
(러너가 실행마다 새 state 를 ainvoke 로 주입).
"""

from __future__ import annotations

from app.live.registry import register_workflow

from .expense_card import build_expense_card_chat_graph

# 1회 컴파일 후 재사용(demo_echo 등록 패턴과 동일).
_expense_card_chat_graph = build_expense_card_chat_graph()
register_workflow("expense-card-chat", lambda: _expense_card_chat_graph)

__all__ = ["build_expense_card_chat_graph"]
