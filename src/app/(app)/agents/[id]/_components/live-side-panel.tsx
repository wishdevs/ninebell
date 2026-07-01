'use client';

import { useEffect, useState } from 'react';
import { RiCheckLine, RiCloseLine, RiErrorWarningLine, RiLoader4Line } from '@remixicon/react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { LiveChatCard } from '@/components/live/LiveChatCard';
import { LiveChoiceCard } from '@/components/live/LiveChoiceCard';
import type {
  LiveLogLevel,
  LiveLogLine,
  LiveStepState,
  LiveStepStatus,
  LiveTransactions,
  UseLiveRunReturn,
} from '@/lib/live/types';
import { WORKFLOW_STEP_DEFS } from '@/lib/live/step-defs';
import { cn } from '@/lib/utils';
import { TemplatesTab, type RunsPanelProps } from './agent-runs-panel';
import { InterventionEmpty } from './intervention-empty';

interface LiveSidePanelProps {
  run: UseLiveRunReturn;
  /** 결과 탭 하단에 덧붙일 액션(예: '템플릿으로 저장'). 종료·결과가 있을 때만 표시된다. */
  resultAction?: React.ReactNode;
  /** 실행 이력·템플릿 탭 데이터(하단 패널에서 우측 탭으로 이동). 없으면 두 탭을 숨긴다. */
  runsPanel?: RunsPanelProps;
  /** 엔진에 등록된 워크플로우 id(예: `expense-card-chat`) — 단계 라벨 번역·전체 단계 표시에 쓴다. */
  workflowId?: string;
}

type TabKey = 'intervention' | 'workflow' | 'log' | 'result' | 'templates';

/**
 * 라이브 사이드 패널 — 라이브 스트림에서 파생한 개입/워크플로우/로그/결과 탭.
 * HITL 이 뜨면 개입 탭으로, 종료되면 결과 탭으로 자동 전환한다. 개입은 hitl.kind 로
 * 분기: chat → 대화형 카드(LiveChatCard), 그 외 → 옵션형 카드(LiveChoiceCard).
 */
export function LiveSidePanel({ run, resultAction, runsPanel, workflowId }: LiveSidePanelProps) {
  const hasHitl = Boolean(run.hitl);
  const terminal = run.status === 'succeeded' || run.status === 'failed';
  const hasResult = run.result != null || run.error != null || run.transactions != null;

  const [tab, setTab] = useState<TabKey>('workflow');

  // HITL 이 뜨면 개입 탭으로 끌어온다(사용자 응답 유도).
  useEffect(() => {
    if (run.hitl) setTab('intervention');
  }, [run.hitl?.id]);
  // 종료되면 결과가 있을 때 결과 탭으로.
  useEffect(() => {
    if (terminal && hasResult) setTab('result');
  }, [terminal, hasResult]);

  return (
    <section className="border-border bg-surface flex min-h-[440px] flex-col overflow-hidden rounded-[var(--radius-lg)] border shadow-[var(--shadow-card)] lg:h-full lg:min-h-0 lg:min-w-0">
      <Tabs
        value={tab}
        onValueChange={(v) => setTab(v as TabKey)}
        className="flex min-h-0 flex-1 flex-col"
      >
        <TabsList className="no-scrollbar shrink-0 overflow-x-auto px-3 pt-1">
          <TabsTrigger value="intervention" className="gap-1.5">
            개입
            {hasHitl ? (
              <span className="bg-warning size-1.5 animate-pulse rounded-full" aria-hidden />
            ) : null}
          </TabsTrigger>
          <TabsTrigger value="workflow">워크플로우</TabsTrigger>
          <TabsTrigger value="log">
            로그
            <span className="text-foreground-tertiary ml-1.5 text-[10px] tabular-nums">
              {run.logs.length}
            </span>
          </TabsTrigger>
          {hasResult ? <TabsTrigger value="result">결과</TabsTrigger> : null}
          {runsPanel ? <TabsTrigger value="templates">템플릿</TabsTrigger> : null}
        </TabsList>

        <TabsContent value="intervention" className="min-h-0 flex-1 overflow-hidden p-4">
          {run.hitl ? (
            run.hitl.kind === 'chat' ? (
              <LiveChatCard
                hitl={run.hitl}
                messages={run.chat}
                onSend={(text) => run.sendChat(run.hitl!.id, text)}
                onComplete={() => run.finishChat(run.hitl!.id)}
              />
            ) : (
              <LiveChoiceCard
                hitl={run.hitl}
                onSubmit={(payload) => run.sendHitl(run.hitl!.id, payload)}
              />
            )
          ) : (
            <InterventionEmpty />
          )}
        </TabsContent>

        <TabsContent value="workflow" className="min-h-0 flex-1 overflow-y-auto p-4">
          <LiveStepList steps={run.steps} status={run.status} workflowId={workflowId} />
        </TabsContent>

        <TabsContent value="log" className="min-h-0 flex-1 overflow-y-auto p-3">
          <LiveLogList logs={run.logs} />
        </TabsContent>

        {hasResult ? (
          <TabsContent value="result" className="min-h-0 flex-1 overflow-y-auto p-4">
            <LiveResult result={run.result} error={run.error} transactions={run.transactions} />
            {resultAction ? (
              <div className="border-border mt-4 border-t pt-4">{resultAction}</div>
            ) : null}
          </TabsContent>
        ) : null}

        {runsPanel ? (
          <TabsContent value="templates" className="min-h-0 flex-1 overflow-y-auto p-3">
            <TemplatesTab {...runsPanel} />
          </TabsContent>
        ) : null}
      </Tabs>
    </section>
  );
}

