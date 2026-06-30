'use client';

import { RiCloseLine } from '@remixicon/react';
import type { ReactNode } from 'react';
import { Avatar } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { Chip } from '@/components/ui/chip-set';
import { formatDate, formatRelativeKorean } from '@/lib/data/format';
import { categoryById, memberById, phaseById, projectRefById, type Work } from '@/lib/data/works';
import { WorkPriorityChip, WorkStatusBadge } from './work-status-badge';

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[5rem_minmax(0,1fr)] items-center gap-3 py-2.5">
      <dt className="text-foreground-tertiary text-[length:var(--text-caption)]">{label}</dt>
      <dd className="text-foreground-secondary text-[length:var(--text-body-sm)]">{children}</dd>
    </div>
  );
}

function ColorChip({ color, name }: { color: string; name: string }) {
  return (
    <Chip shape="pill">
      <span className="h-2 w-2 rounded-full" style={{ background: color }} aria-hidden />
      {name}
    </Chip>
  );
}

export function WorkDetailPane({ work, onClose }: { work: Work; onClose: () => void }) {
  const project = projectRefById(work.projectId);
  const assignee = memberById(work.assigneeId);
  const phase = phaseById(work.phaseId);
  const category = categoryById(work.categoryId);

  return (
    <aside className="border-border bg-surface animate-page-enter rounded-[var(--radius-lg)] border p-5 shadow-[var(--shadow-card)] lg:sticky lg:top-6">
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-[length:var(--text-heading-sm)] leading-snug font-semibold tracking-tight">
          {work.title}
        </h2>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label="상세 닫기"
          className="-mt-1 -mr-1 shrink-0"
        >
          <RiCloseLine size={18} aria-hidden />
        </Button>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <WorkStatusBadge status={work.status} />
        <WorkPriorityChip priority={work.priority} />
      </div>

      <dl className="border-border-subtle divide-border-subtle mt-4 divide-y border-t border-b">
        <DetailRow label="프로젝트">
          {project ? <span className="text-foreground">{project.name}</span> : '—'}
        </DetailRow>
        <DetailRow label="담당자">
          {assignee ? (
            <span className="inline-flex items-center gap-2">
              <Avatar
                userId={assignee.id}
                hasAvatar={false}
                label={assignee.name}
                size={22}
                className="text-[10px]!"
              />
              <span className="text-foreground">{assignee.name}</span>
            </span>
          ) : (
            <span className="text-foreground-tertiary">미지정</span>
          )}
        </DetailRow>
        <DetailRow label="단계">
          {phase ? (
            <ColorChip color={phase.color} name={phase.name} />
          ) : (
            <span className="text-foreground-tertiary">—</span>
          )}
        </DetailRow>
        <DetailRow label="카테고리">
          {category ? (
            <ColorChip color={category.color} name={category.name} />
          ) : (
            <span className="text-foreground-tertiary">—</span>
          )}
        </DetailRow>
        <DetailRow label="마감">{work.dueAt ? formatDate(work.dueAt) : '마감 없음'}</DetailRow>
      </dl>

      <div className="mt-4">
        <p className="text-foreground-tertiary mb-1.5 text-[length:var(--text-caption)]">설명</p>
        <p className="text-foreground-secondary text-[length:var(--text-body-sm)] leading-relaxed">
          {work.description}
        </p>
      </div>

      <p className="text-foreground-tertiary mt-4 text-[length:var(--text-caption)]">
        {formatRelativeKorean(work.updatedAt)} 업데이트
      </p>
    </aside>
  );
}
