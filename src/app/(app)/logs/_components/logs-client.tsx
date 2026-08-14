'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  RiAlertLine,
  RiArrowDownSLine,
  RiCheckLine,
  RiFileCopyLine,
  RiHistoryLine,
} from '@remixicon/react';
import { Button } from '@/components/ui/button';
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

/**
 * 워크플로우 id → 표기 메타. GET /agents 가 단일 라벨 소스다(하드코딩 맵 제거) —
 * 로드 실패/미등록 워크플로우(demo-echo 등)는 매핑이 없어 원문 id 폴백으로 강등된다.
 */
interface AgentMeta {
  /** 한글 에이전트 명(agents.name). */
  name: string;
  /** 소속 그룹명 — null 이면 단독 에이전트. */
  groupName: string | null;
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
  const [agentIndex, setAgentIndex] = useState<Record<string, AgentMeta>>({});

  // 행 라벨·필터 옵션 공용 워크플로우 매핑 — 실패해도 상태 필터만 남기고 무해히 강등한다.
  useEffect(() => {
    if (!canRead) return;
    let cancelled = false;
    (async () => {
      try {
        const agents = await api.get<Agent[]>('/agents');
        if (cancelled) return;
        const index: Record<string, AgentMeta> = {};
        for (const a of agents) {
          if (!a.workflowId || index[a.workflowId]) continue;
          index[a.workflowId] = { name: a.name, groupName: a.group?.name ?? null };
        }
        setAgentIndex(index);
      } catch {
        setAgentIndex({});
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [canRead]);

  // 필터 칩용 옵션 — "그룹명 > 한글명"(단독은 이름만), 그룹 순 → 이름 순 정렬.
  const agentOptions = useMemo<AgentOption[]>(
    () =>
      Object.entries(agentIndex)
        .sort(([, a], [, b]) => {
          if (!!a.groupName !== !!b.groupName) return a.groupName ? -1 : 1; // 그룹 있는 항목 먼저
          const byGroup = (a.groupName ?? '').localeCompare(b.groupName ?? '', 'ko');
          if (byGroup !== 0) return byGroup;
          return a.name.localeCompare(b.name, 'ko');
        })
        .map(([workflowId, meta]) => ({
          value: workflowId,
          label: meta.groupName ? `${meta.groupName} > ${meta.name}` : meta.name,
        })),
    [agentIndex],
  );

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
                  <RunRow key={run.id} run={run} meta={agentIndex[run.agentId]} />
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

function RunRow({ run, meta }: { run: RunSummary; meta?: AgentMeta }) {
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
          {meta ? (
            <>
              <span className="text-foreground font-medium">{meta.name}</span>
              <span className="text-foreground-secondary block text-[11px]">
                {meta.groupName ? `${meta.groupName} ` : null}
                <span className="text-muted-foreground font-mono">{run.agentId}</span>
              </span>
            </>
          ) : (
            // 매핑 없는 워크플로우(expense-card-chat·demo-echo 등)는 원문 id 한 줄만.
            <span className="text-foreground font-medium">{run.agentId}</span>
          )}
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
        <div className="flex items-center justify-between gap-2">
          <p className="text-foreground-secondary text-[11px] font-semibold">단계별 로그</p>
          <CopyLogsButton detail={detail} />
        </div>
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

/** 복사 성공/실패 피드백 유지 시간(ms). */
const COPY_FEEDBACK_MS = 1500;

/** 로그 줄 시각 "HH:MM:SS" — Asia/Seoul 고정(코드베이스 시간 표기 규칙과 동일). */
const LOG_TIME_FMT = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

/** 로그 ts(epoch ms) → "HH:MM:SS". 과거 런엔 ts 가 없으므로 없으면 null(방어 렌더). */
function formatLogTime(ts: number | undefined): string | null {
  if (typeof ts !== 'number' || !Number.isFinite(ts)) return null;
  return LOG_TIME_FMT.format(new Date(ts));
}

/**
 * 런 로그 전체를 사람이 읽는 플레인텍스트로 — 상단에 run id·워크플로우·상태·시작/종료,
 * 이어서 줄마다 [시각] [단계] 레벨 메시지(없는 필드는 생략).
 */
function buildLogText(detail: RunDetail): string {
  const head = [
    `run id: ${detail.id}`,
    `워크플로우: ${detail.agentId}`,
    `상태: ${detail.status}`,
    `시작: ${detail.startedAt ? formatDateTime(detail.startedAt) : '—'}`,
    `종료: ${detail.finishedAt ? formatDateTime(detail.finishedAt) : '—'}`,
  ];
  const lines = detail.logs.map((log) => {
    const time = formatLogTime(log.ts);
    return [
      time ? `[${time}]` : null,
      log.step ? `[${log.step}]` : null,
      LOG_LABEL[log.level] ?? log.level.toUpperCase(),
      log.message,
    ]
      .filter(Boolean)
      .join(' ');
  });
  return [...head, '─'.repeat(24), ...lines].join('\n');
}

type CopyState = 'idle' | 'copied' | 'failed';

/** 단계별 로그 복사 버튼 — 성공 시 1.5s '복사됨'(아이콘 전환), 실패도 조용히 삼키지 않는다. */
function CopyLogsButton({ detail }: { detail: RunDetail }) {
  const [state, setState] = useState<CopyState>('idle');
  const timerRef = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    },
    [],
  );

  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(buildLogText(detail));
      setState('copied');
    } catch {
      // 클립보드 미지원/권한 거부 — 짧은 안내 후 원복.
      setState('failed');
    }
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => setState('idle'), COPY_FEEDBACK_MS);
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      aria-live="polite"
      className={cn('h-6 gap-1 px-1.5 text-[11px]', state === 'failed' && 'text-danger')}
      onClick={() => void copy()}
    >
      {state === 'copied' ? (
        <RiCheckLine size={13} aria-hidden className="text-success" />
      ) : (
        <RiFileCopyLine size={13} aria-hidden />
      )}
      {state === 'copied' ? '복사됨' : state === 'failed' ? '복사 실패' : '복사'}
    </Button>
  );
}

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
      {logs.map((log, i) => {
        const time = formatLogTime(log.ts);
        return (
          <li key={i} className="flex items-start gap-2 px-1 py-0.5">
            {/* ts 는 BE additive 필드 — 과거 런엔 없으므로 있을 때만 표시(방어 렌더). */}
            {time ? (
              <span className="text-foreground-tertiary mt-0.5 shrink-0 font-mono text-[10px] tabular-nums">
                {time}
              </span>
            ) : null}
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
        );
      })}
    </ul>
  );
}
