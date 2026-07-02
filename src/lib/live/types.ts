/**
 * 라이브 런(SSE) 도메인 타입 — 백엔드 이벤트 모델(app/live/events.py)과 1:1.
 *
 * SSE 프레임은 모두 "평탄한 dict"이며 한 프레임에 하나의 판별 키(step/log/screenshot/
 * hitl/chat/transactions/result/error)만 들어온다. 그래서 유니온을 태그드 유니온이 아니라
 * 모든 키가 옵셔널인 {@link LiveFrame} 로 모델링하고, 키 존재로 좁힌다(파싱이 단순해진다).
 *
 * 프레임 계약(고정):
 *   {"step": str, "status": "running"|"done"|"failed", "ms"?: int}
 *   {"log": str, "level": "info"|"ok"|"error"|"warn"}
 *   {"screenshot": "data:image/jpeg;base64,..."}          // 비버퍼(최신 1장)
 *   {"hitl": {"id","kind","title","prompt","options"?}}
 *   {"chat": {"id","role","content","streaming"?,"done"?,"note"?}}
 *   {"transactions": {"title","columns","rows"}}
 *   {"result": str}                                        // 종료(성공)
 *   {"error": str}                                         // 종료(실패)
 */

// ── 스칼라 ───────────────────────────────────────────────────────────

/** 단계 상태(백엔드 emit_step) — UI 스텝 상태(done/active/…)와는 별개. */
export type LiveStepStatus = 'running' | 'done' | 'failed';

/** 로그 레벨(백엔드 emit_log). ok=성공, warn/error/info. */
export type LiveLogLevel = 'info' | 'ok' | 'warn' | 'error';

/** 채팅 롤(백엔드 emit_chat). */
export type ChatRole = 'user' | 'assistant' | 'system';

/**
 * HITL 종류. demo-echo 는 `confirm`(옵션 yes/no), 실 에이전트는 `chat`(대화형) 등을 쓴다.
 * 알 수 없는 종류가 와도 무너지지 않도록 문자열 유니온으로 열어 둔다.
 */
export type LiveHitlKind =
  'confirm' | 'select' | 'multiselect' | 'input' | 'search' | 'chat' | 'grid' | (string & {});

// ── 서브 페이로드 ────────────────────────────────────────────────────

export interface LiveHitlOption {
  value: string;
  label: string;
  description?: string;
  recommended?: boolean;
}

/**
 * 그리드 개입(kind=grid) 한 행 — 카드 거래내역. 표시 컬럼은 읽기 전용이며,
 * 사용자는 행마다 예산단위·프로젝트·적요를 채운다. no 는 행 식별자(제출 시 키).
 * 백엔드 진화 중 컬럼이 빠질 수 있어 표시 필드는 모두 옵셔널로 둔다.
 */
export interface LiveGridRow {
  no: number;
  card?: string;
  merchant?: string;
  amount?: string;
  date?: string;
  time?: string;
  approved?: string;
  vatType?: string;
  /** 적요 기본값(입력 프리필). */
  note?: string;
}

/** 예산단위 보기 한 항목(자주쓰는/전체 공용). deptNm 은 부서명(있을 때). */
/** 예산단위 보기 — 선택 단위는 (예산단위명 × 사업계획명 × 예산계정명) 조합 행.
 * code 는 BG|BIZPLAN|BGACCT 복합키. */
export interface BudgetUnitOption {
  code: string;
  name: string;
  bizplanNm?: string;
  bgacctNm?: string;
  /** 과거 데이터 하위호환(미사용). */
  deptNm?: string;
}

/** 프로젝트 보기 한 항목(자주쓰는/검색결과 공용). */
export interface ProjectOption {
  code: string;
  name: string;
}

/** 그리드 개입의 예산단위 보기 — 자주쓰는 → 내 부서(이름 정규화 매칭) → 전사 전체. */
export interface HitlBudgetUnits {
  favorites?: BudgetUnitOption[];
  /** 내 부서 매칭(예: 소속 '인사/기획팀' ↔ 예산단위 '인사기획팀'). */
  mine?: BudgetUnitOption[];
  all?: BudgetUnitOption[];
}

/** 그리드 개입의 프로젝트 보기 — 자주쓰는 + ERP 검색 결과(질의 후 채워짐). */
export interface HitlProjects {
  favorites?: ProjectOption[];
  /** ERP 검색 응답. 검색 전이면 null. */
  searchResults?: ProjectOption[] | null;
  /** 직전 검색어(검색 전이면 null). */
  query?: string | null;
}

export interface LiveHitl {
  id: string;
  kind?: LiveHitlKind; // 미지정 시 select 취급
  title: string;
  prompt?: string;
  options?: LiveHitlOption[];
  /** 보기에 없을 때 직접 입력 허용(select/search). */
  allowText?: boolean;
  textLabel?: string;
  /** kind=search 일 때 검색창 placeholder. */
  searchPlaceholder?: string;
  /** kind=grid — 채워야 할 거래내역 행(없으면 빈 그리드). */
  rows?: LiveGridRow[];
  /** kind=grid — 예산단위 보기(자주쓰는/전체). */
  budgetUnits?: HitlBudgetUnits;
  /** kind=grid — 프로젝트 보기(자주쓰는/검색결과). */
  projects?: HitlProjects;
}