// ── 라이브 단계 목록 ─────────────────────────────────────────────────

type DisplayStepStatus = LiveStepStatus | 'pending';

interface DisplayStep {
  id: string;
  label: string;
  status: DisplayStepStatus;
  ms?: number;
  skill?: string;
  detail?: string;
}

const STEP_DOT: Record<DisplayStepStatus, string> = {
  running: 'bg-accent/15 text-accent',
  done: 'bg-success/15 text-success',
  failed: 'bg-danger/15 text-danger',
  pending: 'bg-muted text-muted-foreground',
};

const STEP_LABEL: Record<DisplayStepStatus, string> = {
  running: '진행 중',
  done: '완료',
  failed: '실패',
  pending: '대기',
};

/**
 * 라이브 단계(도착한 것만)를 워크플로우 정의(전체 순서·한글 라벨)와 병합한다.
 * 정의에 없는 워크플로우/단계는 원래 id 를 라벨로 써 그대로 노출한다(안전 폴백).
 */
function buildDisplaySteps(
  workflowId: string | undefined,
  steps: readonly LiveStepState[],
): DisplayStep[] {
  const defs = workflowId ? WORKFLOW_STEP_DEFS[workflowId] : undefined;
  if (!defs) {
    return steps.map((s) => ({ id: s.step, label: s.step, status: s.status, ms: s.ms }));
  }
  const byId = new Map(steps.map((s) => [s.step, s] as const));
  const known = new Set(defs.map((d) => d.id));
  const merged = defs.map((d): DisplayStep => {
    const live = byId.get(d.id);
    return {
      id: d.id,
      label: d.label,
      status: live?.status ?? 'pending',
      ms: live?.ms,
      skill: d.skill,
      detail: d.detail,
    };
  });
  // 정의에 없는(향후 추가된) 단계는 도착 순서 그대로 뒤에 붙인다.
  const extra = steps
    .filter((s) => !known.has(s.step))
    .map((s): DisplayStep => ({ id: s.step, label: s.step, status: s.status, ms: s.ms }));
  return [...merged, ...extra];
}

