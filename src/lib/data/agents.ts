/**
 * 에이전트 도메인 모델(타입·어휘·가시성 규칙) — 나인벨 AX의 핵심 단위.
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
  /** 이 단계가 사용하는 공용 스킬명(백엔드가 카탈로그 키를 라벨로 풀어 내려준다). */
  skill?: string;
  /** 공용 스킬 카탈로그 키(백엔드 app/services/skills.py — /skills 역인덱스와 매칭). */
  skillKey?: string;
  status: StepStatus;
  /** 우측 상세 워크플로우 탭에 노출될 보조 설명/하위 단계. */
  detail?: string;
  substeps?: readonly SubStep[];
  /** true 면 이 단계에서 사용자 개입(HITL)이 필요하다 — '개입 필요' 표시. */
  intervention?: boolean;
  /**
   * 실행 이력 기반 예상 소요(밀리초) — 백엔드 /agents/{id} 가 이력이 있을 때만 내려준다.
   * 자동(비개입) 스텝 중 하나라도 이 값이 없으면 예상 시간 UI(세그먼트 타임라인·CTA 소요
   * 예고) 전체를 숨긴다 — 부분 데이터로 엉터리 합계를 만들지 않기 위함. 개입 스텝의 값은
   * 예측에 쓰지 않는다(사람 시간은 예측 대상이 아님 — 타임라인에서 고정폭으로 표시).
   */
  expectedMs?: number;
  /** 큰 단계(카테고리) 라벨 — Phase 아코디언 그룹핑(백엔드 agent_steps.phase). */
  phase?: string;
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

// ── 에이전트 세부설정 ─────────────────────────────────────────────────

/**
 * 에이전트별 세부설정 한 항목의 스키마(백엔드 settingsSchema 원소).
 * 관리자 '에이전트 관리' 화면이 이 스키마만 보고 폼을 자동 렌더한다.
 * 현재는 number 타입만 지원한다(예: corporate-card 의 acct_cutoff_day).
 */
export interface AgentSettingDef {
  key: string;
  label: string;
  type: 'number';
  /** 기본값 — 저장된 값이 없을 때 백엔드가 병합해 내려주는 값과 동일. */
  default: number;
  min?: number | null;
  max?: number | null;
  /** 라벨 옆에 표기할 단위(예: '일'). */
  unit?: string | null;
  /** 필드 하단 힌트로 노출되는 설명. */
  description: string;
}

// ── 에이전트 ─────────────────────────────────────────────────────────

export interface Agent {
  id: string;
  /**
   * 엔진에 등록된 실행 워크플로우 id(서버 agents.workflow_id). 실행 게이트의 단일 소스 —
   * 지정된 에이전트만 라이브 실행 가능하고, 없으면 실행 컨트롤이 비활성화된다.
   */
  workflowId?: string;
  /**
   * 소속 그룹(2뎁스 분류 — 서버 agent_groups). 목록 섹션·디테일 브레드크럼 표기 전용이며
   * 실행·권한과 무관하다. null/미지정 = 단독 에이전트.
   */
  group?: { id: string; name: string; description?: string | null } | null;
  name: string;
  description: string;
  /**
   * 완료 후 사람이 이어서 할 일(핸드오프 안내). 에이전트는 자동화 지점까지만 실행하고,
   * 이후는 사람 몫임을 완료 화면에서 안내한다(예: 카드=저장 후 옴니솔 결제 상신). 없으면 미표시.
   */
  handoffNote?: string | null;
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
  /** 마지막 실행 시각(ISO). 실행 이력 없는 에이전트(준비 중 더미 등)는 null. */
  lastRunAt: string | null;
  steps: readonly WorkflowStep[];
  logs: readonly LogEntry[];
  intervention?: Intervention | null;
  /**
   * 세부설정 유효값(기본값 병합 완료) — 백엔드 GET /agents(·/{id})가
   * settingsSchema 가 있는 에이전트에만 내려준다. 스칼라(number/string/boolean) 외에
   * 구조화 값(예 출장 fuel_classes 목록)도 담길 수 있어 값 타입은 unknown.
   */
  settings?: Record<string, unknown>;
  /** 세부설정 스키마 — 없으면(빈 배열 포함) '에이전트 관리'에 노출되지 않는다. */
  settingsSchema?: readonly AgentSettingDef[];
}

