'use client';

/**
 * useChatStream — AI 어시스턴트를 실제 SSE(`POST /assistant/chat`)로 구동하는 훅.
 *
 * 백엔드는 `data: {"delta"|"action"|"error"}\n\n` 프레임과 `data: [DONE]` 을 흘린다.
 * 세션은 httpOnly 쿠키(credentials:'include')로 서버가 처리하므로 브라우저는 토큰을
 * 다루지 않는다. 401 은 세션 만료로 간주해 재로그인 안내를 표시한다(use-live-run 과 동일 UX).
 *
 * ninebell `useChatStream` 을 이 프로젝트용으로 적응 — `/py` 프록시 대신 API_BASE 직접 호출.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { API_BASE } from '@/lib/api/client';
import type { AssistantAction, AssistantMessage } from './types';

let seq = 0;
function uid(prefix: string): string {
  seq += 1;
  return `${prefix}-${Date.now()}-${seq}`;
}

interface ChatStreamOptions {
  getContext?: () => Record<string, unknown>;
}

interface ChatStream {
  messages: AssistantMessage[];
  isStreaming: boolean;
  send: (text: string) => Promise<void>;
  retry: () => void;
}

const CONNECT_ERROR = 'AI 어시스턴트에 연결할 수 없습니다. 잠시 후 다시 시도하세요.';
const SESSION_ERROR = '세션이 만료되었습니다. 다시 로그인해 주세요.';
const EMPTY_ERROR = '응답을 받지 못했습니다. 다시 시도해 주세요.';

/** 모델의 함수호출(action 프레임)을 프론트 AssistantAction 으로 매핑. */
function mapAction(tc: {
  name?: string;
  args?: Record<string, unknown>;
}): AssistantAction | undefined {
  const args = tc.args ?? {};
  if (tc.name === 'suggest_agent' && typeof args.agentId === 'string') {
    const intent = args.intent;
    return {
      kind: 'agent',
      agentId: args.agentId,
      intent: intent === 'open' || intent === 'run' || intent === 'info' ? intent : undefined,
    };
  }
  if (tc.name === 'suggest_run' && typeof args.runId === 'string') {
    return { kind: 'run', runId: args.runId };
  }
  return undefined;
}

export function useChatStream(options: ChatStreamOptions = {}): ChatStream {
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const ref = useRef<AssistantMessage[]>([]);

  const optionsRef = useRef(options);
  optionsRef.current = options;

  const lastInputRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  // isStreaming(상태)은 비동기 반영이라 빠른 더블클릭이 가드를 함께 통과해 이중 스트림을 연다.
  // 동기 ref 로 시작을 직렬화한다.
  const streamingRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      abortRef.current?.abort();
    };
  }, []);

  const commit = useCallback((updater: (prev: AssistantMessage[]) => AssistantMessage[]) => {
    ref.current = updater(ref.current);
    if (mountedRef.current) setMessages(ref.current);
  }, []);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || streamingRef.current) return;
      streamingRef.current = true;

      lastInputRef.current = trimmed;

      const history = ref.current
        .filter((m) => !m.error && m.content)
        .map((m) => ({ role: m.role, content: m.content }));
      const payload = [...history, { role: 'user' as const, content: trimmed }];

      const userMsg: AssistantMessage = { id: uid('u'), role: 'user', content: trimmed };
      const assistantId = uid('a');
      commit((prev) => [
        ...prev,
        userMsg,
        { id: assistantId, role: 'assistant', content: '', streaming: true },
      ]);
      setIsStreaming(true);

      const patch = (fn: (m: AssistantMessage) => AssistantMessage) =>
        commit((prev) => prev.map((m) => (m.id === assistantId ? fn(m) : m)));
      const appendDelta = (delta: string) => patch((m) => ({ ...m, content: m.content + delta }));
      const setAction = (a: AssistantAction) => patch((m) => ({ ...m, action: a }));
      const fail = (msg: string) =>
        patch((m) => ({ ...m, content: msg, streaming: false, error: true }));

      let errored = false;
      const handleFrame = (frame: string): void => {
        const line = frame.trim();
        if (!line.startsWith('data:')) return;
        const data = line.slice(5).trim();
        if (!data || data === '[DONE]') return;
        try {
          const obj = JSON.parse(data) as {
            delta?: string;
            error?: string;
            action?: { name?: string; args?: Record<string, unknown> };
          };
          if (obj.error) {
            // 백엔드가 사용자에게 안전한 메시지를 이미 선별해 보낸다(민감정보는 일반화됨) — 그대로 노출.
            fail(typeof obj.error === 'string' && obj.error ? obj.error : CONNECT_ERROR);
            errored = true;
          } else if (obj.action) {
            const a = mapAction(obj.action);
            if (a) setAction(a);
          } else if (obj.delta) {
            appendDelta(obj.delta);
          }
        } catch {
          // 부분 프레임 — 무시
        }
      };

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const res = await fetch(`${API_BASE}/assistant/chat`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            messages: payload,
            context: optionsRef.current.getContext?.(),
          }),
          signal: controller.signal,
        });
        if (res.status === 401) {
          fail(SESSION_ERROR);
          return;
        }
        if (!res.ok || !res.body) {
          fail(CONNECT_ERROR);
          return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split('\n\n');
          buffer = frames.pop() ?? '';
          for (const frame of frames) handleFrame(frame);
        }

        buffer += decoder.decode();
        if (buffer.trim()) {
          for (const frame of buffer.split('\n\n')) handleFrame(frame);
        }

        if (!errored) {
          // delta·action 이 하나도 없이 스트림이 끝나면(빈 완료·조용한 절단) 빈 말풍선이 영구히
          // 남고 재시도도 불가하다 — 재시도 가능한 에러로 표면화한다.
          patch((m) =>
            m.content || m.action
              ? { ...m, streaming: false }
              : { ...m, content: EMPTY_ERROR, streaming: false, error: true },
          );
        }
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        fail(CONNECT_ERROR);
      } finally {
        streamingRef.current = false;
        if (abortRef.current === controller) abortRef.current = null;
        if (mountedRef.current) setIsStreaming(false);
      }
    },
    [commit],
  );

  const retry = useCallback(() => {
    const last = lastInputRef.current;
    if (!last) return;
    // 실패한 마지막 교환(사용자 질문 + 에러 말풍선)을 걷어낸 뒤 재전송한다. 그러지 않으면 send 가
    // 같은 질문을 화면과 요청 이력 양쪽에 중복으로 쌓는다.
    commit((prev) => {
      const next = [...prev];
      if (next[next.length - 1]?.error) {
        next.pop();
        if (next[next.length - 1]?.role === 'user') next.pop();
      }
      return next;
    });
    void send(last);
  }, [commit, send]);

  return { messages, isStreaming, send, retry };
}
