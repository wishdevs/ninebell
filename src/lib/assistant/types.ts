/**
 * AI 어시스턴트 채팅 타입.
 *
 * `src/lib/live/types.ts` 의 라이브 런 `ChatMessage` 와 이름 충돌을 피하려고
 * 어시스턴트 전용 타입(`AssistantMessage`/`AssistantAction`)으로 둔다.
 */

export type ChatRole = 'user' | 'assistant';

/**
 * 모델(Gemini 함수호출)이 결정한 네비게이션 의도. 프론트는 이 액션을 카드로 렌더한다.
 * - agent: 특정 에이전트로 이동(intent=run 이고 실행 가능하면 실행 CTA 강조).
 * - run: 특정 실행(로그) 조회.
 */
export type AssistantAction =
  | { kind: 'agent'; agentId: string; intent?: 'open' | 'run' | 'info' }
  | { kind: 'run'; runId: string };

export interface AssistantMessage {
  id: string;
  role: ChatRole;
  content: string;
  /** 스트리밍 중(어시스턴트 말풍선). */
  streaming?: boolean;
  /** 에러 말풍선(재시도 노출). */
  error?: boolean;
  /** 모델이 결정한 액션(네비게이션 카드). */
  action?: AssistantAction;
}

/** 액션 카드가 id → 표시정보를 해석하는 데 쓰는 컨텍스트 스냅샷(마운트 시 1회 로드). */
export interface AssistantAgentRef {
  id: string;
  name: string;
  /** workflowId 보유 → 라이브 실행 가능. */
  runnable: boolean;
}

export interface AssistantRunRef {
  id: string;
  agentId: string;
  status: string;
  resultSummary: string | null;
}

export interface AssistantSnapshot {
  agents: readonly AssistantAgentRef[];
  runs: readonly AssistantRunRef[];
}
