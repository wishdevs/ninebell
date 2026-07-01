/**
 * 에이전트 상세 플로우 그래프(분기·루프 포함) — React Flow로 렌더된다.
 *
 * 선형 스텝(steps[])과 달리 의사결정 분기와 되돌이(루프)를 노드/엣지로 표현한다.
 * 레이아웃은 간략보기처럼 **가로(좌→우)** 스파인이며, 루프(증빙유형 재선택)는
 * 스파인 위로, 스킵 분기(한 종류일 때 분리등록 건너뜀)는 스파인 아래로 아치를 그린다.
 * 노드 종류(kind)는 색을, 진행 상태(status)는 강조/흐림을 좌우한다.
 */

export type FlowNodeKind = 'start' | 'step' | 'decision' | 'end';
export type FlowNodeStatus = 'done' | 'active' | 'pending' | 'error';

export interface FlowGraphNode {
  id: string;
  kind: FlowNodeKind;
  status: FlowNodeStatus;
  title: string;
  /** 두 번째 줄 보조 설명. */
  sub?: string;
  x: number;
  y: number;
}

export type FlowEdgeKind = 'normal' | 'branch' | 'loop' | 'skip';

export interface FlowGraphEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
  kind?: FlowEdgeKind;
}

export interface FlowGraph {
  nodes: readonly FlowGraphNode[];
  edges: readonly FlowGraphEdge[];
}

// 가로 스파인: 한 줄로 좌→우 배치. 루프는 위쪽, 스킵은 아래쪽 여백으로 아치.
const STEP_X = 212;
const BASE_Y = 160;
const col = (i: number): { x: number; y: number } => ({ x: i * STEP_X, y: BASE_Y });

/**
 * 법인카드 지출결의 플로우.
 * - 맨 앞에 로그인 → 회계 사용자 전환을 두고, 이어서 결의서 입력 접속부터 상신까지 진행.
 * - 부가세 간이/빈칸이면 증빙유형(02)으로 되돌아가는 루프.
 * - 매입·불공이 동시면 **매입(01) 행 입력 → F3 줄 추가 → 불공(02) 행 입력**으로
 *   두 증빙유형을 별도 행으로 나눠 등록한다(한 종류면 분리 단계를 건너뜀).
 *
 * status 는 전부 pending(중립) — 미실행에는 활성/완료 표시가 없고, 라이브 실행 시
 * agent-progress 가 run.steps 를 노드 title 매칭으로 오버레이한다.
 */
