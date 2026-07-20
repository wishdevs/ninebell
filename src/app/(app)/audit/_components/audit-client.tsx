'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  RiCloseLine,
  RiErrorWarningLine,
  RiHistoryLine,
  RiLockLine,
  RiSearchLine,
} from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { PageHeader } from '@/components/ui/page-header';
import { Spinner } from '@/components/ui/spinner';
import { EmptyState } from '@/components/ui/empty-state';
import { StatusPill } from '@/components/ui/status-pill';
import { Pagination } from '@/components/ui/pagination';
import { Input } from '@/components/ui/input';
import { FilterPill } from '@/components/ui/filter-pill';
import { SelectItem } from '@/components/ui/select-dropdown';
import { ApiError, api, toApiError } from '@/lib/api/client';
import { Td, Th } from '@/components/ui/table-cell';
import { PERMISSIONS, type Role } from '@/lib/auth/permissions';
import { useCan } from '@/components/permissions/perm-gate';
import { MEMBER_ROLE_LABEL } from '@/lib/data/members';
import { formatDateTime } from '@/lib/data/format';

/** `GET /logs` 한 행 — 접속(감사) 로그 응답 계약(camelCase)과 1:1. */
interface AccessLog {
  id: string;
  /** 성공 시 매칭된 사용자 id. 미상(실패) 시 null. */
  userId: string | null;
  omnisolUserid: string;
  /** 사용자 표시명. 미상 시 빈 문자열일 수 있다. */
  displayName: string;
  /** 미상 사용자(실패)면 null. */
  role: Role | null;
  status: 'success' | 'failed';
  errorMsg: string | null;
  ip: string | null;
  userAgent: string | null;
  loggedAt: string;
}

const PAGE_SIZE = 50;

type Phase = 'loading' | 'ready' | 'error';

/**
 * 감사 로그 테이블 — 사용자 접속(로그인) 감시. logs:read(admin+) 권한이 없으면 접근 불가
 * 상태를 보여주고 fetch 자체를 하지 않는다. 권한이 있으면 `GET /logs?limit&offset`로
 * 최신순 페이지를 불러오고 번호형 페이지네이션으로 페이지를 이동한다.
 */
