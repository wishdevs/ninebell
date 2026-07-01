'use client';

/**
 * useLiveRun — 라이브 런을 실제 SSE(`POST /runs/collect`)로 구동하는 클라이언트 훅.
 *
 * 백엔드 세션(app/live/session.py)은 SSE 연결과 분리돼 살아있으므로, 연결이 끊겨도
 * (프록시 idle/HMR/네트워크) 흐름·HITL 큐가 죽지 않는다. 끊기면 같은 runId+cursor 로
 * 조용히 재접속해 커서 이후만 재생한다(로그·말풍선 중복 방지). 자격증명은 세션 쿠키로
 * 서버가 처리하므로(credentials:'include') 브라우저는 비밀번호를 보내지 않는다.
 *
 * ninebell `useLiveRunDriver`(zustand 전역 상태)를 이 프로젝트용으로 적응 — 전역 스토어
 * 대신 훅 로컬 상태(useReducer)로 캡슐화하고, 우리 엔드포인트/이벤트 모델에 맞췄다.
 */

import { useCallback, useEffect, useReducer, useRef } from 'react';
import { cancelRun } from './runs-api';
import type {
  ChatMessage,
  HitlPayload,
  LiveFrame,
  LiveLogLine,
  LiveRunState,
  LiveStepState,
  UseLiveRunReturn,
} from './types';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://localhost:8000';

// 재연결 정책 — 끊김 시 지수 백오프로 조용히 재시도(흐름은 서버에서 살아있다).
const RECONNECT_MAX = 6;
const RECONNECT_BASE_MS = 800;
const RECONNECT_CAP_MS = 8000;

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

