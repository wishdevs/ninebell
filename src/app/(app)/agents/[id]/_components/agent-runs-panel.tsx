'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  RiArrowDownSLine,
  RiDeleteBinLine,
  RiHistoryLine,
  RiLoader4Line,
  RiPlayMiniLine,
  RiRefreshLine,
} from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ApiError } from '@/lib/api/client';
import { formatDateTime } from '@/lib/data/format';
import {
  deleteTemplate,
  fetchRunDetail,
  fetchRuns,
  fetchTemplates,
  resultText,
  type RunDetail,
  type RunStatus,
  type RunSummary,
  type RunTemplate,
} from '@/lib/live/runs-api';
import { cn } from '@/lib/utils';
import { LiveLogList, LiveResult } from './live-side-panel';

interface AgentRunsPanelProps {
  /** 워크플로우(agentId) — 이력·템플릿을 이 키로 조회한다. */
  agentId: string;
  /** 증가하면 이력·템플릿을 다시 불러온다(런 종료·템플릿 저장 시 상위가 올린다). */
  refreshKey: number;
  /** 템플릿 재생(회수) 시작 — 상위가 templateId 로 새 라이브 런을 띄운다. */
  onReplay: (templateId: string) => void;
  /** 진행 중 라이브 런이 있어 새 재생을 시작할 수 없을 때 true. */
  replayDisabled: boolean;
}

type PanelTab = 'history' | 'templates';

/**
 * 실행 이력 · 템플릿 패널 — 라이브 실행과 공존하는 하단 영역.
 *
 * 이력 탭은 이 워크플로우의 과거 런(시각·상태·요약)을 나열하고, 행을 펼치면 상세(로그/결과)를
 * 지연 로드해 라이브 사이드패널과 같은 렌더러로 보여준다. 템플릿 탭은 저장된 재생 묶음을
 * 나열하고 '재생/회수'·삭제를 제공한다. 모든 네트워크 실패는 조용히 문구로 표시한다.
 */
export function AgentRunsPanel({
  agentId,
  refreshKey,
  onReplay,
  replayDisabled,
}: AgentRunsPanelProps) {
  const [tab, setTab] = useState<PanelTab>('history');
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [templates, setTemplates] = useState<RunTemplate[] | null>(null);
  const [templatesError, setTemplatesError] = useState<string | null>(null);

  const loadRuns = useCallback(async (): Promise<void> => {
    setRunsError(null);
    try {
      setRuns(await fetchRuns({ agentId, limit: 20 }));
    } catch (err) {
      setRunsError(messageOf(err));
      setRuns([]);
    }
  }, [agentId]);

  const loadTemplates = useCallback(async (): Promise<void> => {
    setTemplatesError(null);
    try {
      setTemplates(await fetchTemplates(agentId));
    } catch (err) {
      setTemplatesError(messageOf(err));
      setTemplates([]);
    }
  }, [agentId]);

  useEffect(() => {
    void loadRuns();
    void loadTemplates();
  }, [loadRuns, loadTemplates, refreshKey]);

  return (
    <section className="border-border bg-surface flex flex-col overflow-hidden rounded-[var(--radius-lg)] border shadow-[var(--shadow-card)]">
      <Tabs value={tab} onValueChange={(v) => setTab(v as PanelTab)} className="flex flex-col">
        <div className="border-border flex items-center justify-between gap-2 border-b pr-2">
          <TabsList className="border-0 px-3 pt-1">
            <TabsTrigger value="history" className="gap-1.5">
              <RiHistoryLine size={14} aria-hidden />
              실행 이력
              {runs ? (
                <span className="text-foreground-tertiary ml-1 text-[10px] tabular-nums">
                  {runs.length}
                </span>
              ) : null}
            </TabsTrigger>
            <TabsTrigger value="templates">
              템플릿
              {templates ? (
                <span className="text-foreground-tertiary ml-1.5 text-[10px] tabular-nums">
                  {templates.length}
                </span>
              ) : null}
            </TabsTrigger>
          </TabsList>
          <Button
            size="sm"
            variant="ghost"
            aria-label="새로고침"
            onClick={() => {
              void loadRuns();
              void loadTemplates();
            }}
          >
            <RiRefreshLine size={14} aria-hidden />
          </Button>
        </div>

        <TabsContent value="history" className="max-h-[420px] overflow-y-auto p-3">
          <RunHistory runs={runs} error={runsError} />
        </TabsContent>

        <TabsContent value="templates" className="max-h-[420px] overflow-y-auto p-3">
          <TemplateList
            templates={templates}
            error={templatesError}
            replayDisabled={replayDisabled}
            onReplay={onReplay}
            onDeleted={loadTemplates}
          />
        </TabsContent>
      </Tabs>
    </section>
  );
}

