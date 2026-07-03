/**
 * 에이전트 픽스처 — 나인벨 AX의 핵심 단위.
 *
 * 에이전트는 더존 ERP(옴니솔)의 반복 업무를 사람이 화면을 보며 승인하는 가운데
 * 실제 화면을 조작해 끝까지 처리한다. 상세(구동) 화면은 라이브 브라우저 +
 * 단계 진행(워크플로우) + 사람 개입(선택/대화)으로 구성된다.
 *
 * 구동 방식은 2~3종(브라우저 조작 · API 호출 · 하이브리드)을 상정하지만,
 * 현재는 "브라우저 조작(더존 옴니솔)"만 구현한다.
 *
 * 실행 모델: 에이전트는 백그라운드 워커/큐로 돌리지 않고, **타임아웃을 가진
 * 실시간 세션**으로 처리한다. 각 세션이 헤드리스 브라우저(메모리 다소비)를
 * 점유하므로 동시 실행 수가 제한된다(자원 보존). UI는 이 모델을 그대로 반영해
 * "라이브 세션 · 남은 시간(타임아웃)"과 "동시 세션 한도"를 노출한다.
 */

import { relativeFromNow } from './format';

/** 동시에 떠 있을 수 있는 라이브(헤드리스 브라우저) 세션 한도. */
export const CONCURRENCY_LIMIT = 4;

/** 구동 방식 — 현재는 browser만 구현. */
export type AgentDrive = 'browser' | 'api' | 'hybrid';

export const AGENT_DRIVE_LABEL: Record<AgentDrive, string> = {
  browser: '브라우저 조작',
  api: 'API 호출',
  hybrid: '하이브리드',
};

/** 의사결정 성격 — 화면 우측 개입 형태를 좌우한다. */
export type AgentInteraction = 'readonly' | 'approval' | 'conversational' | 'autonomous';

export const AGENT_INTERACTION_LABEL: Record<AgentInteraction, string> = {
  readonly: '읽기 전용',
  approval: '사람 승인',
  conversational: '대화형',
  autonomous: 'AI 자율',
};

/** 실행 상태. */
export type AgentStatus = 'running' | 'waiting_input' | 'paused' | 'completed' | 'failed' | 'idle';

export const AGENT_STATUS_LABEL: Record<AgentStatus, string> = {
  running: '실행 중',
  waiting_input: '개입 대기',
  paused: '일시정지',
  completed: '완료',
  failed: '실패',
  idle: '대기',
};

export type AgentStatusTone = 'info' | 'warning' | 'muted' | 'success' | 'danger';

export const AGENT_STATUS_TONE: Record<AgentStatus, AgentStatusTone> = {
  running: 'info',
  waiting_input: 'warning',
  paused: 'muted',
  completed: 'success',
  failed: 'danger',
  idle: 'muted',
};

// ── 워크플로우 단계 ──────────────────────────────────────────────────

export type StepStatus = 'done' | 'active' | 'pending' | 'error';

export interface SubStep {
  label: string;
  status: StepStatus;
}

export interface WorkflowStep {
  id: string;
  /** 상단 React Flow 노드에 표기될 짧은 라벨. */
  label: string;
  /** 이 단계가 사용하는 공용 스킬명. */
  skill?: string;
  status: StepStatus;
  /** 우측 상세 워크플로우 탭에 노출될 보조 설명/하위 단계. */
  detail?: string;
  substeps?: readonly SubStep[];
  /** true 면 이 단계에서 사용자 개입(HITL)이 필요하다 — '개입 필요' 표시. */
  intervention?: boolean;
}

// ── 로그 ─────────────────────────────────────────────────────────────

export type LogLevel = 'info' | 'action' | 'success' | 'warn' | 'error';

export const LOG_LEVEL_LABEL: Record<LogLevel, string> = {
  info: 'INFO',
  action: 'ACT',
  success: 'OK',
  warn: 'WARN',
  error: 'ERR',
};

