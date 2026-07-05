'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  RiAlertLine,
  RiArrowDownSLine,
  RiErrorWarningLine,
  RiHistoryLine,
  RiLockLine,
} from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { PageHeader } from '@/components/ui/page-header';
import { Spinner } from '@/components/ui/spinner';
import { EmptyState } from '@/components/ui/empty-state';
import { Pagination } from '@/components/ui/pagination';
import { RunStatusBadge } from '@/components/ui/run-status-badge';
import { cn } from '@/lib/utils';
import { ApiError, toApiError } from '@/lib/api/client';
import { Td, Th } from '@/components/ui/table-cell';
import { PERMISSIONS } from '@/lib/auth/permissions';
import { useCan } from '@/components/permissions/perm-gate';
import { formatDateTime } from '@/lib/data/format';
import {
  extractSelections,
  fetchRunDetail,
  fetchRuns,
  resultText,
  type ChatSelection,
  type RunDetail,
  type RunLogEntry,
  type RunSummary,
} from '@/lib/live/runs-api';

const PAGE_SIZE = 50;

type Phase = 'loading' | 'ready' | 'error';

/** 워크플로우 id → 사람이 읽는 라벨(없으면 raw id). */
const WORKFLOW_LABEL: Record<string, string> = {
  'demo-echo': '데모 에코',
  'expense-card-chat': '법인카드 경비 (대화형)',
};

function agentLabel(agentId: string): string {
  return WORKFLOW_LABEL[agentId] ?? agentId;
}

/**
 * 에이전트 실행 로깅 테이블 — 어떤 에이전트를 누가 언제 돌렸고 어떤 상태로 끝났는지,
 * 실패 시 어느 단계에서 멈췄는지. logs:read(admin+)만 열람(관리자는 전체, 백엔드가 스코프).
 * 행을 펼치면 단계별 로그 + 입력값(selections/chat) + 실패 단계를 상세로 지연 로드한다.
 */
export function LogsClient() {
  const canRead = useCan(PERMISSIONS.LOGS_READ);
  const [rows, setRows] = useState<RunSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [phase, setPhase] = useState<Phase>('loading');
  const [error, setError] = useState<ApiError | null>(null);

  const loadPage = useCallback(async (target: number) => {
    setPhase('loading');
    setError(null);
    try {
      const res = await fetchRuns({ limit: PAGE_SIZE, offset: (target - 1) * PAGE_SIZE });
      setRows(res.runs);
      setTotal(res.total);
      setPage(target);
      setPhase('ready');
    } catch (err: unknown) {
      setError(toApiError(err));
      setPhase('error');
    }
  }, []);

  useEffect(() => {
    if (canRead) loadPage(1);
  }, [canRead, loadPage]);

  return (
    <div className="animate-page-enter flex flex-col gap-8">
      <PageHeader
        caption="운영"
        title="로깅"
        description="에이전트 사용 내역입니다. 어떤 에이전트를 누가 언제 실행했고 어떤 상태로 끝났는지, 실패했다면 어느 단계에서 멈췄는지 확인할 수 있습니다."
      />

      {!canRead ? (
        <EmptyState
          icon={<RiLockLine size={18} aria-hidden />}
          title="접근 권한이 없습니다"
          description="실행 로깅은 관리자 이상만 열람할 수 있습니다."
        />
      ) : phase === 'loading' ? (
        <div className="text-muted-foreground flex items-center justify-center gap-2 py-16 text-sm">
          <Spinner size={18} label="로그 불러오는 중" />
          실행 내역을 불러오는 중…
        </div>
      ) : phase === 'error' && rows.length === 0 ? (
        <EmptyState
          icon={<RiErrorWarningLine size={18} aria-hidden />}
          title="실행 내역을 불러오지 못했습니다"
          description={error?.status === 0 ? '서버에 연결할 수 없습니다.' : (error?.message ?? '')}
          action={
            <Button variant="secondary" size="sm" onClick={() => loadPage(1)}>
              다시 시도
            </Button>
          }
        />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<RiHistoryLine size={18} aria-hidden />}
          title="실행 내역이 없습니다"
          description="아직 기록된 에이전트 실행이 없습니다."
        />
      ) : (
        <div className="flex flex-col gap-3">
          <div className="border-border bg-surface overflow-x-auto rounded-[var(--radius-lg)] border shadow-[var(--shadow-card)]">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="border-border text-foreground-tertiary border-b text-[length:var(--text-caption)] font-medium tracking-[0.04em]">
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
              </thead>
              <tbody>
                {rows.map((run) => (
                  <RunRow key={run.id} run={run} />
                ))}
              </tbody>
            </table>
          </div>

          <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={loadPage} />
        </div>
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
        className="border-border-subtle row-hover cursor-pointer border-b last:border-0"
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