// ── 실행 이력 ────────────────────────────────────────────────────────

function RunHistory({ runs, error }: { runs: RunSummary[] | null; error: string | null }) {
  if (error) return <Notice tone="danger">{error}</Notice>;
  if (runs === null) return <Notice>실행 이력을 불러오는 중…</Notice>;
  if (runs.length === 0) return <Notice>아직 실행 이력이 없습니다.</Notice>;
  return (
    <ul className="flex flex-col gap-1.5">
      {runs.map((run) => (
        <RunRow key={run.id} run={run} />
      ))}
    </ul>
  );
}

function RunRow({ run }: { run: RunSummary }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle(): Promise<void> {
    const next = !open;
    setOpen(next);
    if (next && detail === null && !loading) {
      setLoading(true);
      setError(null);
      try {
        setDetail(await fetchRunDetail(run.id));
      } catch (err) {
        setError(messageOf(err));
      } finally {
        setLoading(false);
      }
    }
  }

  return (
    <li className="border-border overflow-hidden rounded-[var(--radius-md)] border">
      <button
        type="button"
        onClick={() => void toggle()}
        aria-expanded={open}
        className="hover:bg-muted/50 flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors"
      >
        <StatusBadge status={run.status} />
        <span className="min-w-0 flex-1">
          <span className="text-foreground block truncate text-[length:var(--text-body-sm)] font-medium">
            {run.resultSummary?.trim() || '(결과 요약 없음)'}
          </span>
          <span className="text-foreground-tertiary block text-[11px] tabular-nums">
            {run.startedAt ? formatDateTime(run.startedAt) : '시작 시각 미상'}
          </span>
        </span>
        <RiArrowDownSLine
          size={16}
          aria-hidden
          className={cn(
            'text-foreground-tertiary shrink-0 transition-transform',
            open ? 'rotate-180' : '',
          )}
        />
      </button>

      {open ? (
        <div className="border-border bg-muted/20 border-t px-3 py-3">
          {loading ? (
            <p className="text-foreground-tertiary flex items-center gap-1.5 text-[12px]">
              <RiLoader4Line size={13} className="animate-spin" aria-hidden />
              상세를 불러오는 중…
            </p>
          ) : error ? (
            <p className="text-danger text-[12px]">{error}</p>
          ) : detail ? (
            <RunDetailBody detail={detail} />
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function RunDetailBody({ detail }: { detail: RunDetail }) {
  const failed = detail.status === 'failed';
  const logs = detail.logs.map((l, i) => ({ id: `rl-${i}`, message: l.message, level: l.level }));
  return (
    <div className="flex flex-col gap-4">
      <LiveResult
        result={resultText(detail)}
        error={failed ? (detail.resultSummary ?? '실행이 실패했습니다.') : null}
        transactions={null}
      />
      <div className="flex flex-col gap-1.5">
        <p className="text-foreground-secondary text-[11px] font-semibold">로그</p>
        <LiveLogList logs={logs} />
      </div>
    </div>
  );
}

// ── 템플릿 ───────────────────────────────────────────────────────────

interface TemplateListProps {
  templates: RunTemplate[] | null;
  error: string | null;
  replayDisabled: boolean;
  onReplay: (templateId: string) => void;
  onDeleted: () => Promise<void> | void;
}

function TemplateList({
  templates,
  error,
  replayDisabled,
  onReplay,
  onDeleted,
}: TemplateListProps) {
  if (error) return <Notice tone="danger">{error}</Notice>;
  if (templates === null) return <Notice>템플릿을 불러오는 중…</Notice>;
  if (templates.length === 0) {
    return (
      <Notice>
        저장된 템플릿이 없습니다. 대화형 실행을 완료한 뒤 결과에서 &lsquo;템플릿으로 저장&rsquo;할
        수 있습니다.
      </Notice>
    );
  }
  return (
    <ul className="flex flex-col gap-1.5">
      {templates.map((t) => (
        <TemplateRow
          key={t.id}
          template={t}
          replayDisabled={replayDisabled}
          onReplay={onReplay}
          onDeleted={onDeleted}
        />
      ))}
    </ul>
  );
}

function TemplateRow({
  template,
  replayDisabled,
  onReplay,
  onDeleted,
}: {
  template: RunTemplate;
  replayDisabled: boolean;
  onReplay: (templateId: string) => void;
  onDeleted: () => Promise<void> | void;
}) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove(): Promise<void> {
    if (deleting) return;
    if (
      typeof window !== 'undefined' &&
      !window.confirm(`'${template.name}' 템플릿을 삭제할까요?`)
    ) {
      return;
    }
    setDeleting(true);
    setError(null);
    try {
      await deleteTemplate(template.id);
      await onDeleted();
    } catch (err) {
      setError(messageOf(err));
      setDeleting(false);
    }
  }

  return (
    <li className="border-border flex items-center gap-3 rounded-[var(--radius-md)] border px-3 py-2.5">
      <span className="min-w-0 flex-1">
        <span className="text-foreground block truncate text-[length:var(--text-body-sm)] font-medium">
          {template.name}
        </span>
        <span className="text-foreground-tertiary block text-[11px] tabular-nums">
          {formatDateTime(template.createdAt)}
        </span>
        {error ? <span className="text-danger mt-0.5 block text-[11px]">{error}</span> : null}
      </span>
      <div className="flex shrink-0 items-center gap-1.5">
        <Button
          size="sm"
          onClick={() => onReplay(template.id)}
          disabled={replayDisabled || deleting}
          title={replayDisabled ? '진행 중인 실행을 종료한 뒤 재생할 수 있습니다.' : undefined}
        >
          <RiPlayMiniLine size={14} aria-hidden />
          재생
        </Button>
        <Button
          size="sm"
          variant="ghost"
          aria-label="템플릿 삭제"
          onClick={() => void remove()}
          disabled={deleting}
          className="text-danger hover:bg-danger/10 hover:text-danger"
        >
          {deleting ? (
            <RiLoader4Line size={14} className="animate-spin" aria-hidden />
          ) : (
            <RiDeleteBinLine size={14} aria-hidden />
          )}
        </Button>
      </div>
    </li>
  );
}

// ── 공통 ─────────────────────────────────────────────────────────────

const STATUS_STYLE: Record<string, { className: string; label: string }> = {
  running: { className: 'border-accent/30 bg-accent/10 text-accent', label: '실행 중' },
  waiting_input: { className: 'border-warning/30 bg-warning/10 text-warning', label: '개입 대기' },
  succeeded: { className: 'border-success/30 bg-success/10 text-success', label: '완료' },
  failed: { className: 'border-danger/30 bg-danger/10 text-danger', label: '실패' },
  cancelled: { className: 'border-border bg-muted text-muted-foreground', label: '종료됨' },
};

function StatusBadge({ status }: { status: RunStatus }) {
  const style = STATUS_STYLE[status] ?? {
    className: 'border-border bg-muted text-muted-foreground',
    label: status,
  };
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[10px] font-bold tracking-wider',
        style.className,
      )}
    >
      {style.label}
    </span>
  );
}

function Notice({
  children,
  tone = 'muted',
}: {
  children: React.ReactNode;
  tone?: 'muted' | 'danger';
}) {
  return (
    <p
      className={cn(
        'py-6 text-center text-[12px]',
        tone === 'danger' ? 'text-danger' : 'text-foreground-tertiary',
      )}
    >
      {children}
    </p>
  );
}

function messageOf(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return '세션이 만료되었습니다. 다시 로그인해 주세요.';
    return err.message;
  }
  return '요청을 처리하지 못했습니다.';
}