export interface LogEntry {
  id: string;
  at: string;
  level: LogLevel;
  /** 어느 단계에서 발생했는지(라벨). */
  step?: string;
  message: string;
}

// ── 사람 개입 (HITL) ─────────────────────────────────────────────────

export interface ChoiceOption {
  id: string;
  label: string;
  hint?: string;
}

export interface ChatMessage {
  id: string;
  role: 'agent' | 'user';
  text: string;
  at: string;
}

export type InterventionKind = 'choice' | 'chat';

export interface Intervention {
  kind: InterventionKind;
  title: string;
  prompt: string;
  /** kind === 'choice' */
  options?: readonly ChoiceOption[];
  /** kind === 'chat' */
  messages?: readonly ChatMessage[];
  placeholder?: string;
}

// ── 에이전트 ─────────────────────────────────────────────────────────

export interface Agent {
  id: string;
  /**
   * 엔진에 등록된 실행 워크플로우 id(서버 agents.workflow_id). 실행 게이트의 단일 소스 —
   * 지정된 에이전트만 라이브 실행 가능하고, 없으면 실행 컨트롤이 비활성화된다.
   */
  workflowId?: string;
  name: string;
  description: string;
  drive: AgentDrive;
  interaction: AgentInteraction;
  /** 대상 시스템 — 현재는 더존 옴니솔. */
  targetSystem: string;
  /** 브라우저 라이브 화면 주소(표시용). */
  targetUrl: string;
  status: AgentStatus;
  /** 0..100 전체 진행률. */
  progress: number;
  /** 실시간 세션 타임아웃(초). 이 시간을 넘기면 세션을 강제 종료한다. */
  timeoutSeconds: number;
  /** 현재 세션 경과(초). 실행/대기 중이면 진행분, 완료면 총 소요. 대기(idle)는 0. */
  elapsedSeconds: number;
  /** 브라우저에서 지금 수행 중인 동작 캡션. */
  currentAction: string;
  runCount: number;
  successRate: number;
  avgSeconds: number;
  lastRunAt: string;
  steps: readonly WorkflowStep[];
  logs: readonly LogEntry[];
  intervention?: Intervention | null;
}

// 공통 단계 라벨(공용 스킬 기반)
const baseSteps = (
  overrides: Record<string, { status: StepStatus; substeps?: readonly SubStep[] }>,
  tail: readonly WorkflowStep[] = [],
): readonly WorkflowStep[] => {
  const defs: WorkflowStep[] = [
    {
      id: 'login',
      label: '로그인',
      skill: '로그인',
      status: 'pending',
      detail: '더존 옴니솔 인증 후 세션 확보',
    },
    {
      id: 'usertype',
      label: '유형 확인',
      skill: '사용자 유형 확인',
      status: 'pending',
      detail: '법인/사업장·권한 유형 식별',
    },
    {
      id: 'menu',
      label: '메뉴 이동',
      skill: '메뉴 이동',
      status: 'pending',
      detail: '대상 업무 화면으로 이동',
    },
  ];
  return [...defs.map((s) => ({ ...s, ...(overrides[s.id] ?? {}) })), ...tail];
};

