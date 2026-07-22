'use client';

import { useCallback, useEffect, useState } from 'react';
import { RiAlertLine, RiArrowDownSLine, RiHistoryLine } from '@remixicon/react';
import { PageHeader } from '@/components/ui/page-header';
import { Spinner } from '@/components/ui/spinner';
import { FilterPill } from '@/components/ui/filter-pill';
import { ListStatePanel, LockedEmptyState } from '@/components/ui/list-state';
import { ListToolbar } from '@/components/ui/list-toolbar';
import { Pagination } from '@/components/ui/pagination';
import { RunStatusBadge } from '@/components/ui/run-status-badge';
import { SelectItem } from '@/components/ui/select-dropdown';
import { TableCard, tableRowClass } from '@/components/ui/table-card';
import { cn } from '@/lib/utils';
import { api, ApiError } from '@/lib/api/client';
import { Td, Th } from '@/components/ui/table-cell';
import { useListParams } from '@/hooks/use-list-params';
import { usePagedQuery, type Page } from '@/hooks/use-paged-query';
import { PERMISSIONS } from '@/lib/auth/permissions';
import { useCan } from '@/components/permissions/perm-gate';
import { formatDateTime } from '@/lib/data/format';
import type { Agent } from '@/lib/data/agents';
import {
  extractSelections,
  fetchRunDetail,
  fetchRuns,
  resultText,
  type ChatSelection,
  type RunDetail,
  type RunLogEntry,
  type RunStatus,
  type RunSummary,
} from '@/lib/live/runs-api';

const PAGE_SIZE = 50;

/** 워크플로우 id → 사람이 읽는 라벨(없으면 raw id). */
const WORKFLOW_LABEL: Record<string, string> = {
  'demo-echo': '데모 에코',
  'expense-card-chat': '법인카드 경비 (대화형)',
};

function agentLabel(agentId: string): string {
  return WORKFLOW_LABEL[agentId] ?? agentId;
}

/** 상태 필터 옵션 — DB에 실제로 저장되는 런 상태만(RunStatusBadge 라벨과 동일 문구). */
const STATUS_FILTER_OPTIONS: { value: RunStatus; label: string }[] = [
  { value: 'running', label: '실행 중' },
  { value: 'succeeded', label: '완료' },
  { value: 'failed', label: '실패' },
  { value: 'cancelled', label: '종료됨' },
];

interface AgentOption {
  value: string;
  label: string;
}

/**
 * 에이전트 실행 로깅 테이블 — 어떤 에이전트를 누가 언제 돌렸고 어떤 상태로 끝났는지,
 * 실패 시 어느 단계에서 멈췄는지. logs:read(admin+)만 열람(관리자는 전체, 백엔드가 스코프).
 * 행을 펼치면 단계별 로그 + 입력값(selections/chat) + 실패 단계를 상세로 지연 로드한다.
 */
