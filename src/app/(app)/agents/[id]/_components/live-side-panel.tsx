'use client';

import { useEffect, useRef, useState } from 'react';
import { RiArrowRightUpLine, RiCheckLine, RiErrorWarningLine } from '@remixicon/react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { EmptyNote } from '@/components/ui/empty-note';
import { LiveChatCard } from '@/components/live/LiveChatCard';
import { LiveChoiceCard } from '@/components/live/LiveChoiceCard';
import { LiveGridCard } from '@/components/live/LiveGridCard';
import type {
  LiveLogLevel,
  LiveLogLine,
  LiveTransactions,
  UseLiveRunReturn,
} from '@/lib/live/types';
import type { WorkflowStep } from '@/lib/data/agents';
import { cn } from '@/lib/utils';
import { TemplatesTab, type RunsPanelProps } from './agent-runs-panel';
import { InterventionEmpty } from './intervention-empty';
import { PhaseStepPanel } from './phase-step-panel';

interface LiveSidePanelProps {
  run: UseLiveRunReturn;
  /** 결과 탭 하단에 덧붙일 액션(예: '템플릿으로 저장'). 종료·결과가 있을 때만 표시된다. */
  resultAction?: React.ReactNode;
  /** 실행 이력·템플릿 탭 데이터(하단 패널에서 우측 탭으로 이동). 없으면 두 탭을 숨긴다. */
  runsPanel?: RunsPanelProps;
  /**
   * 에이전트의 단계 계획(백엔드 `/agents/{id}` steps — 단일 소스). 라이브 단계에
   * 한글 라벨·스킬·상세·개입 표시를 병합하고 미도달 단계까지 전체를 노출한다.
   * 없거나 비어 있으면(DB 스텝 없는 데모 등) 도착한 라이브 단계 id 그대로 폴백.
   */
  planSteps?: readonly WorkflowStep[];
  /**
   * 완료 후 사람이 이어서 할 일(에이전트 handoff_note). 성공 종료 시 결과 탭에서 성공
   * 박스와 구분된 안내로 보여준다(예: 저장된 결의서를 옴니솔에서 결제 상신). 없으면 미표시.
   */
  handoffNote?: string | null;
}

type TabKey = 'intervention' | 'workflow' | 'log' | 'result' | 'templates';

/**
 * 라이브 사이드 패널 — 라이브 스트림에서 파생한 개입/워크플로우/로그/결과 탭.
 * HITL 이 뜨면 개입 탭으로, 종료되면 결과 탭으로 자동 전환한다. 개입은 hitl.kind 로
 * 분기: chat → 대화형 카드(LiveChatCard), 그 외 → 옵션형 카드(LiveChoiceCard).
 */
export function LiveSidePanel({
  run,
  resultAction,
  runsPanel,
  planSteps,
  handoffNote,
}: LiveSidePanelProps) {
  const hasHitl = Boolean(run.hitl);
  const terminal = run.status === 'succeeded' || run.status === 'failed';
  const hasResult = run.result != null || run.error != null || run.transactions != null;

  const [tab, setTab] = useState<TabKey>('workflow');

  // HITL 이 뜨면 개입 탭으로 끌어오고, 개입이 끝나면(제출) 워크플로우 탭으로 되돌린다
  // (사용자 요청: 제출 후 개입 탭이 아니라 워크플로우 진행이 보여야 한다).
  const prevHadHitl = useRef(false);
  useEffect(() => {
    const has = Boolean(run.hitl);
    if (has) setTab('intervention');
    else if (prevHadHitl.current && !terminal) setTab('workflow');
    prevHadHitl.current = has;
  }, [run.hitl?.id, terminal]);
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
            {/* 펄스 점은 시각 전용 — 같은 정보를 스크린리더에도 알린다(항상 렌더해 두어야
                aria-live 가 텍스트 변경을 감지한다). */}
            <span role="status" aria-live="polite" className="sr-only">
              {hasHitl ? '개입 1건 대기 중' : ''}
            </span>
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
            ) : run.hitl.kind === 'grid' ? (
              <LiveGridCard
                hitl={run.hitl}
                onQuery={(query) => run.sendQuery(run.hitl!.id, query)}
                onSubmit={(rows) => run.sendRows(run.hitl!.id, rows)}
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

        {/* Phase 아코디언 — 자체 sticky 진행 헤더가 있어 패딩 없이 스크롤 컨테이너만 준다. */}
        <TabsContent value="workflow" className="min-h-0 flex-1 overflow-y-auto">
          <PhaseStepPanel planSteps={planSteps} liveSteps={run.steps} runStatus={run.status} />
        </TabsContent>

        <TabsContent value="log" className="min-h-0 flex-1 overflow-y-auto p-3">
          <LiveLogList logs={run.logs} />
        </TabsContent>

        {hasResult ? (
          <TabsContent value="result" className="min-h-0 flex-1 overflow-y-auto p-4">
            <LiveResult result={run.result} error={run.error} transactions={run.transactions} />
            {run.status === 'succeeded' && handoffNote ? <HandoffNote note={handoffNote} /> : null}
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

// (구 LiveStepList 는 PhaseStepPanel — phase-step-panel.tsx — 로 대체되어 제거됐다.)

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
    return <EmptyNote>아직 로그가 없습니다.</EmptyNote>;
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

/**
 * 완료 후 사람이 이어서 할 일(핸드오프 안내) — 성공 결과(초록) 아래에 info 톤으로 구분해
 * 보여준다. "에이전트는 여기까지, 이후는 사람 몫"임을 명확히 한다. 성공 종료 시에만 렌더.
 */
function HandoffNote({ note }: { note: string }) {
  return (
    <div
      data-testid="handoff-note"
      className="border-info/30 bg-info/10 mt-3 flex items-start gap-2.5 rounded-[var(--radius-md)] border px-3 py-2.5"
    >
      <RiArrowRightUpLine size={16} aria-hidden className="text-info mt-0.5 shrink-0" />
      <div className="flex flex-col gap-0.5">
        <p className="text-info text-[length:var(--text-caption)] font-semibold tracking-[0.04em]">
          다음 할 일
        </p>
        <p className="text-foreground text-[length:var(--text-body-sm)] leading-relaxed">{note}</p>
      </div>
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
