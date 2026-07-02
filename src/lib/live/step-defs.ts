/**
 * 워크플로우 id → 순서대로의 단계 정의(한글 라벨 + 스킬/상세).
 * 백엔드 LangGraph 노드명(예: `login`, `user_type`)은 영어 식별자라 그대로 노출하면
 * 안 되므로, 라이브 단계 목록에서 라벨 번역 + 전체 단계(미도달 포함) 표시에 쓴다.
 * skill/detail 은 미실행 목업(WorkflowDetail)과 동일한 풍성함을 라이브 뷰에도 주기 위한 것.
 * 노드 구성은 backend/app/agents/expense_card/graph.py, backend/app/live/demo_echo.py 와 동기화되어야 한다.
 */

export interface WorkflowStepDef {
  /** 백엔드 LangGraph 노드 id(SSE `step` 필드와 매칭). */
  id: string;
  label: string;
  /** 이 단계가 사용하는 공용 스킬명(배지). */
  skill?: string;
  /** 보조 설명. */
  detail?: string;
}

export const WORKFLOW_STEP_DEFS: Record<string, readonly WorkflowStepDef[]> = {
  'expense-card-chat': [
    { id: 'login', label: '로그인', skill: '로그인', detail: '더존 옴니솔 인증 후 세션 확보' },
    {
      id: 'user_type',
      label: '회계 사용자 전환',
      skill: '사용자 유형 확인',
      detail: "사용자 유형을 '회계'로 전환",
    },
    {
      id: 'menu_nav',
      label: '결의서입력 화면',
      skill: '메뉴 이동',
      detail: '전사공통(회계) 결의서 입력 화면 진입',
    },
    {
      id: 'set_gubun',
      label: '결의구분: 카드',
      skill: '필드 입력',
      detail: '결의구분 드롭다운을 카드로 설정',
    },
    {
      id: 'add_row',
      label: '상세행 추가(F3)',
      skill: '필드 입력',
      detail: 'F3로 카드 결의 상세행 생성',
    },
    {
      id: 'open_evdn',
      label: '증빙유형 선택',
      skill: '코드피커',
      detail: '증빙유형 코드피커 열기',
    },
    {
      id: 'select_evdn',
      label: '법인카드 선택',
      skill: '코드피커',
      detail: '증빙유형 01 법인카드 선택',
    },
    {
      id: 'chat_form',
      label: '상세 폼 대화 입력',
      skill: '대화형 입력',
      detail: '남은 상세 필드를 자연어 대화로 채움 · 부족하면 되묻는다',
    },
  ],
  'card-collect': [
    { id: 'login', label: '로그인', skill: '로그인', detail: '더존 옴니솔 인증 후 세션 확보' },
    {
      id: 'user_type',
      label: '회계 사용자 전환',
      skill: '사용자 유형 확인',
      detail: "사용자 유형을 '회계'로 전환",
    },
    {
      id: 'menu_nav',
      label: '결의서입력 화면',
      skill: '메뉴 이동',
      detail: '전사공통(회계) 결의서 입력 화면 진입',
    },
    {
      id: 'set_gubun',
      label: '결의구분: 카드',
      skill: '필드 입력',
      detail: '결의구분 드롭다운을 카드로 설정',
    },
    {
      id: 'add_row',
      label: '상세행 추가(F3)',
      skill: '필드 입력',
      detail: 'F3로 카드 결의 상세행 생성',
    },
    {
      id: 'open_evdn',
      label: '증빙유형 선택',
      skill: '코드피커',
      detail: '증빙유형 코드피커 열기',
    },
    {
      id: 'select_evdn',
      label: '법인카드 선택',
      skill: '코드피커',
      detail: '증빙유형 01 법인카드 선택 → 승인내역 팝업',
    },
    {
      id: 'select_all_cards',
      label: '카드 전체선택',
      skill: '코드피커',
      detail: '카드번호 돋보기 → 전체선택 → 적용',
    },
    {
      id: 'set_period',
      label: '승인일 기간',
      skill: '필드 입력',
      detail: '10일 이전=전월 / 이후=당월 기간 설정',
    },
    { id: 'query', label: '조회', skill: '그리드 읽기', detail: '승인내역 조회 → 리스트 보고' },
    {
      id: 'collect_rows',
      label: '건별 입력(그리드)',
      skill: '그리드 입력',
      detail: '전 행 예산단위/프로젝트/적요 입력 → 과세분(법인카드) 먼저 반영',
    },
    {
      id: 'apply_doc',
      label: '과세분 적용',
      skill: '문서 반영',
      detail: '과세 행 체크 → 적용 → 결의서 반영(저장 전)',
    },
    {
      id: 'switch_evdn',
      label: '불공 전환',
      skill: '코드피커',
      detail: '행 추가(F3) → 증빙유형 법인카드(불공) 선택 → 재조회·행 매칭',
    },
    {
      id: 'apply_pass2',
      label: '불공분 반영·적용',
      skill: '그리드 입력',
      detail: '입력해둔 값을 불공 행에 자동 반영 후 결의서 적용(재입력 없음)',
    },
    {
      id: 'save_final',
      label: '저장(F7)',
      skill: '저장',
      detail: '과세·불공 반영분을 마지막에 한 번만 저장',
    },
  ],
  'demo-echo': [
    { id: 'open', label: '시작' },
    { id: 'greet', label: '인사' },
    { id: 'confirm', label: '확인' },
    { id: 'finish', label: '종료' },
  ],
};
