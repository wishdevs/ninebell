import { RiListCheck3 } from '@remixicon/react';
import { Avatar } from '@/components/ui/avatar';
import { EmptyState } from '@/components/ui/empty-state';
import { SectionCard } from '@/components/ui/section-card';
import { cn } from '@/lib/utils';
import { type Project } from '@/lib/data/projects';
import { WORK_STATUS_LABEL, WORKS, memberById, type WorkStatus } from '@/lib/data/works';
import { formatDate, NOW_ANCHOR } from '@/lib/data/format';

interface WorksTabProps {
  project: Project;
}

const STATUS_TONE: Record<WorkStatus, string> = {
  todo: 'bg-muted text-muted-foreground',
  in_progress: 'bg-info/10 text-info',
  review: 'bg-warning/10 text-warning',
  done: 'bg-success/10 text-success',
};

/**
 * 업무 탭 — 현재 프로젝트에 속한 업무 목록(제목·상태·담당자·마감).
 * 마감이 지난 미완료 업무는 마감일을 danger 톤으로 강조한다.
 */
export function WorksTab({ project }: WorksTabProps) {
  const works = WORKS.filter((work) => work.projectId === project.id);
  const now = NOW_ANCHOR.getTime();

  if (works.length === 0) {
    return (
      <EmptyState
        icon={<RiListCheck3 size={18} aria-hidden />}
        title="이 프로젝트에 등록된 업무가 없습니다"
        description="업무를 추가하면 진행 상황과 담당자가 여기에 표시됩니다."
      />
    );
  }

  return (
    <SectionCard caption="업무" title={`업무 ${works.length}건`} density="comfortable">
      <ul className="grid gap-0.5">
        {works.map((work) => {
          const assignee = memberById(work.assigneeId);
          const isOverdue =
            work.dueAt != null && work.status !== 'done' && new Date(work.dueAt).getTime() < now;
          const dueLabel = work.dueAt ? `마감 ${formatDate(work.dueAt)}` : '마감 없음';

          return (
            <li
              key={work.id}
              className="row-hover -mx-3 flex items-center gap-3 rounded-[var(--radius-md)] px-3 py-2.5"
            >
              <div className="min-w-0 flex-1">
                <p className="text-foreground truncate text-sm font-medium">{work.title}</p>
                <p className="text-muted-foreground mt-0.5 text-xs">
                  <span>{assignee ? assignee.name : '담당자 없음'}</span>
                  <span aria-hidden> · </span>
                  <span className={cn(isOverdue && 'text-danger font-medium')}>{dueLabel}</span>
                </p>
              </div>

              {assignee ? (
                <div className="hidden shrink-0 items-center gap-2 sm:flex">
                  <Avatar userId={assignee.id} hasAvatar={false} label={assignee.name} size={22} />
                </div>
              ) : null}

              <span
                className={cn(
                  'shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium',
                  STATUS_TONE[work.status],
                )}
              >
                {WORK_STATUS_LABEL[work.status]}
              </span>
            </li>
          );
        })}
      </ul>
    </SectionCard>
  );
}