/** 그리드 개입 제출 한 행 — 비제외(skip=false) 행은 budgetUnit·note 필수, project 선택. */
export interface GridRowSubmit {
  no: number;
  /** 예산단위 조합 선택 — bizplanNm/bgacctNm 이 있으면 서버가 그 조합 행을 정확히 고른다. */
  budgetUnit: { code: string; name: string; bizplanNm?: string; bgacctNm?: string } | null;
  project: { code: string; name: string } | null;
  note: string;
  skip: boolean;
}

/** SSE chat 프레임(백엔드 emit_chat) — 화면 표시용 ChatMessage 로 변환된다. */
export interface ChatFrame {
  id: string;
  role: ChatRole;
  content: string;
  streaming?: boolean;
  done?: boolean;
  /** action = 채움 실행로그 말풍선(누적 표시). 그 외 어시스턴트 메시지는 id 로 upsert. */
  note?: 'action';
}

export interface LiveTxColumn {
  key: string;
  header: string;
  align?: 'right';
}

export interface LiveTransactions {
  title: string;
  columns: LiveTxColumn[];
  rows: Array<Record<string, string | number>>;
}

// ── 프레임(와이어) ───────────────────────────────────────────────────

/**
 * 한 SSE 프레임. 하나의 판별 키만 존재한다. 파서는 키 존재로 좁혀서 상태에 반영한다.
 * (백엔드가 평탄한 dict 로 보내므로 태그드 유니온보다 이 형태가 파싱에 유리하다.)
 */
export interface LiveFrame {
  step?: string;
  status?: LiveStepStatus;
  ms?: number;
  log?: string;
  level?: LiveLogLevel;
  screenshot?: string;
  hitl?: LiveHitl;
  chat?: ChatFrame;
  transactions?: LiveTransactions;
  result?: string;
  error?: string;
}

/** HITL 응답 페이로드 — 종류에 따라 하나 이상이 채워진다(POST /runs/hitl body). */
export interface HitlPayload {
  value?: string;
  values?: string[];
  text?: string;
  query?: string;
  message?: string;
  done?: boolean;
  /** kind=grid 일괄 제출 — 행별 예산단위·프로젝트·적요·제외. */
  rows?: GridRowSubmit[];
}

// ── UI 상태 ──────────────────────────────────────────────────────────

/** 라이브 런의 표시 상태. */
export type LiveRunStatus =
  | 'idle' // 세션 없음
  | 'connecting' // /runs/collect 연결 시도 중
  | 'running' // 흐름 진행 중
  | 'waiting_input' // HITL 대기(사용자 입력 필요)
  | 'succeeded' // result 수신(종료)
  | 'failed'; // error/연결실패(종료)

/** 누적 단계(스텝 이름으로 upsert). */
export interface LiveStepState {
  step: string;
  status: LiveStepStatus;
  ms?: number;
}

/** 누적 로그 한 줄. */
export interface LiveLogLine {
  id: string;
  message: string;
  level: LiveLogLevel;
}

/** 화면 표시용 채팅 메시지(사용자 낙관 추가 + 어시스턴트 스트림 반영). */
export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  streaming?: boolean;
  /** 전송 실패한 사용자 말풍선 표시. */
  error?: boolean;
  note?: 'action';
}

/** useLiveRun 이 노출하는 라이브 상태 스냅샷 + 액션. */
export interface LiveRunState {
  /** 이 세션에 사용된 runId(재접속·HITL 에 동봉). 세션 미시작이면 null. */
  runId: string | null;
  status: LiveRunStatus;
  steps: readonly LiveStepState[];
  logs: readonly LiveLogLine[];
  /** 최신 스크린캐스트 dataURL. 없으면 null. */
  screenshot: string | null;
  /** 활성 HITL(대기 중). 없으면 null. */
  hitl: LiveHitl | null;
  chat: readonly ChatMessage[];
  transactions: LiveTransactions | null;
  result: string | null;
  error: string | null;
  /** SSE 스트림이 현재 붙어 있는지(끊김 표시용). */
  connected: boolean;
}

export interface LiveRunActions {
  /** HITL 응답 전달(POST /runs/hitl). 성공 시 true. */
  sendHitl: (decisionId: string, payload: HitlPayload) => Promise<boolean>;
  /** 대화형 HITL 한 턴 — 사용자 말풍선 낙관 추가 + message 전송. */
  sendChat: (decisionId: string, text: string) => Promise<boolean>;
  /** 대화형 HITL 종료 — done 신호(BE 가 마무리 → result). */
  finishChat: (decisionId: string) => Promise<boolean>;
  /** 그리드 개입 — 프로젝트 ERP 검색 질의(BE 가 searchResults 를 채운 새 hitl 프레임을 보냄). */
  sendQuery: (decisionId: string, query: string) => Promise<boolean>;
  /** 그리드 개입 — 행 일괄 제출(채움 실행 재개). */
  sendRows: (decisionId: string, rows: GridRowSubmit[]) => Promise<boolean>;
}

export type UseLiveRunReturn = LiveRunState & LiveRunActions;