/**
 * UI에서만 숨기는 워크플로우 id — 백엔드/실행은 그대로 두고 화면 목록에서만 제외한다.
 * workflowId 로 매칭하며, 상세 페이지 직접 URL 접근은 막지 않는다. 현재 숨김 대상 없음
 * (해외출장·경조금 노출 해제). 숨기려면 해당 workflowId 를 이 Set 에 추가한다.
 */
export const HIDDEN_WORKFLOW_IDS: ReadonlySet<string> = new Set<string>();

/** 숨김 대상(HIDDEN_WORKFLOW_IDS)을 제외한 목록 — 화면 표시용 필터. */
export function filterVisibleAgents<T extends { workflowId?: string }>(agents: readonly T[]): T[] {
  return agents.filter((a) => !a.workflowId || !HIDDEN_WORKFLOW_IDS.has(a.workflowId));
}

/**
 * 일반 모드에서 숨길 워크플로우 — **현재 비어 있다**(전 종류 상시 노출, 사용자 확정 2026-08-11).
 * 출장(국내·해외)·경조금·학자금은 검증이 끝나 일반 사용자에게도 공개했다.
 * 메커니즘은 유지한다 — 새 에이전트를 검증 기간 동안 감출 때 여기 id 한 줄만 추가하면 된다.
 */
export const DEBUG_ONLY_WORKFLOW_IDS: ReadonlySet<string> = new Set([]);

/**
 * 일반 모드에서 숨길 **에이전트 id** — 실행 워크플로우가 없어 workflowId 로는 못 거르는 건.
 * (`DEBUG_ONLY_WORKFLOW_IDS` 는 workflowId 매칭이라 workflow_id=null 인 에이전트엔 무력하다.)
 *
 * · `tax-invoice` — 세금계산서. 실행 전 폼으로 승격됐지만(2026-08-19) 스모크 사이클을 아직
 *   통과하지 않았다 — 통과 전 정식 공개 금지. 통과 후 이 한 줄을 지운다.
 * · 구매팀 그룹 전체(`purchase-order`·`item-bulk-register`·`purchase-order-demo`) — 구축 중
 *   (구매발주 Phase A: 계획서까지, 실 발주 저장 없음)이라 일반 모드에서 감춘다(사용자 지정
 *   2026-08-14). 그룹 카드·메뉴얼 '구매팀' 분류는 소속 에이전트가 전부 걸러지면 함께
 *   사라진다. 정식 공개할 때 이 줄들을 지운다.
 */
export const DEBUG_ONLY_AGENT_IDS: ReadonlySet<string> = new Set([
  'tax-invoice',
  'purchase-order',
  'item-bulk-register',
  'purchase-order-demo',
]);

/** 일반 모드에서 감출 대상인지 — 목록 필터와 상세 URL 게이트가 함께 쓰는 단일 판정. */
export function isDebugOnlyAgent(agent: { id: string; workflowId?: string }): boolean {
  return (
    DEBUG_ONLY_AGENT_IDS.has(agent.id) ||
    (!!agent.workflowId && DEBUG_ONLY_WORKFLOW_IDS.has(agent.workflowId))
  );
}

/**
 * 디버그 모드 여부에 따라 에이전트를 걸러낸다.
 *  · 디버그 모드: 아무것도 숨기지 않는다.
 *  · 일반 모드: `DEBUG_ONLY_AGENT_IDS`(id) 또는 `DEBUG_ONLY_WORKFLOW_IDS`(workflowId) 등록분을 숨긴다.
 *
 * ⚠ 이 필터는 **화면 표시 전용**이다 — 서버는 여전히 내려주므로 보안 경계가 아니다
 *   (디버그 모드 자체가 localStorage 클라이언트 플래그다). 권한으로 막아야 하는 것은
 *   백엔드 hidden(`agent_visibility.HIDDEN_AGENT_IDS`)을 쓴다.
 */
export function filterByDebugMode<T extends { id: string; workflowId?: string }>(
  agents: readonly T[],
  debugMode: boolean,
): T[] {
  if (debugMode) return [...agents];
  return agents.filter((a) => !isDebugOnlyAgent(a));
}

/** 헤드리스 브라우저 슬롯을 점유한 상태(라이브 세션). */
export const LIVE_SESSION_STATUSES: ReadonlySet<AgentStatus> = new Set([
  'running',
  'waiting_input',
  'paused',
]);