export const CORPORATE_CARD_FLOW: FlowGraph = {
  nodes: [
    {
      id: 'login',
      kind: 'start',
      status: 'pending',
      title: '로그인',
      sub: '옴니솔 인증',
      ...col(0),
    },
    {
      id: 'usertype',
      kind: 'step',
      status: 'pending',
      title: '회계 사용자 전환',
      sub: "유형 '회계'",
      ...col(1),
    },
    {
      id: 'access',
      kind: 'step',
      status: 'pending',
      title: '결의서 입력 접속',
      sub: '전사공통(회계)',
      ...col(2),
    },
    {
      id: 'kind',
      kind: 'step',
      status: 'pending',
      title: '결의구분 = 카드',
      sub: '추가(F3)',
      ...col(3),
    },
    {
      id: 'date',
      kind: 'step',
      status: 'pending',
      title: '회계일자 세팅',
      sub: '카드 사용 월',
      ...col(4),
    },
    {
      id: 'ev',
      kind: 'step',
      status: 'pending',
      title: '증빙유형 선택',
      sub: '01 매입 / 02 불공',
      ...col(5),
    },
    {
      id: 'card',
      kind: 'step',
      status: 'pending',
      title: '카드내역 조회·적용',
      sub: '승인일→조회→적용',
      ...col(6),
    },
    {
      id: 'vat',
      kind: 'decision',
      status: 'pending',
      title: '부가세 구분',
      sub: '간이·빈칸이면 02',
      ...col(7),
    },
    {
      id: 'both',
      kind: 'decision',
      status: 'pending',
      title: '매입·불공 동시?',
      sub: '둘 다면 행 분리 등록',
      ...col(8),
    },
    {
      id: 'rowMae',
      kind: 'step',
      status: 'pending',
      title: '매입 행 입력',
      sub: '증빙유형 01 매입',
      ...col(9),
    },
    {
      id: 'rowAdd',
      kind: 'step',
      status: 'pending',
      title: 'F3 줄 추가',
      sub: '불공용 행 추가',
      ...col(10),
    },
    {
      id: 'rowBul',
      kind: 'step',
      status: 'pending',
      title: '불공 행 입력',
      sub: '증빙유형 02 불공',
      ...col(11),
    },
    {
      id: 'budget',
      kind: 'step',
      status: 'pending',
      title: '예산계정 매핑',
      sub: '항목별 계정 선택',
      ...col(12),
    },
    {
      id: 'project',
      kind: 'step',
      status: 'pending',
      title: '프로젝트·일괄적용',
      sub: '취소 내역 포함',
      ...col(13),
    },
    {
      id: 'memo',
      kind: 'step',
      status: 'pending',
      title: '적요 작성',
      sub: '자금예정일 매핑',
      ...col(14),
    },
    {
      id: 'save',
      kind: 'step',
      status: 'pending',
      title: '저장(F7)',
      sub: '결의번호 생성',
      ...col(15),
    },
    {
      id: 'warn',
      kind: 'decision',
      status: 'pending',
      title: '저장 시 경고?',
      sub: '회계일자 확인',
      ...col(16),
    },
    {
      id: 'submit',
      kind: 'end',
      status: 'pending',
      title: '전자결재 상신',
      sub: '회계팀 + 증빙',
      ...col(17),
    },
  ],
  edges: [
    // 맨 앞: 로그인 → 회계 사용자 전환 → 결의서 입력 접속
    { id: 'e-login-usertype', source: 'login', target: 'usertype' },
    { id: 'e-usertype-access', source: 'usertype', target: 'access' },
    { id: 'e-access-kind', source: 'access', target: 'kind' },
    { id: 'e-kind-date', source: 'kind', target: 'date' },
    { id: 'e-date-ev', source: 'date', target: 'ev' },
    { id: 'e-ev-card', source: 'ev', target: 'card' },
    { id: 'e-card-vat', source: 'card', target: 'vat' },
    { id: 'e-vat-both', source: 'vat', target: 'both', label: '아니오 · 과세', kind: 'branch' },
    { id: 'e-vat-ev', source: 'vat', target: 'ev', label: '예 ↩ 02', kind: 'loop' },
    // 매입·불공 동시(예): 매입 행 → F3 줄 추가 → 불공 행으로 분리 등록
    { id: 'e-both-mae', source: 'both', target: 'rowMae', label: '예 · 둘 다', kind: 'branch' },
    { id: 'e-mae-add', source: 'rowMae', target: 'rowAdd' },
    { id: 'e-add-bul', source: 'rowAdd', target: 'rowBul' },
    { id: 'e-bul-budget', source: 'rowBul', target: 'budget' },
    // 한 종류(아니오): 분리 등록 단계를 건너뜀(스파인 아래로 스킵)
    {
      id: 'e-both-budget',
      source: 'both',
      target: 'budget',
      label: '아니오 · 한 종류',
      kind: 'skip',
    },
    { id: 'e-budget-project', source: 'budget', target: 'project' },
    { id: 'e-project-memo', source: 'project', target: 'memo' },
    { id: 'e-memo-save', source: 'memo', target: 'save' },
    { id: 'e-save-warn', source: 'save', target: 'warn' },
    { id: 'e-warn-submit', source: 'warn', target: 'submit', label: '확인 후', kind: 'branch' },
  ],
};
