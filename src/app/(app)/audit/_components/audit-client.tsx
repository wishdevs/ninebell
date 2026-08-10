'use client';

import { useCallback } from 'react';
import { RiHistoryLine } from '@remixicon/react';
import { PageHeader } from '@/components/ui/page-header';
import { StatusPill } from '@/components/ui/status-pill';
import { Pagination } from '@/components/ui/pagination';
import { FilterPill } from '@/components/ui/filter-pill';
import { SelectItem } from '@/components/ui/select-dropdown';
import { SearchInput } from '@/components/ui/search-input';
import { ListToolbar } from '@/components/ui/list-toolbar';
import { TableCard, tableRowClass } from '@/components/ui/table-card';
import { ListStatePanel, LockedEmptyState } from '@/components/ui/list-state';
import { api } from '@/lib/api/client';
import { Td, Th } from '@/components/ui/table-cell';
import { useListParams } from '@/hooks/use-list-params';
import { usePagedQuery, type Page } from '@/hooks/use-paged-query';
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

/**
 * 감사 로그 테이블 — 사용자 접속(로그인) 감시. logs:read(admin+) 권한이 없으면 접근 불가
 * 상태를 보여주고 fetch 자체를 하지 않는다. 권한이 있으면 `GET /logs?limit&offset`로
 * 최신순 페이지를 불러오고 번호형 페이지네이션으로 페이지를 이동한다.
 * 파라미터·페칭·툴바·상태 3분기·테이블 셸은 공용 레일(useListParams·usePagedQuery·
 * ListToolbar·ListStatePanel·TableCard) 소유 — 이 파일은 도메인 셀 렌더만 가진다.
 */
export function AuditClient() {
  const canRead = useCan(PERMISSIONS.LOGS_READ);
  const {
    searchInput,
    setSearchInput,
    search,
    filters,
    setFilter,
    page,
    setPage,
    isFiltered,
    reset,
  } = useListParams({ filters: { status: 'all' } });

  // `GET /logs` 어댑터 — 응답 키는 items(신)·logs(구) 병기 중이라 관용 리더로 정규화
  // (배포 혼재 윈도 보호). 검색어/필터는 클로저로 — 정체성 변경 시 usePagedQuery 가 재조회.
  const fetchPage = useCallback(
    async ({ limit, offset }: { limit: number; offset: number }): Promise<Page<AccessLog>> => {
      const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
      if (search.trim()) params.set('q', search.trim());
      if (filters.status !== 'all') params.set('status', filters.status);
      const res = await api.get<{ items?: AccessLog[]; logs?: AccessLog[]; total: number }>(
        `/logs?${params}`,
      );
      return { rows: res.items ?? res.logs ?? [], total: res.total };
    },
    [search, filters.status],
  );

  const { rows, total, phase, error, reload } = usePagedQuery(canRead ? fetchPage : null, {
    page,
    pageSize: PAGE_SIZE,
    setPage, // 스테일 URL page 오버플로 시 마지막 페이지로 클램프
  });

  return (
    <div className="animate-page-enter flex flex-col gap-8">
      <PageHeader
        caption="운영"
        title="감사"
        description="옴니솔 로그인 접속 기록입니다. 언제·누가·어디서 접속했는지와 성공·실패를 확인할 수 있습니다."
      />

      {!canRead ? (
        <LockedEmptyState description="감사 로그는 관리자 이상만 열람할 수 있습니다." />
      ) : (
        <>
          <ListToolbar isFiltered={isFiltered} onReset={reset}>
            <SearchInput
              value={searchInput}
              onChange={setSearchInput}
              placeholder="옴니솔 아이디 검색"
              ariaLabel="감사 로그 검색"
            />
            <FilterPill
              label="상태"
              ariaLabel="상태 필터"
              value={filters.status}
              active={filters.status !== 'all'}
              onValueChange={(v) => setFilter('status', v)}
            >
              <SelectItem value="all">전체</SelectItem>
              <SelectItem value="success">성공</SelectItem>
              <SelectItem value="failed">실패</SelectItem>
            </FilterPill>
          </ListToolbar>

          <ListStatePanel
            phase={phase}
            error={error}
            loadingLabel="접속 기록을 불러오는 중…"
            errorTitle="접속 기록을 불러오지 못했습니다"
            onRetry={reload}
            isEmpty={rows.length === 0}
            empty={{
              icon: <RiHistoryLine size={18} aria-hidden />,
              title: '접속 기록이 없습니다',
              description: isFiltered
                ? '검색·필터 조건에 맞는 접속 기록이 없습니다.'
                : '아직 기록된 로그인 접속 이벤트가 없습니다.',
            }}
          >
            <div className="flex flex-col gap-3">
              <TableCard
                minWidth={820}
                ariaLabel="감사 로그"
                head={
                  <tr>
                    <Th>사용자</Th>
                    <Th>롤</Th>
                    <Th>접속시각</Th>
                    <Th>IP</Th>
                    <Th>상태</Th>
                  </tr>
                }
              >
                {rows.map((log) => (
                  <tr key={log.id} className={tableRowClass}>
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
              </TableCard>

              <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
            </div>
          </ListStatePanel>
        </>
      )}
    </div>
  );
}
