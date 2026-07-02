"""Gemini function-calling 도구 스키마 — 법인카드 승인내역 항목 처리(대화형).

expense_card.tools.CHAT_TOOLS 와 같은 스타일(app.agents.expense_card.gemini.gemini_chat_decide
가 어느 에이전트든 재사용하도록 tools 를 파라미터로 받게 일반화됨 — 여기서 그 도구 목록만 정의).
행 번호는 사용자에게 보여준 전체 리스트 표의 # 컬럼(1-based)이다.
"""

from __future__ import annotations

CARD_COLLECT_TOOLS: list[dict] = [
    {
        "name": "apply_fields",
        "description": (
            "지정한 승인내역 행(row_numbers, 표의 # 번호 1-based)에 예산단위·프로젝트(필수)를 적용한다. "
            "계정은 보통 예산단위로 자동 결정되므로 사용자가 명시하지 않으면 비워 두면 자동 처리된다. "
            "적요를 함께 말했으면 note 에 담고, 안 그러면 비워 두면 추천 적요가 유지된다. "
            "여러 행에 같은 값을 한 번에 적용하려면 row_numbers 배열에 여러 번호를 담는다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "row_numbers": {"type": "array", "items": {"type": "integer"}},
                "budget_unit": {"type": "string"},
                "account": {"type": "string"},
                "project": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["row_numbers", "budget_unit", "project"],
        },
    },
    {
        "name": "update_note",
        "description": "지정 행의 적요만 바꾼다(예산단위/계정/프로젝트는 건드리지 않음).",
        "parameters": {
            "type": "object",
            "properties": {
                "row_numbers": {"type": "array", "items": {"type": "integer"}},
                "note": {"type": "string"},
            },
            "required": ["row_numbers", "note"],
        },
    },
    {
        "name": "skip_rows",
        "description": "지정 행을 처리 대상에서 제외한다(건너뛰기).",
        "parameters": {
            "type": "object",
            "properties": {"row_numbers": {"type": "array", "items": {"type": "integer"}}},
            "required": ["row_numbers"],
        },
    },
    {
        "name": "show_status",
        "description": "현재까지의 처리 현황 표를 다시 보여준다(사용자가 '표/현황 다시 보여줘' 등으로 요청할 때).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "ask",
        "description": "정보가 부족하거나 모호할 때(예: 존재하지 않는 행 번호) 사용자에게 되묻는다. question=물어볼 한 문장.",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
    {
        "name": "turn_done",
        "description": (
            "이번 사용자 메시지의 지시를 모두 처리했을 때 호출한다(대화를 끝내는 게 아님). "
            "message=사용자에게 할 짧은 안내. 종료(저장 단계로 진행)는 오직 사용자가 화면의 '선택 완료' "
            "버튼으로만 한다 — 이 도구를 이 목적으로 쓰지 않는다."
        ),
        "parameters": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    },
]
