import { cn } from '@/lib/utils';
import {
  WORK_PRIORITY_LABEL,
  WORK_STATUS_LABEL,
  type WorkPriority,
  type WorkStatus,
} from '@/lib/data/works';

/**
 * 업무 상태/우선순위 배지 — status-badge.tsx의 톤 클래스(반투명 배경 + 톤 텍스트)를
 * 그대로 따른다. 디자인 토큰만 사용하므로 라이트/다크 모두 안전하다.
 */

const STATUS_TONE: Record<WorkStatus, string> = {
  todo: 'bg-muted text-muted-foreground',
  in_progress: 'bg-info/10 text-info',
  review: 'bg-warning/10 text-warning',
  done: 'bg-success/10 text-success',
};

const PRIORITY_TONE: Record<WorkPriority, string> = {
  urgent: 'bg-danger/10 text-danger',
  high: 'bg-warning/10 text-warning',
  medium: 'bg-accent/10 text-accent',
  low: 'bg-muted text-muted-foreground',
};

const PILL =
  'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] leading-none font-semibold';

export function WorkStatusBadge({ status, className }: { status: WorkStatus; className?: string }) {
  return (
    <span className={cn(PILL, STATUS_TONE[status], className)}>{WORK_STATUS_LABEL[status]}</span>
  );
}

export function WorkPriorityChip({
  priority,
  className,
}: {
  priority: WorkPriority;
  className?: string;
}) {
  return (
    <span className={cn(PILL, PRIORITY_TONE[priority], className)}>
      {WORK_PRIORITY_LABEL[priority]}
    </span>
  );
}