/** 새 runId 발급 — 세션 시작마다 새로, 재접속엔 같은 값을 재사용한다(백엔드 max_length=40). */
export function newRunId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `r-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

// ── reducer ──────────────────────────────────────────────────────────

const initialState: LiveRunState = {
  runId: null,
  status: 'idle',
  steps: [],
  logs: [],
  screenshot: null,
  hitl: null,
  chat: [],
  transactions: null,
  result: null,
  error: null,
  connected: false,
};

type Action =
  | { type: 'start'; runId: string }
  | { type: 'frame'; frame: LiveFrame }
  | { type: 'optimisticUser'; id: string; content: string }
  | { type: 'markError'; id: string }
  | { type: 'connected'; value: boolean }
  | { type: 'failure'; message: string }
  | { type: 'detach' };

function upsertStep(steps: readonly LiveStepState[], next: LiveStepState): LiveStepState[] {
  const i = steps.findIndex((s) => s.step === next.step);
  if (i === -1) return [...steps, next];
  const copy = steps.slice();
  copy[i] = { ...copy[i], status: next.status, ms: next.ms ?? copy[i].ms };
  return copy;
}

function upsertChat(chat: readonly ChatMessage[], msg: ChatMessage): ChatMessage[] {
  const i = chat.findIndex((m) => m.id === msg.id);
  if (i === -1) return [...chat, msg];
  const copy = chat.slice();
  copy[i] = { ...copy[i], ...msg };
  return copy;
}

/** 비-종료 프레임(step/log/chat/…)이 왔을 때의 상태 — 종료는 sticky, HITL 대기는 유지. */
function progressStatus(state: LiveRunState): LiveRunState['status'] {
  if (state.status === 'succeeded' || state.status === 'failed') return state.status;
  return state.hitl ? 'waiting_input' : 'running';
}

/** 한 SSE 프레임을 상태에 반영(키 존재로 좁힌다). 순수 함수. */
function applyFrame(state: LiveRunState, frame: LiveFrame): LiveRunState {
  if (frame.error != null) {
    return { ...state, status: 'failed', hitl: null, error: frame.error };
  }
  if (frame.result != null) {
    return { ...state, status: 'succeeded', hitl: null, result: frame.result };
  }
  if (frame.hitl) {
    return { ...state, status: 'waiting_input', hitl: frame.hitl };
  }
  if (frame.transactions) {
    return { ...state, transactions: frame.transactions, status: progressStatus(state) };
  }
  if (frame.chat) {
    const c = frame.chat;
    const msg: ChatMessage = {
      id: c.id,
      role: c.role,
      content: c.content,
      streaming: c.done ? false : c.streaming,
      note: c.note,
    };
    // note==='action' 은 실행로그 말풍선(항상 신규 append), 그 외는 id 로 upsert.
    const chat = c.note === 'action' ? [...state.chat, msg] : upsertChat(state.chat, msg);
    return { ...state, chat, status: progressStatus(state) };
  }
  if (frame.screenshot != null) {
    // 스크린캐스트(최신 1장) — 상태만 갱신, 상태머신은 건드리지 않는다.
    return { ...state, screenshot: frame.screenshot };
  }
  if (frame.log != null) {
    const line: LiveLogLine = {
      id: `l-${state.logs.length}`,
      message: frame.log,
      level: frame.level ?? 'info',
    };
    return { ...state, logs: [...state.logs, line], status: progressStatus(state) };
  }
  if (frame.step && frame.status) {
    const steps = upsertStep(state.steps, { step: frame.step, status: frame.status, ms: frame.ms });
    return { ...state, steps, status: progressStatus(state) };
  }
  return state;
}

function reducer(state: LiveRunState, action: Action): LiveRunState {
  switch (action.type) {
    case 'start':
      return { ...initialState, runId: action.runId, status: 'connecting', connected: false };
    case 'frame':
      return applyFrame(state, action.frame);
    case 'optimisticUser':
      return {
        ...state,
        chat: [...state.chat, { id: action.id, role: 'user', content: action.content }],
      };
    case 'markError':
      return {
        ...state,
        chat: state.chat.map((m) => (m.id === action.id ? { ...m, error: true } : m)),
      };
    case 'connected':
      return state.connected === action.value ? state : { ...state, connected: action.value };
    case 'failure':
      return { ...state, status: 'failed', hitl: null, connected: false, error: action.message };
    case 'detach':
      return state.connected ? { ...state, connected: false } : state;
    default:
      return state;
  }
}

// ── HITL 전송 ────────────────────────────────────────────────────────

async function postHitl(
  runId: string | null,
  decisionId: string,
  payload: HitlPayload,
): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/runs/hitl`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ runId, decisionId, ...payload }),
    });
    const json = (await res.json().catch(() => ({}))) as { ok?: boolean };
    return res.ok && json.ok === true;
  } catch {
    return false;
  }
}

// ── 훅 ───────────────────────────────────────────────────────────────

export interface UseLiveRunOptions {
  /**
   * 서버 런/세션 id. 지정하면 재마운트(StrictMode)·재접속 시 같은 세션으로 재부착한다
   * (새 흐름 시작 안 함). "다시 실행"처럼 새 흐름을 원하면 새 runId 를 넘긴다. 미지정 시
   * 세션 시작마다 클라이언트가 생성한다(이 경우 재마운트가 새 세션을 만들 수 있음).
   */
  runId?: string;
  /** true 일 때만 세션을 시작(카드 진입=start, 이탈=cleanup→슬롯 반납). */
  enabled?: boolean;
  /** 워크플로우 파라미터(그래프 state.params 로 주입). */
  params?: Record<string, unknown>;
  /**
   * 템플릿 재생(회수) — 지정하면 `/runs/collect` 에 templateId 를 실어 AUTO 재생을
   * 시작한다(대화 없이 저장된 selections 를 순서대로 적용). 새 흐름이므로 재생 시작마다
   * 새 runId 와 함께 넘긴다.
   */
  templateId?: string;
}

type Outcome = 'terminal' | 'dropped' | 'gone' | 'fatal' | 'aborted';

