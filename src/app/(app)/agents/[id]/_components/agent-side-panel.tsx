'use client';

import { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { Agent, LogEntry, LogLevel, StepStatus, WorkflowStep } from '@/lib/data/agents';
import { LOG_LEVEL_LABEL } from '@/lib/data/agents';
import { formatRelativeKorean } from '@/lib/data/format';
import { cn } from '@/lib/utils';
import { TemplatesTab, type RunsPanelProps } from './agent-runs-panel';
import { InterventionEmpty } from './intervention-empty';

interface AgentSidePanelProps {
  agent: Agent;
  /** 템플릿 탭 데이터. (실행 이력은 top-level /logs 페이지와 중복이라 여기선 노출하지 않는다.) */
  runsPanel?: RunsPanelProps;
}

/**
 * 브라우저 오른쪽 영역(미실행 상태) — 개입 · 워크플로우 · 로그 · 템플릿 탭.
 * 개입은 라이브 실행이 요청할 때만 생기므로, 미실행에서는 픽스처 목업 대화 대신 중립 빈 상태를
 * 보여준다(가짜 채팅 노출 금지). 기본 탭은 워크플로우(상단 스텝퍼와 함께 단계를 노출).
 */
export function AgentSidePanel({ agent, runsPanel }: AgentSidePanelProps) {
  const [tab, setTab] = useState('workflow');

  return (
    <section className="border-border bg-surface flex min-h-[440px] flex-col overflow-hidden rounded-[var(--radius-lg)] border shadow-[var(--shadow-card)] lg:h-full lg:min-h-0 lg:min-w-0">
      <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
        <TabsList className="no-scrollbar shrink-0 overflow-x-auto px-3 pt-1">
          <TabsTrigger value="intervention">개입</TabsTrigger>
          <TabsTrigger value="workflow">워크플로우</TabsTrigger>
          <TabsTrigger value="log">
            로그
            <span className="text-foreground-tertiary ml-1.5 text-[10px] tabular-nums">
              {agent.logs.length}
            </span>
          </TabsTrigger>
          {runsPanel ? <TabsTrigger value="templates">템플릿</TabsTrigger> : null}
        </TabsList>

        <TabsContent value="intervention" className="min-h-0 flex-1 overflow-y-auto p-4">
          <InterventionEmpty />
        </TabsContent>

        <TabsContent value="workflow" className="min-h-0 flex-1 overflow-y-auto p-4">
          <WorkflowDetail steps={agent.steps} />
        </TabsContent>

        <TabsContent value="log" className="min-h-0 flex-1 overflow-y-auto p-3">
          <LogList logs={agent.logs} />
        </TabsContent>

        {runsPanel ? (
          <TabsContent value="templates" className="min-h-0 flex-1 overflow-y-auto p-3">
            <TemplatesTab {...runsPanel} />
          </TabsContent>
        ) : null}
      </Tabs>
    </section>
  );
}

// ── 워크플로우 상세(세로 타임라인) ───────────────────────────────────

const STEP_DOT: Record<StepStatus, string> = {
  done: 'bg-success/15 text-success',
  active: 'bg-accent/15 text-accent',
  pending: 'bg-muted text-muted-foreground',
  error: 'bg-danger/15 text-danger',
};

const STEP_LABEL: Record<StepStatus, string> = {
  done: '완료',
  active: '진행 중',
  pending: '대기',
  error: '오류',
};

export function WorkflowDetail({ steps }: { steps: readonly WorkflowStep[] }) {
  return (
    <ol className="flex flex-col">
      {steps.map((step, i) => (
        <li key={step.id} className="relative flex gap-3 pb-4 last:pb-0">
          {i < steps.length - 1 ? (
            <span
              aria-hidden
              className="bg-border absolute top-6 left-[11px] h-[calc(100%-1rem)] w-px"
            />
          ) : null}
          <span
            className={cn(
              'relative z-10 mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold tabular-nums',
              STEP_DOT[step.status],
            )}
          >
            {i + 1}
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
              <span className="text-foreground-tertiary border-border-subtle mt-0.5 inline-block rounded border px-1.5 py-0.5 text-[10px]">
                {step.skill}
              </span>
            ) : null}
            {step.detail ? (
              <p className="text-muted-foreground mt-1 text-[11px] leading-relaxed">
                {step.detail}
              </p>
            ) : null}
            {step.substeps && step.substeps.length > 0 ? (
              <ul className="mt-1.5 flex flex-col gap-1">
                {step.substeps.map((sub, si) => (
                  <li
                    key={si}
                    className="text-foreground-secondary flex items-center gap-1.5 text-[11px]"
                  >
                    <span
                      aria-hidden
                      className={cn(
                        'size-1.5 shrink-0 rounded-full',
                        sub.status === 'done'
                          ? 'bg-success'
                          : sub.status === 'active'
                            ? 'bg-accent animate-pulse'
                            : sub.status === 'error'
                              ? 'bg-danger'
                              : 'bg-muted-foreground/50',
                      )}
                    />
                    <span className={cn(sub.status === 'pending' && 'text-foreground-tertiary')}>
                      {sub.label}
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

// ── 로그 ─────────────────────────────────────────────────────────────

const LOG_TONE: Record<LogLevel, string> = {
  info: 'text-muted-foreground bg-muted',
  action: 'text-accent bg-accent/10',
  success: 'text-success bg-success/10',
  warn: 'text-warning bg-warning/10',
  error: 'text-danger bg-danger/10',
};

function LogList({ logs }: { logs: readonly LogEntry[] }) {
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
            {LOG_LEVEL_LABEL[log.level]}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-foreground-secondary text-[11px] leading-snug">{log.message}</p>
            <p className="text-foreground-tertiary mt-0.5 flex items-center gap-1.5 text-[10px]">
              {log.step ? <span className="font-medium">{log.step}</span> : null}
              <span className="tabular-nums">{formatRelativeKorean(log.at)}</span>
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}
