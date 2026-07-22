'use client';

import { RiAddLine, RiSearchLine } from '@remixicon/react';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { PageHeader } from '@/components/ui/page-header';
import { SearchInput } from '@/components/ui/search-input';
import {
  WORK_STATUS_LABEL,
  WORKS,
  findWork,
  memberById,
  projectRefById,
  type WorkStatus,
} from '@/lib/data/works';
import { cn } from '@/lib/utils';
import { WorkDetailPane } from './work-detail-pane';
import { WorkTable } from './work-table';

type StatusFilter = WorkStatus | 'all';

const STATUS_FILTERS: ReadonlyArray<{ value: StatusFilter; label: string }> = [
  { value: 'all', label: '전체' },
  { value: 'todo', label: WORK_STATUS_LABEL.todo },
  { value: 'in_progress', label: WORK_STATUS_LABEL.in_progress },
  { value: 'review', label: WORK_STATUS_LABEL.review },
  { value: 'done', label: WORK_STATUS_LABEL.done },
];

export function WorksClient() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return WORKS.filter((work) => {
      if (statusFilter !== 'all' && work.status !== statusFilter) return false;
      if (!q) return true;
      const haystack = [
        work.title,
        memberById(work.assigneeId)?.name ?? '',
        projectRefById(work.projectId)?.name ?? '',
      ]
        .join(' ')
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [statusFilter, query]);

  const counts = useMemo(() => {
    const base: Record<StatusFilter, number> = {
      all: WORKS.length,
      todo: 0,
      in_progress: 0,
      review: 0,
      done: 0,
    };
    for (const work of WORKS) base[work.status] += 1;
    return base;
  }, []);

  const selected = selectedId ? findWork(selectedId) : null;

  return (
    <div className="animate-page-enter space-y-6">
      <PageHeader
        title="업무"
        description="팀의 업무를 상태·담당자·마감 기준으로 추적합니다. 행을 선택하면 오른쪽에서 상세를 확인할 수 있습니다."
        action={
          <Button onClick={() => toast.info('새 업무 폼은 데모에서 비활성화되어 있습니다.')}>
            <RiAddLine size={16} aria-hidden />새 업무
          </Button>
        }
      />

      {/* 툴바 — 좌측 상태 필터 칩 · 우측 검색 */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="상태 필터">
          {STATUS_FILTERS.map((f) => {
            const active = statusFilter === f.value;
            return (
              <button
                key={f.value}
                type="button"
                onClick={() => setStatusFilter(f.value)}
                aria-pressed={active}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[length:var(--text-body-sm)] font-medium transition-colors',
                  'focus-visible:ring-accent/50 focus-visible:ring-2 focus-visible:outline-none',
                  active
                    ? 'border-accent bg-accent text-accent-foreground'
                    : 'border-border bg-surface text-foreground-secondary hover:bg-muted',
                )}
              >
                {f.label}
                <span
                  className={cn(
                    'text-[length:var(--text-caption)] tabular-nums',
                    active ? 'text-accent-foreground/80' : 'text-foreground-tertiary',
                  )}
                >
                  {counts[f.value]}
                </span>
              </button>
            );
          })}
        </div>

        <SearchInput
          value={query}
          onChange={setQuery}
          placeholder="제목·담당자·프로젝트 검색"
          ariaLabel="업무 검색"
          className="sm:w-64"
        />
      </div>

      {/* 본문 — 선택 시 2열(리스트 + 상세), 미선택 시 전체폭 리스트 */}
      <div className={cn('grid gap-5', selected && 'lg:grid-cols-[minmax(0,1fr)_360px]')}>
        <div className="min-w-0">
          {filtered.length === 0 ? (
            <EmptyState
              icon={<RiSearchLine size={18} aria-hidden />}
              title="조건에 맞는 업무가 없습니다"
              description="상태 필터를 바꾸거나 검색어를 지워 보세요."
            />
          ) : (
            <>
              <WorkTable works={filtered} selectedId={selectedId} onSelect={setSelectedId} />
              <p className="text-foreground-tertiary mt-3 text-[length:var(--text-caption)] tabular-nums">
                총 {WORKS.length}건 · 1–{filtered.length} / {filtered.length}
              </p>
            </>
          )}
        </div>

        {selected ? <WorkDetailPane work={selected} onClose={() => setSelectedId(null)} /> : null}
      </div>
    </div>
  );
}