export function LogsClient() {
  const canRead = useCan(PERMISSIONS.LOGS_READ);
  // 이 화면은 텍스트 검색이 없다 — searchInput 은 쓰지 않는다.
  const { filters, setFilter, page, setPage, isFiltered, reset } = useListParams({
    filters: { status: 'all', agent: 'all' },
  });
  const [agentOptions, setAgentOptions] = useState<AgentOption[]>([]);

  // 필터 칩용 에이전트 옵션 — 실패해도 상태 필터만 남기고 무해히 강등한다.
  useEffect(() => {
    if (!canRead) return;
    let cancelled = false;
    (async () => {
      try {
        const agents = await api.get<Agent[]>('/agents');
        if (cancelled) return;
        const seen = new Set<string>();
        const options: AgentOption[] = [];
        for (const a of agents) {
          if (!a.workflowId || seen.has(a.workflowId)) continue;
          seen.add(a.workflowId);
          options.push({ value: a.workflowId, label: a.name });
        }
        setAgentOptions(options);
      } catch {
        setAgentOptions([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [canRead]);

  // 필터를 클로저에 넣은 fetcher — 정체성이 바뀌면 usePagedQuery 가 재조회한다.
  // fetchRuns 의 {runs,total} 을 정규형 Page{rows,total} 로 어댑트.
  const fetchPage = useCallback(
    async ({ limit, offset }: { limit: number; offset: number }): Promise<Page<RunSummary>> => {
      const res = await fetchRuns({
        limit,
        offset,
        agentId: filters.agent === 'all' ? undefined : filters.agent,
        status: filters.status === 'all' ? undefined : filters.status,
      });
      return { rows: res.runs, total: res.total };
    },
    [filters.agent, filters.status],
  );

  // 권한 없으면 fetcher null — 요청 자체를 하지 않는다(권한 게이트).
  const { rows, total, phase, error, reload } = usePagedQuery(canRead ? fetchPage : null, {
    page,
    pageSize: PAGE_SIZE,
    setPage, // 스테일 URL page 오버플로 시 마지막 페이지로 클램프
  });

  return (
    <div className="animate-page-enter flex flex-col gap-8">
      <PageHeader
        caption="운영"
        title="로깅"
        description="에이전트 사용 내역입니다. 어떤 에이전트를 누가 언제 실행했고 어떤 상태로 끝났는지, 실패했다면 어느 단계에서 멈췄는지 확인할 수 있습니다."
      />

      {!canRead ? (
        <LockedEmptyState description="실행 로깅은 관리자 이상만 열람할 수 있습니다." />
      ) : (
        <>
          <ListToolbar isFiltered={isFiltered} onReset={reset}>
            <FilterPill
              label="상태"
              ariaLabel="상태 필터"
              value={filters.status}
              active={filters.status !== 'all'}
              onValueChange={(v) => setFilter('status', v)}
            >
              <SelectItem value="all">전체</SelectItem>
              {STATUS_FILTER_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </FilterPill>

            <FilterPill
              label="에이전트"
              ariaLabel="에이전트 필터"
              value={filters.agent}
              active={filters.agent !== 'all'}
              onValueChange={(v) => setFilter('agent', v)}
            >
              <SelectItem value="all">전체</SelectItem>
              {agentOptions.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </FilterPill>
          </ListToolbar>

          <ListStatePanel
            phase={phase}
            error={error}
            loadingLabel="실행 내역을 불러오는 중…"
            errorTitle="실행 내역을 불러오지 못했습니다"
            onRetry={reload}
            isEmpty={rows.length === 0}
            empty={{
              icon: <RiHistoryLine size={18} aria-hidden />,
              title: '실행 내역이 없습니다',
              description: isFiltered
                ? '검색·필터 조건에 맞는 실행 내역이 없습니다.'
                : '아직 기록된 에이전트 실행이 없습니다.',
            }}
          >
            <div className="flex flex-col gap-3">
              <TableCard
                minWidth={900}
                head={
                  <tr>
                    <Th className="w-6">
                      <span className="sr-only">펼치기</span>
                    </Th>
                    <Th>에이전트</Th>
                    <Th>실행자</Th>
                    <Th>실행시각</Th>
                    <Th>상태</Th>
                    <Th>실패 단계</Th>
                    <Th>결과 요약</Th>
                  </tr>
                }
              >
                {rows.map((run) => (
                  <RunRow key={run.id} run={run} />
                ))}
              </TableCard>

              <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
            </div>
          </ListStatePanel>
        </>
      )}
    </div>
  );
}

// ── 행(+ 지연 로드 상세) ─────────────────────────────────────────────

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
        setError(err instanceof ApiError ? err.message : '상세를 불러오지 못했습니다.');
      } finally {
        setLoading(false);
      }
    }
  }

  const executor = run.userDisplayName || run.omnisolUserid || run.userId || '—';

  return (
    <>
      <tr
        onClick={() => void toggle()}
        aria-expanded={open}
        className={cn(tableRowClass, 'cursor-pointer')}
      >
        <Td className="text-foreground-tertiary">
          <RiArrowDownSLine
            size={16}
            aria-hidden
            className={cn('transition-transform', open ? 'rotate-180' : '')}
          />
        </Td>
        <Td>
          <span className="text-foreground font-medium">{agentLabel(run.agentId)}</span>
          <span className="text-muted-foreground block font-mono text-[11px]">{run.agentId}</span>
        </Td>
        <Td className="text-muted-foreground text-xs">{executor}</Td>
        <Td className="text-muted-foreground text-xs tabular-nums">
          {run.startedAt ? formatDateTime(run.startedAt) : '—'}
        </Td>
        <Td>
          <RunStatusBadge status={run.status} />
        </Td>
        <Td className="text-xs">
          {run.failedStep ? (
            <span className="text-danger inline-flex items-center gap-1 font-medium">
              <RiAlertLine size={13} aria-hidden />
              {run.failedStep}
            </span>
          ) : (
            <span className="text-foreground-tertiary">—</span>
          )}
        </Td>
        <Td className="text-muted-foreground max-w-[22rem]">
          <span className="block truncate" title={run.resultSummary ?? undefined}>
            {run.resultSummary?.trim() || '—'}
          </span>
        </Td>
      </tr>

      {open ? (
        <tr className="bg-muted/20">
          <td colSpan={7} className="px-4 py-4">
            {loading ? (
              <p className="text-foreground-tertiary flex items-center gap-1.5 text-[12px]">
                <Spinner size={13} />
                상세를 불러오는 중…
              </p>
            ) : error ? (
              <p className="text-danger text-[12px]">{error}</p>
            ) : detail ? (
              <RunDetailBody detail={detail} />
            ) : null}
          </td>
        </tr>
      ) : null}
    </>
  );
}

function RunDetailBody({ detail }: { detail: RunDetail }) {
  const result = resultText(detail);
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="flex flex-col gap-4">
        {detail.failedStep ? (
          <div className="border-danger/30 bg-danger/10 text-danger flex items-start gap-2 rounded-[var(--radius-md)] border px-3 py-2.5">
            <RiAlertLine size={15} aria-hidden className="mt-0.5 shrink-0" />
            <p className="text-[length:var(--text-body-sm)]">
              <span className="font-semibold">실패 단계:</span> {detail.failedStep}
            </p>
          </div>
        ) : null}

        {result?.trim() ? (
          <div className="flex flex-col gap-1.5">
            <p className="text-foreground-secondary text-[11px] font-semibold">결과</p>
            <p className="text-foreground text-[length:var(--text-body-sm)] leading-relaxed">
              {result}
            </p>
          </div>
        ) : null}

        <div className="flex flex-col gap-1.5">
          <p className="text-foreground-secondary text-[11px] font-semibold">입력값</p>
          <RunInputsView detail={detail} />
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <p className="text-foreground-secondary text-[11px] font-semibold">단계별 로그</p>
        <RunLogLines logs={detail.logs} />
      </div>
    </div>
  );
}

// ── 입력값(선택/대화) ────────────────────────────────────────────────

function RunInputsView({ detail }: { detail: RunDetail }) {
  const selections = extractSelections(detail);
  // 백엔드는 대화를 `messages`(문자열 배열)로 준다. 과거/타 워크플로우의 `chat` 키도 수용.
  const chat = detail.inputs?.messages ?? detail.inputs?.chat;
  const chatItems = Array.isArray(chat) ? chat : [];

  if (selections.length === 0 && chatItems.length === 0) {
    return <p className="text-foreground-tertiary text-[12px]">기록된 입력값이 없습니다.</p>;
  }

  return (
    <div className="flex flex-col gap-2">
      {selections.map((sel, i) => (
        <SelectionCard key={`sel-${i}`} selection={sel} />
      ))}
      {chatItems.map((item, i) => (
        <ChatLine key={`chat-${i}`} item={item} />
      ))}
    </div>
  );
}

function SelectionCard({ selection }: { selection: ChatSelection }) {
  const entries = Object.entries(selection);
  return (
    <div className="border-border bg-surface rounded-[var(--radius-sm)] border px-3 py-2">
      {entries.length === 0 ? (
        <span className="text-foreground-tertiary text-[11px]">(빈 선택)</span>
      ) : (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
          {entries.map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="text-foreground-tertiary font-mono text-[11px]">{key}</dt>
              <dd className="text-foreground-secondary text-[11px] break-words">
                {renderValue(value)}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function ChatLine({ item }: { item: unknown }) {
  if (item && typeof item === 'object') {
    const o = item as Record<string, unknown>;
    const role = typeof o.role === 'string' ? o.role : null;
    const content = typeof o.content === 'string' ? o.content : null;
    if (role || content) {
      return (
        <p className="text-foreground-secondary text-[11px] leading-relaxed">
          {role ? <span className="text-foreground-tertiary font-mono">{role}: </span> : null}
          {content ?? renderValue(item)}
        </p>
      );
    }
  }
  return (
    <p className="text-foreground-secondary font-mono text-[11px] break-words">
      {renderValue(item)}
    </p>
  );
}

function renderValue(value: unknown): string {
  if (value == null) return '—';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

// ── 단계별 로그 ──────────────────────────────────────────────────────

const LOG_TONE: Record<string, string> = {
  info: 'text-muted-foreground bg-muted',
  ok: 'text-success bg-success/10',
  warn: 'text-warning bg-warning/10',
  error: 'text-danger bg-danger/10',
};

const LOG_LABEL: Record<string, string> = {
  info: 'INFO',
  ok: 'OK',
  warn: 'WARN',
  error: 'ERR',
};

function RunLogLines({ logs }: { logs: readonly RunLogEntry[] }) {
  if (logs.length === 0) {
    return <p className="text-foreground-tertiary text-[12px]">기록된 로그가 없습니다.</p>;
  }
  return (
    <ul className="border-border bg-surface flex max-h-72 flex-col gap-0.5 overflow-y-auto rounded-[var(--radius-md)] border p-2">
      {logs.map((log, i) => (
        <li key={i} className="flex items-start gap-2 px-1 py-0.5">
          <span
            className={cn(
              'mt-0.5 shrink-0 rounded px-1 py-0.5 font-mono text-[9px] font-bold',
              LOG_TONE[log.level] ?? LOG_TONE.info,
            )}
          >
            {LOG_LABEL[log.level] ?? log.level.toUpperCase()}
          </span>
          <p className="text-foreground-secondary min-w-0 flex-1 text-[11px] leading-snug break-words">
            {log.message}
          </p>
        </li>
      ))}
    </ul>
  );
}
