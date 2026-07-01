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
  'confirm' | 'select' | 'multiselect' | 'input' | 'search' | 'chat' | (string & {});

// ── 서브 페이로드 ────────────────────────────────────────────────────

export interface LiveHitlOption {
  value: string;
  label: string;
  description?: string;
  recommended?: boolean;
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
}

export type UseLiveRunReturn = LiveRunState & LiveRunActions;
