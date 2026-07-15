'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { RiSparkling2Line } from '@remixicon/react';
import { useApiResource } from '@/app/(app)/_lib/use-api-resource';
import { fetchRuns, type RunSummary } from '@/lib/live/runs-api';
import { type Agent, filterVisibleAgents } from '@/lib/data/agents';
import type { AssistantSnapshot } from '@/lib/assistant/types';
import { useChatStream } from '@/lib/assistant/use-chat-stream';
import { cn } from '@/lib/utils';
import { MessageList } from './message-list';
import { Composer } from './composer';

const SUGGESTIONS = [
  '지금 사용할 수 있는 에이전트를 알려줘',
  '최근 실행 현황을 요약해줘',
  '방금 실패한 실행의 원인은?',
];

/**
 * AI 어시스턴트 대화 패널. 마운트 시 `/agents`(useApiResource)와 `/runs`(limit 8)를 한 번
 * 로드해 컨텍스트 스냅샷을 만들고, 모델의 함수호출(action 프레임)을 카드로 렌더한다.
 * 의도 파악은 백엔드 Gemini 함수호출이 수행한다.
 */
export function ChatPanel({ layout = 'docked' }: { layout?: 'docked' | 'full' }) {
  const { data: agents } = useApiResource<Agent[]>('/agents');
  const [runs, setRuns] = useState<RunSummary[]>([]);

  useEffect(() => {
    let active = true;
    fetchRuns({ limit: 8 })
      .then((page) => {
        if (active) setRuns(page.runs);
      })
      .catch(() => {
        /* 컨텍스트는 부가정보 — 실패해도 대화는 가능 */
      });
    return () => {
      active = false;
    };
  }, []);

  // 카드가 id → 표시정보를 해석하는 데 쓰는 스냅샷(부분집합).
  const snapshot: AssistantSnapshot = useMemo(
    () => ({
      agents: filterVisibleAgents(agents ?? []).map((a) => ({
        id: a.id,
        name: a.name,
        runnable: !!a.workflowId,
      })),
      runs: runs.map((r) => ({
        id: r.id,
        agentId: r.agentId,
        status: r.status,
        resultSummary: r.resultSummary,
      })),
    }),
    [agents, runs],
  );

  // 백엔드 프롬프트가 기대하는 컨텍스트(더 풍부한 필드).
  const getContext = useCallback(
    () => ({
      agents: (agents ?? []).map((a) => ({
        id: a.id,
        name: a.name,
        description: a.description,
        status: a.status,
        runnable: !!a.workflowId,
      })),
      runs: runs.map((r) => ({
        id: r.id,
        agentId: r.agentId,
        status: r.status,
        resultSummary: r.resultSummary,
        failedStep: r.failedStep ?? null,
      })),
    }),
    [agents, runs],
  );

  const { messages, isStreaming, send, retry } = useChatStream({ getContext });
  const empty = messages.length === 0;

  return (
    <div className="flex h-full flex-col">
      <div className={cn('flex-1 overflow-y-auto', layout === 'full' ? 'p-5' : 'p-4')}>
        {empty ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <span className="bg-accent/10 text-accent grid size-11 place-items-center rounded-full">
              <RiSparkling2Line size={20} aria-hidden />
            </span>
            <h2 className="text-foreground mt-3 text-[15px] font-semibold">AI 어시스턴트</h2>
            <p className="text-muted-foreground mt-1 max-w-sm text-[12px] leading-relaxed">
              에이전트·실행 현황을 묻거나 자연어로 이동을 요청하세요. 답변 근거는 현재 대시보드
              데이터입니다.
            </p>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => send(p)}
                  className="border-border bg-surface text-muted-foreground hover:text-foreground hover:bg-muted rounded-[var(--radius-sm)] border px-2.5 py-1 text-[11px] transition-colors"
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <MessageList messages={messages} snapshot={snapshot} onRetry={retry} />
        )}
      </div>

      <div className="border-border space-y-2 border-t p-3">
        {!empty ? (
          <div className="flex flex-wrap gap-1.5">
            {SUGGESTIONS.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => send(p)}
                disabled={isStreaming}
                className="border-border bg-surface text-muted-foreground hover:text-foreground hover:bg-muted rounded-[var(--radius-sm)] border px-2 py-0.5 text-[10.5px] transition-colors disabled:opacity-40"
              >
                {p}
              </button>
            ))}
          </div>
        ) : null}
        <Composer onSend={send} disabled={isStreaming} />
      </div>
    </div>
  );
}
