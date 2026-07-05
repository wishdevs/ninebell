'use client';

import { Avatar } from '@/components/ui/avatar';
import { formatDate, formatRelativeKorean, NOW_ANCHOR } from '@/lib/data/format';
import { memberById, phaseById, type Work } from '@/lib/data/works';
import { cn } from '@/lib/utils';
import { WorkPriorityChip, WorkStatusBadge } from './work-status-badge';

interface WorkTableProps {
  works: readonly Work[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

/**
 * 마감 표기 — 과거이면서 미완료면 "지연"(danger). 그 외 과거는 상대시간,
 * 미래는 절대 날짜로 표시한다. (formatRelativeKorean은 미래 날짜에 대해
 * "방금 전"을 반환하므로 마감 표시로는 부적절 → 미래는 formatDate 사용.)
 */
function dueMeta(work: Work): { label: string; overdue: boolean } {
  if (!work.dueAt) return { label: '마감 없음', overdue: false };
  const target = new Date(work.dueAt).getTime();
  const now = NOW_ANCHOR.getTime();
  const isPast = target < now;
  const overdue = isPast && work.status !== 'done';
  if (overdue) return { label: '지연', overdue: true };
  if (isPast) return { label: formatRelativeKorean(work.dueAt), overdue: false };
  return { label: formatDate(work.dueAt), overdue: false };
}

const TH = 'px-3 py-2 text-left font-medium';

export function WorkTable({ works, selectedId, onSelect }: WorkTableProps) {
  return (
    <div className="border-border bg-surface overflow-hidden rounded-[var(--radius-lg)] border shadow-[var(--shadow-card)]">
      <table className="w-full border-collapse text-[length:var(--text-body-sm)]">
        <thead>
          <tr className="border-border-subtle text-foreground-tertiary border-b text-[length:var(--text-caption)] tracking-[0.04em]">
            <th className={TH}>제목</th>
            <th className={TH}>상태</th>
            <th className={cn(TH, 'hidden sm:table-cell')}>우선순위</th>
            <th className={cn(TH, 'hidden md:table-cell')}>담당자</th>
            <th className={cn(TH, 'hidden lg:table-cell')}>단계</th>
            <th className={cn(TH, 'text-right')}>마감</th>
          </tr>
        </thead>
        <tbody>
          {works.map((work) => {
            const selected = work.id === selectedId;
            const assignee = memberById(work.assigneeId);
            const phase = phaseById(work.phaseId);
            const due = dueMeta(work);
            return (
              <tr
                key={work.id}
                onClick={() => onSelect(work.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onSelect(work.id);
                  }
                }}
                role="button"
                tabIndex={0}
                aria-pressed={selected}
                className={cn(
                  'row-hover border-border-subtle cursor-pointer border-b last:border-0',
                  'focus-visible:ring-accent/50 focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset',
                  selected && 'bg-surface-raised',
                )}
              >
                <td
                  className={cn(
                    'border-l-2 py-2.5 pr-3 pl-3',
                    selected ? 'border-accent' : 'border-transparent',
                  )}
                >
                  <span
                    className={cn(
                      'line-clamp-1 font-medium',
                      selected ? 'text-accent' : 'text-foreground',
                    )}
                  >
                    {work.title}
                  </span>
                </td>
                <td className="px-3 py-2.5">
                  <WorkStatusBadge status={work.status} />
                </td>
                <td className="hidden px-3 py-2.5 sm:table-cell">
                  <WorkPriorityChip priority={work.priority} />
                </td>
                <td className="text-foreground-secondary hidden px-3 py-2.5 md:table-cell">
                  {assignee ? (
                    <span className="inline-flex items-center gap-2">
                      <Avatar
                        userId={assignee.id}
                        hasAvatar={false}
                        label={assignee.name}
                        size={22}
                        className="text-[10px]!"
                      />
                      <span className="whitespace-nowrap">{assignee.name}</span>
                    </span>
                  ) : (
                    <span className="text-foreground-tertiary">미지정</span>
                  )}
                </td>
                <td className="hidden px-3 py-2.5 lg:table-cell">
                  {phase ? (
                    <span className="text-foreground-secondary inline-flex items-center gap-1.5 whitespace-nowrap">
                      <span
                        className="h-2 w-2 shrink-0 rounded-full"
                        style={{ background: phase.color }}
                        aria-hidden
                      />
                      {phase.name}
                    </span>
                  ) : (
                    <span className="text-foreground-tertiary">—</span>
                  )}
                </td>
                <td className="px-3 py-2.5 text-right whitespace-nowrap tabular-nums">
                  <span
                    className={cn(
                      due.overdue ? 'text-danger font-medium' : 'text-foreground-secondary',
                    )}
                  >
                    {due.label}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