export const AGENTS: readonly Agent[] = [
  {
    id: 'outbound-test',
    name: '출고 데이터 테스트',
    description:
      '로그인 → 메뉴 이동 → 조회 → 그리드 데이터 수집까지 자동 수행하는 읽기 전용 에이전트.',
    drive: 'browser',
    interaction: 'readonly',
    targetSystem: '더존 옴니솔',
    targetUrl: 'erp.ninebell.co.kr',
    status: 'running',
    progress: 58,
    timeoutSeconds: 120,
    elapsedSeconds: 47,
    currentAction: '출고현황 그리드에서 84행을 읽는 중…',
    runCount: 132,
    successRate: 99.2,
    avgSeconds: 41,
    lastRunAt: relativeFromNow({ minutes: 3 }),
    steps: baseSteps(
      {
        login: { status: 'done' },
        usertype: { status: 'done' },
        menu: { status: 'done' },
      },
      [
        {
          id: 'query',
          label: '조회',
          skill: '그리드 읽기',
          status: 'active',
          detail: '기간·창고 조건으로 출고현황 조회',
          substeps: [
            { label: '조회 조건 입력(기간/창고)', status: 'done' },
            { label: '조회 버튼 실행', status: 'done' },
            { label: '그리드 로딩 대기', status: 'active' },
          ],
        },
        {
          id: 'collect',
          label: '데이터 수집',
          skill: '그리드 읽기',
          status: 'pending',
          detail: '그리드 행을 구조화 데이터로 추출',
        },
        {
          id: 'apply',
          label: '결과 정리',
          status: 'pending',
          detail: '수집 결과를 실행 이력에 기록',
        },
      ],
    ),
    logs: [
      {
        id: 'l1',
        at: relativeFromNow({ minutes: 3 }),
        level: 'info',
        step: '로그인',
        message: '더존 옴니솔 세션 시작',
      },
      {
        id: 'l2',
        at: relativeFromNow({ minutes: 3 }),
        level: 'success',
        step: '로그인',
        message: '인증 성공 · 사용자 유형=법인',
      },
      {
        id: 'l3',
        at: relativeFromNow({ minutes: 2 }),
        level: 'action',
        step: '메뉴 이동',
        message: '자재 > 출고현황 화면으로 이동',
      },
      {
        id: 'l4',
        at: relativeFromNow({ minutes: 2 }),
        level: 'action',
        step: '조회',
        message: "조회 조건 입력: 기간=2026-06, 창고='본사'",
      },
      {
        id: 'l5',
        at: relativeFromNow({ minutes: 1 }),
        level: 'info',
        step: '조회',
        message: '그리드 로딩 대기 중(84행 예상)',
      },
    ],
    intervention: null,
  },
  {
    id: 'card-expense',
    name: '법인카드 지출결의',
    description:
      '결의서 입력 화면에서 카드 결의 행을 만들고 증빙유형·프로젝트를 사람 승인으로 선택한다.',
    drive: 'browser',
    interaction: 'approval',
    targetSystem: '더존 옴니솔',
    targetUrl: 'erp.ninebell.co.kr',
    status: 'waiting_input',
    progress: 46,
    timeoutSeconds: 180,
    elapsedSeconds: 72,
    currentAction: '증빙유형 선택을 기다리는 중 — 사용자 승인 필요',
    runCount: 57,
    successRate: 96.5,
    avgSeconds: 88,
    lastRunAt: relativeFromNow({ minutes: 12 }),
    steps: baseSteps(
      {
        login: { status: 'done' },
        usertype: { status: 'done' },
        menu: { status: 'done' },
      },
      [
        {
          id: 'row',
          label: '결의행 생성',
          skill: '필드 입력',
          status: 'done',
          detail: '법인카드 승인내역에서 결의 대상 행 생성',
        },
        {
          id: 'evidence',
          label: '증빙유형',
          skill: '코드피커',
          status: 'active',
          detail: '증빙유형 선택 — 사람 승인 지점',
          substeps: [
            { label: '코드피커 열기', status: 'done' },
            { label: '증빙유형 후보 제시', status: 'done' },
            { label: '사용자 승인 대기', status: 'active' },
          ],
        },
        {
          id: 'project',
          label: '프로젝트',
          skill: '코드피커',
          status: 'pending',
          detail: '프로젝트(검색형) 선택',
        },
        {
          id: 'apply',
          label: '적용',
          status: 'pending',
          detail: '입력값 적용(저장·상신은 사람이)',
        },
      ],
    ),
    logs: [
      {
        id: 'l1',
        at: relativeFromNow({ minutes: 12 }),
        level: 'success',
        step: '로그인',
        message: '인증 성공',
      },
      {
        id: 'l2',
        at: relativeFromNow({ minutes: 11 }),
        level: 'action',
        step: '메뉴 이동',
        message: '회계 > 지출결의 입력 화면 이동',
      },
      {
        id: 'l3',
        at: relativeFromNow({ minutes: 10 }),
        level: 'action',
        step: '결의행 생성',
        message: '법인카드 승인내역 3건 중 1건 결의행 생성',
      },
      {
        id: 'l4',
        at: relativeFromNow({ minutes: 9 }),
        level: 'info',
        step: '증빙유형',
        message: '코드피커 열기 · 후보 4종 제시',
      },
      {
        id: 'l5',
        at: relativeFromNow({ minutes: 9 }),
        level: 'warn',
        step: '증빙유형',
        message: '판단 필요 — 사용자 승인 대기',
      },
    ],
    intervention: {
      kind: 'choice',
      title: '증빙유형 선택',
      prompt:
        '이 카드 결의 행에 적용할 증빙유형을 선택하세요. 선택 후 프로젝트 지정으로 이어집니다.',
      options: [
        { id: 'ev-normal', label: '일반경비', hint: '대부분의 카드 지출' },
        { id: 'ev-entertain', label: '접대비', hint: '거래처 접대·경조사' },
        { id: 'ev-welfare', label: '복리후생비', hint: '임직원 복리후생' },
        { id: 'ev-education', label: '교육훈련비', hint: '교육·세미나·도서' },
      ],
    },
  },
  {
    id: 'card-chat',
    name: '법인카드 승인내역 정리 — 대화형',
    description:
      '법인카드 승인내역을 일괄 조회해 건별로 예산단위·계정·프로젝트·적요를 대화로 채운다(적요 추천). 저장은 확인 후.',
    drive: 'browser',
    interaction: 'conversational',
    targetSystem: '더존 옴니솔',
    targetUrl: 'erp.ninebell.co.kr',
    status: 'waiting_input',
    progress: 72,
    timeoutSeconds: 240,
    elapsedSeconds: 151,
    currentAction: '상세 필드 입력을 위한 대화 입력을 기다리는 중',
    runCount: 23,
    successRate: 89.1,
    avgSeconds: 124,
    lastRunAt: relativeFromNow({ minutes: 6 }),
    // steps = 실제 워크플로우(card-collect) 15개 노드 순서(backend graph.py 와 1:1). 미실행 시
    // 상단 스텝퍼가 이 목록을 중립으로 노출하고, 라이브 실행 시 run.steps 가 진행상태를 오버레이한다.
    steps: [
      {
        id: 'login',
        label: '로그인',
        skill: '로그인',
        status: 'pending',
        detail: '더존 옴니솔 인증 후 세션 확보',
      },
      {
        id: 'usertype',
        label: '회계 사용자 전환',
        skill: '사용자 유형 확인',
        status: 'pending',
        detail: "사용자 유형을 '회계'로 전환",
      },
      {
        id: 'menu',
        label: '결의서입력 화면',
        skill: '메뉴 이동',
        status: 'pending',
        detail: '전사공통(회계) 결의서 입력 화면 진입',
      },
      {
        id: 'gubun',
        label: '결의구분: 카드',
        skill: '필드 입력',
        status: 'pending',
        detail: '결의구분 드롭다운을 카드로 설정',
      },
      {
        id: 'addrow',
        label: '상세행 추가(F3)',
        skill: '필드 입력',
        status: 'pending',
        detail: 'F3로 카드 결의 상세행 생성',
      },
      {
        id: 'evdn',
        label: '증빙유형 선택',
        skill: '코드피커',
        status: 'pending',
        detail: '증빙유형 코드피커 열기',
      },
      {
        id: 'card',
        label: '법인카드 선택',
        skill: '코드피커',
        status: 'pending',
        detail: '증빙유형 01 법인카드 선택 → 승인내역 팝업',
      },
      {
        id: 'selectcards',
        label: '카드 전체선택',
        skill: '코드피커',
        status: 'pending',
        detail: '카드번호 돋보기 → 전체선택 → 적용',
      },
      {
        id: 'period',
        label: '승인일 기간',
        skill: '필드 입력',
        status: 'pending',
        detail: '10일 이전=전월 / 이후=당월 기간 설정',
      },
      {
        id: 'query',
        label: '조회',
        skill: '그리드 읽기',
        status: 'pending',
        detail: '승인내역 조회 → 리스트 보고',
      },
      {
        id: 'collect_rows',
        label: '건별 입력(그리드)',
        skill: '그리드 입력',
        status: 'pending',
        intervention: true,
        detail: "전 행 예산단위·프로젝트·적요를 입력하고 '입력 완료'로 제출(사용자 개입)",
      },
      {
        id: 'apply_doc',
        label: '과세분 적용',
        skill: '문서 반영',
        status: 'pending',
        detail: '과세 행 체크 → 적용 → 결의서 반영(저장 전)',
      },
      {
        id: 'switch_evdn',
        label: '불공 전환',
        skill: '코드피커',
        status: 'pending',
        detail: '행 추가(F3) → 증빙유형 법인카드(불공) 선택 → 재조회·행 매칭',
      },
      {
        id: 'apply_pass2',
        label: '불공분 반영·적용',
        skill: '그리드 입력',
        status: 'pending',
        detail: '입력해둔 값을 불공 행에 자동 반영 후 결의서 적용',
      },
      {
        id: 'save_final',
        label: '저장(F7)',
        skill: '저장',
        status: 'pending',
        detail: '과세·불공 반영분을 마지막에 한 번만 저장',
      },
    ],
    logs: [
      {
        id: 'l1',
        at: relativeFromNow({ minutes: 6 }),
        level: 'success',
        step: '증빙유형',
        message: '증빙유형 적용: 일반경비',
      },
      {
        id: 'l2',
        at: relativeFromNow({ minutes: 5 }),
        level: 'success',
        step: '프로젝트',
        message: '프로젝트 적용: 커머스 리뉴얼',
      },
      {
        id: 'l3',
        at: relativeFromNow({ minutes: 4 }),
        level: 'action',
        step: '상세 필드',
        message: '필수 필드 식별: 적요, 사용부서, 금액',
      },
      {
        id: 'l4',
        at: relativeFromNow({ minutes: 3 }),
        level: 'info',
        step: '상세 필드',
        message: '대화형 입력 대기 — 한 문장으로 입력 요청',
      },
    ],
    intervention: {
      kind: 'chat',
      title: '상세 필드 — 대화형 입력',
      prompt:
        '남은 상세 필드를 한 문장으로 입력하면 에이전트가 알아서 채웁니다. 부족하면 되묻습니다.',
      placeholder: '예) 적요는 6월 팀 회식, 사용부서는 마케팅, 금액 184,000원',
      messages: [
        {
          id: 'm1',
          role: 'agent',
          at: relativeFromNow({ minutes: 4 }),
          text: '상세 필드를 채울게요. 적요·사용부서·금액을 한 문장으로 알려주세요.',
        },
        {
          id: 'm2',
          role: 'user',
          at: relativeFromNow({ minutes: 3 }),
          text: '적요는 6월 거래처 미팅 식대로 해줘',
        },
        {
          id: 'm3',
          role: 'agent',
          at: relativeFromNow({ minutes: 3 }),
          text: '적요=‘6월 거래처 미팅 식대’로 입력했어요. 사용부서와 금액도 알려주시겠어요?',
        },
      ],
    },
  },
  {
    id: 'card-md',
    name: '법인카드 지출결의 MD',
    description: '같은 업무를 매 단계 화면을 읽고 AI가 스스로 판단해 수행한다(비교·실험용).',
    drive: 'browser',
    interaction: 'autonomous',
    targetSystem: '더존 옴니솔',
    targetUrl: 'erp.ninebell.co.kr',
    status: 'completed',
    progress: 100,
    timeoutSeconds: 240,
    elapsedSeconds: 167,
    currentAction: '적용 완료 — 최종 저장·상신은 사용자 확인 대기',
    runCount: 11,
    successRate: 81.8,
    avgSeconds: 167,
    lastRunAt: relativeFromNow({ hours: 2 }),
    steps: baseSteps(
      {
        login: { status: 'done' },
        usertype: { status: 'done' },
        menu: { status: 'done' },
      },
      [
        { id: 'row', label: '결의행 생성', skill: '필드 입력', status: 'done' },
        { id: 'evidence', label: '증빙유형', skill: '코드피커', status: 'done' },
        { id: 'project', label: '프로젝트', skill: '코드피커', status: 'done' },
        { id: 'apply', label: '적용', status: 'done', detail: '입력값 적용 완료' },
      ],
    ),
    logs: [
      {
        id: 'l1',
        at: relativeFromNow({ hours: 2, minutes: 4 }),
        level: 'success',
        step: '로그인',
        message: '인증 성공',
      },
      {
        id: 'l2',
        at: relativeFromNow({ hours: 2, minutes: 2 }),
        level: 'action',
        step: '증빙유형',
        message: 'AI 판단: 증빙유형=일반경비(신뢰도 0.92)',
      },
      {
        id: 'l3',
        at: relativeFromNow({ hours: 2, minutes: 1 }),
        level: 'action',
        step: '프로젝트',
        message: 'AI 판단: 프로젝트=브랜드 사이트(신뢰도 0.76)',
      },
      {
        id: 'l4',
        at: relativeFromNow({ hours: 2 }),
        level: 'success',
        step: '적용',
        message: '적용 완료 · 저장/상신 보류',
      },
    ],
    intervention: null,
  },
  {
    id: 'bom-lookup',
    name: '자재 BOM 조회',
    description: '품목 BOM 구조를 조회해 구성 품목과 소요량을 수집하는 읽기 전용 에이전트.',
    drive: 'browser',
    interaction: 'readonly',
    targetSystem: '더존 옴니솔',
    targetUrl: 'erp.ninebell.co.kr',
    status: 'idle',
    progress: 0,
    timeoutSeconds: 120,
    elapsedSeconds: 0,
    currentAction: '대기 중 — 실행을 시작하면 라이브 화면이 표시됩니다.',
    runCount: 64,
    successRate: 98.4,
    avgSeconds: 36,
    lastRunAt: relativeFromNow({ days: 1 }),
    steps: baseSteps({}, [
      {
        id: 'query',
        label: '조회',
        skill: '그리드 읽기',
        status: 'pending',
        detail: '품목코드로 BOM 조회',
      },
      { id: 'collect', label: '데이터 수집', skill: '그리드 읽기', status: 'pending' },
      { id: 'apply', label: '결과 정리', status: 'pending' },
    ]),
    logs: [
      {
        id: 'l1',
        at: relativeFromNow({ days: 1 }),
        level: 'info',
        message: '직전 실행 완료 · 구성품목 27건 수집',
      },
    ],
    intervention: null,
  },
];

export function findAgent(id: string): Agent | null {
  return AGENTS.find((a) => a.id === id) ?? null;
}

/** 헤드리스 브라우저 슬롯을 점유한 상태(라이브 세션). */
export const LIVE_SESSION_STATUSES: ReadonlySet<AgentStatus> = new Set([
  'running',
  'waiting_input',
  'paused',
]);

/** 지금 라이브(헤드리스 브라우저) 슬롯을 쓰고 있는 세션 수. */
export function liveSessionCount(): number {
  return AGENTS.filter((a) => LIVE_SESSION_STATUSES.has(a.status)).length;
}
