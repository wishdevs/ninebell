'use client';

import { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { Agent, LogEntry, LogLevel } from '@/lib/data/agents';
import { LOG_LEVEL_LABEL } from '@/lib/data/agents';
import { formatRelativeKorean } from '@/lib/data/format';
import { cn } from '@/lib/utils';
import { InterventionEmpty } from './intervention-empty';
import { PhaseStepPanel } from './phase-step-panel';

interface AgentSidePanelProps {
  agent: Agent;
}

/**
 * 브라우저 오른쪽 영역(미실행 상태) — 개입 · 워크플로우 · 로그 탭.
 * 개입은 라이브 실행이 요청할 때만 생기므로, 미실행에서는 픽스처 목업 대화 대신 중립 빈 상태를
 * 보여준다(가짜 채팅 노출 금지). 기본 탭은 워크플로우(상단 스텝퍼와 함께 단계를 노출).
 * (템플릿 탭·'템플릿으로 저장'은 사용자 요청으로 제거 — 2026-07-06.)
 */
export function AgentSidePanel({ agent }: AgentSidePanelProps) {
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
        </TabsList>

        <TabsContent value="intervention" className="min-h-0 flex-1 overflow-y-auto p-4">
          <InterventionEmpty />
        </TabsContent>

        {/* 실행 전에도 라이브와 같은 Phase 아코디언으로 계획을 보여준다(liveSteps 없음 = 전부 대기). */}
        <TabsContent value="workflow" className="min-h-0 flex-1 overflow-y-auto">
          <PhaseStepPanel planSteps={agent.steps} liveSteps={[]} runStatus="idle" />
        </TabsContent>

        <TabsContent value="log" className="min-h-0 flex-1 overflow-y-auto p-3">
          <LogList logs={agent.logs} />
        </TabsContent>
      </Tabs>
    </section>
  );
}

// (구 WorkflowDetail 타임라인은 PhaseStepPanel — phase-step-panel.tsx — 로 대체되어 제거됐다.)

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