export function AuditClient() {
  const canRead = useCan(PERMISSIONS.LOGS_READ);
  const [rows, setRows] = useState<AccessLog[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [phase, setPhase] = useState<Phase>('loading');
  const [error, setError] = useState<ApiError | null>(null);
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'success' | 'failed'>('all');

  const loadPage = useCallback(
    async (target: number) => {
      setPhase('loading');
      setError(null);
      try {
        const params = new URLSearchParams({
          limit: String(PAGE_SIZE),
          offset: String((target - 1) * PAGE_SIZE),
        });
        if (query.trim()) params.set('q', query.trim());
        if (statusFilter !== 'all') params.set('status', statusFilter);
        const res = await api.get<{ logs: AccessLog[]; total: number }>(`/logs?${params}`);
        setRows(res.logs);
        setTotal(res.total);
        setPage(target);
        setPhase('ready');
      } catch (err: unknown) {
        setError(toApiError(err));
        setPhase('error');
      }
    },
    [query, statusFilter],
  );

  useEffect(() => {
    if (!canRead) return;
    const timer = setTimeout(() => loadPage(1), 250);
    return () => clearTimeout(timer);
  }, [canRead, loadPage]);

  const filterActive = query.trim() !== '' || statusFilter !== 'all';
  const resetFilters = () => {
    setQuery('');
    setStatusFilter('all');
  };

  return (
    <div className="animate-page-enter flex flex-col gap-8">
      <PageHeader
        caption="운영"
        title="감사"
        description="옴니솔 로그인 접속 기록입니다. 언제·누가·어디서 접속했는지와 성공·실패를 확인할 수 있습니다."
      />

      {!canRead ? (
        <EmptyState
          icon={<RiLockLine size={18} aria-hidden />}
          title="접근 권한이 없습니다"
          description="감사 로그는 관리자 이상만 열람할 수 있습니다."
        />
      ) : (
        <>
          <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
            <div className="relative w-full sm:w-72">
              <RiSearchLine
                size={16}
                aria-hidden
                className="text-foreground-tertiary pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2"
              />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="옴니솔 아이디 검색"
                aria-label="감사 로그 검색"
                className="h-9 rounded-full pl-9"
              />
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <FilterPill
                label="상태"
                ariaLabel="상태 필터"
                value={statusFilter}
                active={statusFilter !== 'all'}
                onValueChange={(v) => setStatusFilter(v as 'all' | 'success' | 'failed')}
              >
                <SelectItem value="all">전체</SelectItem>
                <SelectItem value="success">성공</SelectItem>
                <SelectItem value="failed">실패</SelectItem>
              </FilterPill>

              {filterActive ? (
                <button
                  type="button"
                  onClick={resetFilters}
                  className="text-foreground-tertiary hover:text-foreground-secondary inline-flex h-9 items-center gap-1 rounded-full px-2.5 text-[length:var(--text-body-sm)] font-medium transition-colors"
                >
                  <RiCloseLine size={14} aria-hidden />
                  초기화
                </button>
              ) : null}
            </div>
          </div>

          {phase === 'loading' ? (
            <div className="text-muted-foreground flex items-center justify-center gap-2 py-16 text-sm">
              <Spinner size={18} label="로그 불러오는 중" />
              접속 기록을 불러오는 중…
            </div>
          ) : phase === 'error' && rows.length === 0 ? (
            <EmptyState
              icon={<RiErrorWarningLine size={18} aria-hidden />}
              title="접속 기록을 불러오지 못했습니다"
              description={
                error?.status === 0 ? '서버에 연결할 수 없습니다.' : (error?.message ?? '')
              }
              action={
                <Button variant="secondary" size="sm" onClick={() => loadPage(1)}>
                  다시 시도
                </Button>
              }
            />
          ) : rows.length === 0 ? (
            <EmptyState
              icon={<RiHistoryLine size={18} aria-hidden />}
              title="접속 기록이 없습니다"
              description={
                filterActive
                  ? '검색·필터 조건에 맞는 접속 기록이 없습니다.'
                  : '아직 기록된 로그인 접속 이벤트가 없습니다.'
              }
            />
          ) : (
            <div className="flex flex-col gap-3">
              <div className="border-border bg-surface overflow-x-auto rounded-[var(--radius-lg)] border shadow-[var(--shadow-card)]">
                <table className="w-full min-w-[820px] text-left text-sm">
                  <thead className="border-border text-foreground-tertiary border-b text-[length:var(--text-caption)] font-medium tracking-[0.04em]">
                    <tr>
                      <Th>사용자</Th>
                      <Th>롤</Th>
                      <Th>접속시각</Th>
                      <Th>IP</Th>
                      <Th>상태</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((log) => (
                      <tr
                        key={log.id}
                        className="border-border-subtle row-hover border-b last:border-0"
                      >
                        <Td>
                          <div className="grid gap-0.5">
                            <p className="text-foreground font-medium">
                              {log.displayName || log.omnisolUserid}
                            </p>
                            <p className="text-muted-foreground font-mono text-xs">
                              {log.omnisolUserid}
                            </p>
                          </div>
                        </Td>

                        <Td className="text-muted-foreground text-xs">
                          {log.role ? MEMBER_ROLE_LABEL[log.role] : '—'}
                        </Td>

                        <Td className="text-muted-foreground text-xs tabular-nums">
                          {formatDateTime(log.loggedAt)}
                        </Td>

                        <Td className="text-muted-foreground font-mono text-xs">{log.ip || '—'}</Td>

                        <Td>
                          <div className="flex flex-col gap-0.5">
                            <StatusPill
                              label={log.status === 'success' ? '성공' : '실패'}
                              variant={log.status === 'success' ? 'success' : 'danger'}
                            />
                            {log.status === 'failed' && log.errorMsg ? (
                              <span
                                className="text-foreground-tertiary max-w-[16rem] truncate text-[11px]"
                                title={log.errorMsg}
                              >
                                {log.errorMsg}
                              </span>
                            ) : null}
                          </div>
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={loadPage} />
            </div>
          )}
        </>
      )}
    </div>
  );
}