/**
 * 라이브 런 구동. `enabled` 가 true 가 되면 `agentId` 워크플로우를 `/runs/collect` 로
 * 시작하고 SSE 를 파싱해 상태를 누적한다. `enabled` 가 false 가 되거나 언마운트되면
 * fetch 를 abort 해 스트림을 놓는다(브라우저 큐 슬롯 반납 신호).
 */
export function useLiveRun(agentId: string, options: UseLiveRunOptions = {}): UseLiveRunReturn {
  const { runId: runIdProp, enabled = false, params, templateId } = options;
  const [state, dispatch] = useReducer(reducer, initialState);

  // 콜백이 항상 현재 runId 를 읽도록 ref 로 보관(콜백은 안정적으로 유지).
  const runIdRef = useRef<string | null>(null);
  const userSeqRef = useRef(0);
  // params/templateId 는 매 렌더 새 참조일 수 있어 effect 재실행 트리거로 쓰지 않는다(ref 로 캡처).
  const paramsRef = useRef(params);
  paramsRef.current = params;
  const templateIdRef = useRef(templateId);
  templateIdRef.current = templateId;
  // 언마운트/종료 시 예약한 즉시-cancel(StrictMode 재마운트면 다음 setup 이 취소한다).
  const pendingCancelRef = useRef<{ runId: string; timer: ReturnType<typeof setTimeout> } | null>(
    null,
  );

  useEffect(() => {
    if (!enabled || !agentId) return;

    const runId = runIdProp ?? newRunId();
    runIdRef.current = runId;

    // StrictMode 재마운트(같은 runId): 직전 cleanup 이 예약한 즉시-cancel 을 취소해 세션을
    // 유지한다. runId 가 다르면(=다시 실행) 취소하지 않으므로 옛 세션 cancel 이 그대로 발사된다.
    const pending = pendingCancelRef.current;
    if (pending && pending.runId === runId) {
      clearTimeout(pending.timer);
      pendingCancelRef.current = null;
    }

    dispatch({ type: 'start', runId });

    let aborted = false;
    let controller: AbortController | null = null;
    let cursor = 0; // 소비한 비-스크린샷 이벤트 수(서버 재생 버퍼와 1:1)
    let terminal = false;

    const consume = (raw: string): void => {
      const line = raw.trim();
      if (!line.startsWith('data:')) return;
      const data = line.slice(5).trim();
      if (!data || data === '[DONE]') return;
      let frame: LiveFrame;
      try {
        frame = JSON.parse(data) as LiveFrame;
      } catch {
        return; // 부분/손상 프레임 무시(커서 전진 안 함)
      }
      if (frame.error != null || frame.result != null) terminal = true;
      dispatch({ type: 'frame', frame });
      // 스크린샷은 최신 1장(비버퍼)이라 커서 대상이 아니다. 그 외만 커서 전진.
      if (frame.screenshot == null) cursor += 1;
    };

    const connect = async (): Promise<Outcome> => {
      controller = new AbortController();
      let res: Response;
      try {
        res = await fetch(`${API_BASE}/runs/collect`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          credentials: 'include',
          signal: controller.signal,
          body: JSON.stringify({
            runId,
            agentId,
            cursor, // >0 이면 기존 세션 재부착(새 흐름 시작 안 함)
            ...(templateIdRef.current ? { templateId: templateIdRef.current } : {}),
            ...(paramsRef.current ? { params: paramsRef.current } : {}),
          }),
        });
      } catch {
        return aborted ? 'aborted' : 'dropped';
      }

      if (!res.ok) {
        if (res.status === 401) {
          dispatch({ type: 'failure', message: '세션이 만료되었습니다. 다시 로그인해 주세요.' });
          return 'fatal';
        }
        if (res.status === 410) {
          dispatch({ type: 'failure', message: '흐름이 종료되었습니다. 다시 실행해 주세요.' });
          return 'gone';
        }
        let message = '라이브 연결에 실패했습니다.';
        try {
          const err = (await res.json()) as { error?: string };
          if (err.error) message = err.error;
        } catch {
          /* JSON 아니면 기본 메시지 */
        }
        dispatch({ type: 'failure', message });
        return 'fatal';
      }
      if (!res.body) return aborted ? 'aborted' : 'dropped';

      dispatch({ type: 'connected', value: true });
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      try {
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split('\n\n');
          buffer = frames.pop() ?? '';
          for (const f of frames) consume(f);
        }
        buffer += decoder.decode();
        if (buffer.trim()) for (const f of buffer.split('\n\n')) consume(f);
      } catch {
        return aborted ? 'aborted' : 'dropped';
      }
      return terminal ? 'terminal' : aborted ? 'aborted' : 'dropped';
    };

    // 탭 종료/새로고침(pagehide)에도 진행 중 세션을 반납한다 — 리액트 cleanup 이 못 도는
    // 실 언로드 경로를 keepalive fetch 로 보완한다(SPA 이탈은 아래 cleanup 이 담당).
    const onPageHide = (): void => {
      if (!terminal) cancelRun(runId);
    };
    if (typeof window !== 'undefined') window.addEventListener('pagehide', onPageHide);

    void (async () => {
      let attempt = 0;
      for (;;) {
        const before = cursor;
        const outcome = await connect();
        dispatch({ type: 'connected', value: false });
        if (aborted || outcome === 'aborted') return;
        if (outcome === 'terminal' || outcome === 'fatal' || outcome === 'gone') return;
        // dropped → 백오프 후 재접속(커서 이후만 재생). 진전이 있었으면 재시도 예산 복구.
        if (cursor > before) attempt = 0;
        attempt += 1;
        if (attempt > RECONNECT_MAX) {
          dispatch({
            type: 'failure',
            message: '연결이 끊겨 재연결하지 못했습니다. 다시 실행해 주세요.',
          });
          return;
        }
        await sleep(Math.min(RECONNECT_BASE_MS * 2 ** (attempt - 1), RECONNECT_CAP_MS));
        if (aborted) return;
      }
    })();

    return () => {
      aborted = true;
      controller?.abort();
      runIdRef.current = null;
      dispatch({ type: 'detach' });
      if (typeof window !== 'undefined') window.removeEventListener('pagehide', onPageHide);
      // 즉시 큐 반납 — 진행 중 세션이면 cancel 을 예약한다. setTimeout(0) 으로 한 틱 미뤄
      // StrictMode 재마운트(setup 이 예약을 취소)와 실제 종료/이탈을 구분한다. 이미 종료된
      // 런은 세션이 없으니 굳이 보내지 않는다(백엔드도 멱등이라 보내도 무해).
      if (!terminal) {
        const timer = setTimeout(() => {
          pendingCancelRef.current = null;
          cancelRun(runId);
        }, 0);
        pendingCancelRef.current = { runId, timer };
      }
    };
  }, [enabled, agentId, runIdProp]);

  const sendHitl = useCallback(
    (decisionId: string, payload: HitlPayload): Promise<boolean> =>
      postHitl(runIdRef.current, decisionId, payload),
    [],
  );

  const sendChat = useCallback(async (decisionId: string, text: string): Promise<boolean> => {
    const trimmed = text.trim();
    if (!trimmed) return false;
    const id = `u-${runIdRef.current ?? 'x'}-${(userSeqRef.current += 1)}`;
    dispatch({ type: 'optimisticUser', id, content: trimmed });
    const ok = await postHitl(runIdRef.current, decisionId, { message: trimmed });
    if (!ok) dispatch({ type: 'markError', id });
    return ok;
  }, []);

  const finishChat = useCallback(
    (decisionId: string): Promise<boolean> =>
      postHitl(runIdRef.current, decisionId, { done: true }),
    [],
  );

  return { ...state, sendHitl, sendChat, finishChat };
}
