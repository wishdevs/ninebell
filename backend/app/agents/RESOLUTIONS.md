# 결의서입력(GLDDOC00300) — 문서 종류 패밀리 인덱스

더존 옴니솔 **결의서입력** 화면은 여러 **문서 형태**를 하나의 화면에서 처리한다. 각 형태는
진입 앞단(login→회계→결의서입력)을 공유하되, 결의구분/증빙유형/후속 폼이 달라 **종류별로
구분해 저장**해야 한다. 에이전트도 종류별로 나눈다(공유 프리미티브는 nbkit/expense_card 재사용).

## 종류 목록

| 종류 | 상태 | 에이전트/문서 | 비고 |
|---|---|---|---|
| **카드** | 🟢 구축 중 | `app/agents/card_collect/` ([PROCESS.md](card_collect/PROCESS.md)) | 법인카드 승인내역 일괄 조회→정리→일괄적용→저장 |
| 출장(국내/자차) | 🟡 진행중 | `app/agents/trip_domestic/` ([PROCESS.md](trip_domestic/PROCESS.md)) | 실행 전 폼→무개입 완주(통행료/유류비 다행·F7 저장) |
| 출장(해외/정산서) | ⚪ 예정 | (미구현) | |
| 경조금신청서 | ⚪ 예정 | (미구현) | |
| 학자금신청 | ⚪ 예정 | (미구현) | |

## 참고

- 기존 `app/agents/expense_card/`(expense-card-chat)는 **카드 단건 대화형 폼 채움**(증빙유형→상세필드).
  신규 `card_collect`는 **카드 다건 리스트 정리형**(돋보기 전체선택→기간→조회→건별 입력→일괄적용→저장).
- 공유 프리미티브: `nbkit.omnisol`(js_lib/selectors), `nbkit.patterns`(login/user_type/menu),
  `expense_card.tools`(프로젝트/계정/예산단위/적요 코드피커 채움), `app.agents.common.nodes`(진입 앞단).