export function LiveStepList({
  steps,
  status,
  workflowId,
}: {
  steps: readonly LiveStepState[];
  status: UseLiveRunReturn['status'];
  workflowId?: string;
}) {
  const display = buildDisplaySteps(workflowId, steps);
  if (display.length === 0) {
    return (
      <p className="text-foreground-tertiary py-6 text-center text-[12px]">
        {status === 'connecting' ? '세션에 연결하는 중…' : '아직 단계가 없습니다.'}
      </p>
    );
  }
  return (
    <ol className="flex flex-col">
      {display.map((step, i) => (
        <li key={step.id} className="relative flex gap-3 pb-4 last:pb-0">
          {i < display.length - 1 ? (
            <span
              aria-hidden
              className="bg-border absolute top-6 left-[11px] h-[calc(100%-1rem)] w-px"
            />
          ) : null}
          <span
            className={cn(
              'relative z-10 mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full',
              STEP_DOT[step.status],
            )}
          >
            {step.status === 'done' ? (
              <RiCheckLine size={12} aria-hidden />
            ) : step.status === 'failed' ? (
              <RiCloseLine size={12} aria-hidden />
            ) : step.status === 'pending' ? (
              <span className="text-[10px] font-bold tabular-nums">{i + 1}</span>
            ) : (
              <RiLoader4Line size={12} className="animate-spin" aria-hidden />
            )}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-2">
              <span className="text-foreground text-[length:var(--text-body-sm)] font-semibold">
                {step.label}
              </span>
              <span
                className={cn(
                  'shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-semibold',
                  STEP_DOT[step.status],
                )}
              >
                {STEP_LABEL[step.status]}
              </span>
            </div>
            {step.skill ? (
              <span className="text-foreground-tertiary border-border-subtle mt-0.5 mr-1.5 inline-block rounded border px-1.5 py-0.5 text-[10px]">
                {step.skill}
              </span>
            ) : null}
            {step.ms != null ? (
              <span className="text-foreground-tertiary text-[10px] tabular-nums">{step.ms}ms</span>
            ) : null}
            {step.detail ? (
              <p className="text-muted-foreground mt-1 text-[11px] leading-relaxed">
                {step.detail}
              </p>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

// ── 라이브 로그 ──────────────────────────────────────────────────────

const LOG_TONE: Record<LiveLogLevel, string> = {
  info: 'text-muted-foreground bg-muted',
  ok: 'text-success bg-success/10',
  warn: 'text-warning bg-warning/10',
  error: 'text-danger bg-danger/10',
};

const LOG_LABEL: Record<LiveLogLevel, string> = {
  info: 'INFO',
  ok: 'OK',
  warn: 'WARN',
  error: 'ERR',
};

export function LiveLogList({ logs }: { logs: readonly LiveLogLine[] }) {
  if (logs.length === 0) {
    return (
      <p className="text-foreground-tertiary py-6 text-center text-[12px]">아직 로그가 없습니다.</p>
    );
  }
  return (
    <ul className="flex flex-col gap-0.5">
      {logs.map((log) => (
        <li
          key={log.id}
          className="hover:bg-muted/50 flex items-start gap-2 rounded-[var(--radius-sm)] px-2 py-1.5"
        >
          <span
            className={cn(
              'mt-0.5 shrink-0 rounded px-1 py-0.5 font-mono text-[9px] font-bold',
              LOG_TONE[log.level],
            )}
          >
            {LOG_LABEL[log.level]}
          </span>
          <p className="text-foreground-secondary min-w-0 flex-1 text-[11px] leading-snug">
            {log.message}
          </p>
        </li>
      ))}
    </ul>
  );
}

// ── 결과 ─────────────────────────────────────────────────────────────

export function LiveResult({
  result,
  error,
  transactions,
}: {
  result: string | null;
  error: string | null;
  transactions: LiveTransactions | null;
}) {
  return (
    <div className="flex flex-col gap-4">
      {error ? (
        <div className="border-danger/30 bg-danger/10 text-danger flex items-start gap-2.5 rounded-[var(--radius-md)] border px-3 py-2.5">
          <RiErrorWarningLine size={16} aria-hidden className="mt-0.5 shrink-0" />
          <p className="text-[length:var(--text-body-sm)] leading-relaxed">{error}</p>
        </div>
      ) : null}

      {result ? (
        <div className="border-success/30 bg-success/10 flex items-start gap-2.5 rounded-[var(--radius-md)] border px-3 py-2.5">
          <RiCheckLine size={16} aria-hidden className="text-success mt-0.5 shrink-0" />
          <p className="text-foreground text-[length:var(--text-body-sm)] leading-relaxed">
            {result}
          </p>
        </div>
      ) : null}

      {transactions ? <TxTable table={transactions} /> : null}
    </div>
  );
}

function TxTable({ table }: { table: LiveTransactions }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-foreground text-[length:var(--text-body-sm)] font-semibold">
        {table.title}
      </p>
      <div className="border-border overflow-x-auto rounded-[var(--radius-md)] border">
        <table className="w-full text-[11px]">
          <thead className="bg-muted/50 text-foreground-tertiary">
            <tr>
              {table.columns.map((c) => (
                <th
                  key={c.key}
                  className={cn(
                    'px-2 py-1.5 font-semibold',
                    c.align === 'right' ? 'text-right' : 'text-left',
                  )}
                >
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, ri) => (
              <tr key={ri} className="border-border/60 border-t">
                {table.columns.map((c) => (
                  <td
                    key={c.key}
                    className={cn(
                      'text-foreground-secondary px-2 py-1.5 tabular-nums',
                      c.align === 'right' ? 'text-right' : 'text-left',
                    )}
                  >
                    {row[c.key] ?? ''}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
