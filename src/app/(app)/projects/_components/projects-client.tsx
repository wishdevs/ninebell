'use client';

import { useMemo, useState } from 'react';
import { RiFolderOpenLine, RiAddLine } from '@remixicon/react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { PageHeader } from '@/components/ui/page-header';
import { PROJECTS, PROJECT_STATUS_LABEL, type ProjectStatus } from '@/lib/data/projects';
import { cn } from '@/lib/utils';
import { ProjectCard } from './project-card';

type Filter = ProjectStatus | 'all';

const FILTERS: readonly { value: Filter; label: string }[] = [
  { value: 'all', label: '전체' },
  { value: 'active', label: PROJECT_STATUS_LABEL.active },
  { value: 'paused', label: PROJECT_STATUS_LABEL.paused },
  { value: 'archived', label: PROJECT_STATUS_LABEL.archived },
];

export function ProjectsClient() {
  const [filter, setFilter] = useState<Filter>('all');

  const counts = useMemo<Record<Filter, number>>(() => {
    const base: Record<Filter, number> = {
      all: PROJECTS.length,
      active: 0,
      paused: 0,
      archived: 0,
    };
    for (const project of PROJECTS) base[project.status] += 1;
    return base;
  }, []);

  const visible = useMemo(
    () => (filter === 'all' ? PROJECTS : PROJECTS.filter((project) => project.status === filter)),
    [filter],
  );

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="프로젝트"
        description="팀이 진행 중인 프로젝트를 한눈에 살펴보고 상태별로 필터링하세요."
        action={
          <Button
            onClick={() =>
              toast.success('새 프로젝트 생성은 기본형 데모에서 비활성화되어 있습니다')
            }
          >
            <RiAddLine size={16} aria-hidden />새 프로젝트
          </Button>
        }
      />

      <div className="border-border bg-surface inline-flex flex-wrap items-center gap-1 self-start rounded-[var(--radius-lg)] border p-1">
        {FILTERS.map((option) => {
          const isActive = filter === option.value;
          return (
            <button
              key={option.value}
              type="button"
              onClick={() => setFilter(option.value)}
              aria-pressed={isActive}
              className={cn(
                'inline-flex items-center gap-2 rounded-[var(--radius-md)] px-3 py-1.5 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-accent text-accent-foreground shadow-sm'
                  : 'text-foreground-secondary hover:bg-muted hover:text-foreground',
              )}
            >
              {option.label}
              <span
                className={cn(
                  'inline-flex min-w-[1.25rem] justify-center rounded-full px-1.5 py-0.5 text-[11px] tabular-nums',
                  isActive
                    ? 'bg-accent-foreground/15 text-accent-foreground'
                    : 'bg-muted text-muted-foreground',
                )}
              >
                {counts[option.value]}
              </span>
            </button>
          );
        })}
      </div>

      {visible.length === 0 ? (
        <EmptyState
          icon={<RiFolderOpenLine size={20} aria-hidden />}
          title="해당 상태의 프로젝트가 없습니다"
          description="다른 상태 필터를 선택해 보세요."
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {visible.map((project) => (
            <ProjectCard key={project.id} project={project} />
          ))}
        </div>
      )}
    </div>
  );
}
