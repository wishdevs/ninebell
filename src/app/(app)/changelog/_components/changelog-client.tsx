'use client';

import { useCallback } from 'react';
import { RiGitCommitLine } from '@remixicon/react';
import { FilterPill } from '@/components/ui/filter-pill';
import { ListStatePanel } from '@/components/ui/list-state';
import { ListToolbar } from '@/components/ui/list-toolbar';
import { MarkdownContent } from '@/components/ui/markdown-content';
import { PageHeader } from '@/components/ui/page-header';
import { Pagination } from '@/components/ui/pagination';
import { SearchInput } from '@/components/ui/search-input';
import { SelectItem } from '@/components/ui/select-dropdown';
import { StatusPill } from '@/components/ui/status-pill';
import { usePermissions } from '@/hooks/use-permissions';
import { usePagedQuery, type Page } from '@/hooks/use-paged-query';
import { useListParams } from '@/hooks/use-list-params';
import { fetchChangelog, type ChangelogEntry, type ChangelogStatus } from '@/lib/api/changelog';
import { ROLES, roleAtLeast } from '@/lib/auth/permissions';
import { cn } from '@/lib/utils';

const PAGE_SIZE = 20;

/**
 * 버전 문자열이 릴리스 날짜를 그대로 담고 있는가(예: '2026.07.28' + releasedAt 2026-07-28).
 * 날짜식 버전을 쓰면 레일에 같은 날짜가 두 번 찍히므로, 이때만 날짜 줄을 숨긴다.
 * semver('v1.4.0') 처럼 날짜와 무관한 버전은 그대로 날짜를 함께 보여준다.
 */
function versionRepeatsDate(version: string, releasedAt: string): boolean {
  return version.replace(/\./g, '-') === releasedAt;
}

/**
 * 'yyyy-mm-dd' → '2026. 7. 28.'. 공용 formatDate 와 달리 Date 파싱을 거치지 않는다 —
 * 달력 날짜라 시간대와 무관하게 항상 같은 날짜를 찍어야 한다.
 */
function formatReleaseDate(ymd: string): string {
  const [y, m, d] = ymd.split('-');
  if (!y || !m || !d) return ymd;
  return `${y}. ${Number(m)}. ${Number(d)}.`;
}

/**
 * 변경사항(릴리스 노트) 타임라인 — 릴리스 단위 기록을 최신순으로 보여준다.
 * 조회는 로그인한 전원(백엔드가 일반 사용자에게는 released 만 반환). 릴리스는 파일
 * (backend/app/data/releases/*.md)에서 기동 시 적재되므로 화면은 읽기 전용이다(2026-09-02 —
 * 추가/수정/삭제 UI 제거). 관리자에게는 공개 상태 필터만 추가로 보인다.
 * 파라미터·페칭·툴바·상태 3분기는 공용 레일(useListParams·usePagedQuery·ListToolbar·
 * ListStatePanel) 소유 — 이 파일은 타임라인 렌더만 가진다.
 */
