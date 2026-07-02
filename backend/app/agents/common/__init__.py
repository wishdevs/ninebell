"""공용 에이전트 프리미티브 — 여러 워크플로우가 공유하는 진입 스테이지·Gemini 디스패처.

- :mod:`nodes`: 결의서입력 화면 진입 앞단(login→user_type→menu_nav→set_gubun→add_row→
  open_evdn→select_evdn). expense_card·card_collect 가 함께 쓴다.
- :mod:`gemini`: 범용 Gemini function-calling 디스패처(`gemini_chat_decide`).

이전엔 expense_card 소유라 card_collect 가 형제 패키지 내부를 import 하는 역방향 결합이었다.
공용 계층으로 승격해 결합 방향을 바로잡았다(순수 이동, 동작 불변).
"""