export function ChangelogClient() {
  const { role } = usePermissions();
  const isAdmin = roleAtLeast(role, ROLES.ADMIN);

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
  } = useListParams({ filters: { status: 'all', major: 'all' } });

  // 상태 필터는 관리자에게만 의미가 있다(일반 사용자는 서버가 released 로 고정).
  const statusFilter = (isAdmin ? filters.status : 'all') as ChangelogStatus | 'all';
  // 'all' = 필터 없음(undefined), 'only' = 주요 수정 포함 릴리스만.
  const majorFilter = filters.major === 'only' ? true : undefined;

  const fetchPage = useCallback(
    async ({ limit, offset }: { limit: number; offset: number }): Promise<Page<ChangelogEntry>> => {
      const { items, total } = await fetchChangelog({
        limit,
        offset,
        q: search,
        status: statusFilter,
        hasMajorFix: majorFilter,
      });
      return { rows: items, total };
    },
    [search, statusFilter, majorFilter],
  );

  const { rows, total, phase, error, reload } = usePagedQuery(fetchPage, {
    page,
    pageSize: PAGE_SIZE,
    setPage,
  });

  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-8">
      <PageHeader
        caption="변경 이력"
        title="변경사항"
        description="대시보드와 에이전트에 무엇이 추가·수정됐는지를 릴리스 단위로 기록합니다."
      />

      <ListToolbar isFiltered={isFiltered} onReset={reset}>
        <SearchInput
          value={searchInput}
          onChange={setSearchInput}
          placeholder="버전·제목·본문 검색"
          ariaLabel="변경사항 검색"
        />
        <FilterPill
          label="수정"
          ariaLabel="주요 수정 필터"
          value={filters.major}
          active={filters.major !== 'all'}
          onValueChange={(v) => setFilter('major', v)}
        >
          <SelectItem value="all">전체</SelectItem>
          <SelectItem value="only">주요 수정 포함</SelectItem>
        </FilterPill>
        {isAdmin ? (
          <FilterPill
            label="공개"
            ariaLabel="공개 상태 필터"
            value={filters.status}
            active={filters.status !== 'all'}
            onValueChange={(v) => setFilter('status', v)}
          >
            <SelectItem value="all">전체</SelectItem>
            <SelectItem value="released">배포됨</SelectItem>
            <SelectItem value="draft">미공개</SelectItem>
          </FilterPill>
        ) : null}
      </ListToolbar>

      <ListStatePanel
        phase={phase}
        error={error}
        loadingLabel="변경사항을 불러오는 중…"
        errorTitle="변경사항을 불러오지 못했습니다"
        onRetry={reload}
        isEmpty={rows.length === 0}
        empty={{
          icon: <RiGitCommitLine size={18} aria-hidden />,
          title: '기록된 변경사항이 없습니다',
          description: isFiltered
            ? '검색·필터 조건에 맞는 릴리스가 없습니다.'
            : '아직 공개된 변경 기록이 없습니다.',
        }}
      >
        <div className="flex flex-col gap-6">
          <ol className="flex flex-col">
            {rows.map((entry) => (
              <li
                key={entry.id}
                className="group grid gap-2 pb-6 last:pb-0 md:grid-cols-[7rem_1.25rem_1fr] md:gap-x-4"
              >
                {/* 버전·날짜 — 타임라인의 시각적 앵커. */}
                <div className="flex items-baseline gap-2 md:flex-col md:items-end md:gap-1 md:pt-4">
                  <p className="text-foreground font-mono text-[length:var(--text-body-sm)] font-semibold tabular-nums">
                    {entry.version}
                  </p>
                  {versionRepeatsDate(entry.version, entry.releasedAt) ? null : (
                    <p className="text-foreground-tertiary text-xs tabular-nums">
                      {formatReleaseDate(entry.releasedAt)}
                    </p>
                  )}
                </div>

                {/* 연결선 + 노드 — 마지막 항목은 선을 노드에서 끊는다. 주요 수정이 있는
                    릴리스는 노드 색으로 표시해 레일만 훑어도 눈에 띄게 한다. */}
                <div className="relative hidden justify-center md:flex" aria-hidden>
                  <span className="bg-border absolute inset-y-0 w-px group-last:h-6" />
                  <span
                    className={cn(
                      'ring-background relative mt-[1.15rem] size-2.5 shrink-0 rounded-full ring-4',
                      entry.hasMajorFix ? 'bg-warning' : 'bg-accent',
                    )}
                  />
                </div>

                <article className="border-border bg-surface rounded-[var(--radius-lg)] border p-5 transition-shadow hover:shadow-sm">
                  <header className="flex flex-wrap items-start justify-between gap-3">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <h2 className="text-foreground text-[length:var(--text-body)] font-semibold">
                        {entry.title}
                      </h2>
                      <StatusPill
                        label={entry.status === 'released' ? '배포됨' : '미공개'}
                        variant={entry.status === 'released' ? 'success' : 'info'}
                      />
                      {entry.hasMajorFix ? (
                        <StatusPill label="주요 수정 포함" variant="warn" />
                      ) : null}
                    </div>
                  </header>

                  <div className="border-border/60 mt-4 border-t pt-4">
                    <MarkdownContent content={entry.bodyMd} />
                  </div>
                </article>
              </li>
            ))}
          </ol>

          <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
        </div>
      </ListStatePanel>
    </div>
  );
}
