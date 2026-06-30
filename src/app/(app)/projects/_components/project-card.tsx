import Link from 'next/link';
import { Avatar } from '@/components/ui/avatar';
import { ChipSet, Chip } from '@/components/ui/chip-set';
import { StatusPill } from '@/components/ui/status-pill';
import {
  PROJECT_STATUS_LABEL,
  type Project,
  type ProjectStatus,
} from '@/lib/data/projects';
import { formatRelativeKorean } from '@/lib/data/format';
import { cn } from '@/lib/utils';

/** 아바타 스택에 펼쳐 보일 멤버 수 상한. 초과분은 +N 배지로 접는다. */
const MAX_AVATARS = 4;

/**
 * 상태 태그 — active/paused 는 토큰 톤 StatusPill, archived 는 중립(muted) 칩.
 * StatusPill 어휘에 muted 변형이 없으므로 보관 상태만 별도 렌더한다.
 */
function StatusTag({ status }: { status: ProjectStatus }) {
  const label = PROJECT_STATUS_LABEL[status];
  if (status === 'active') return <StatusPill label={label} variant="success" />;
  if (status === 'paused') return <StatusPill label={label} variant="warn" />;
  return (
    <span className="bg-muted text-muted-foreground inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium">
      {label}
    </span>
  );
}

/**
 * 프로젝트 카드. 클릭 시 /projects/{slug} 로 이동하며, 상단 색 강조 라인,
 * 상태 태그, 진행률 바, 업무 수, 멤버 아바타 스택, 모듈 칩을 담는다.
 */
export function ProjectCard({ project }: { project: Project }) {
  const {
    slug,
    name,
    description,
    status,
    color,
    progress,
    workCount,
    openWorkCount,
    members,
    modules,
    updatedAt,
  } = project;

  const shownMembers = members.slice(0, MAX_AVATARS);
  const overflow = members.length - shownMembers.length;

  return (
    <Link
      href={`/projects/${slug}`}
      className="card-interactive border-border bg-surface-raised shadow-[var(--shadow-card)] focus-visible:ring-accent focus-visible:ring-offset-background group relative flex h-full flex-col overflow-hidden rounded-[var(--radius-lg)] border outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
    >
      <span aria-hidden className="absolute inset-x-0 top-0 h-1" style={{ background: color }} />

      <div className="flex h-full flex-col gap-4 p-5 pt-6">
        <div className="flex items-start justify-between gap-3">
          <h3 className="group-hover:text-accent text-[length:var(--text-body-lg)] leading-snug font-semibold tracking-tight transition-colors">
            {name}
          </h3>
          <StatusTag status={status} />
        </div>

        <p className="text-foreground-secondary line-clamp-2 min-h-[2.75rem] text-sm leading-relaxed">
          {description}
        </p>

        <div className="grid gap-2">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">진행률</span>
            <span className="text-foreground-secondary font-medium tabular-nums">{progress}%</span>
          </div>
          <div className="bg-muted h-1.5 w-full overflow-hidden rounded-full">
            <div
              className="bg-accent h-full rounded-full"
              style={{ width: `${progress}%` }}
              role="progressbar"
              aria-valuenow={progress}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`${name} 진행률`}
            />
          </div>
          <p className="text-muted-foreground text-xs tabular-nums">
            열린 {openWorkCount} / 전체 {workCount}
          </p>
        </div>

        <div className="mt-auto flex flex-col gap-4">
          <ChipSet>
            {modules.map((module) => (
              <Chip key={module} shape="pill">
                {module}
              </Chip>
            ))}
          </ChipSet>

          <div className="border-border-subtle flex items-center justify-between border-t pt-4">
            <div className="flex items-center">
              {shownMembers.map((member, index) => (
                <Avatar
                  key={member.id}
                  userId={member.id}
                  hasAvatar={false}
                  label={member.name}
                  size={28}
                  className={cn('ring-surface-raised ring-2', index > 0 && '-ml-2')}
                />
              ))}
              {overflow > 0 ? (
                <span className="border-border bg-muted text-muted-foreground ring-surface-raised -ml-2 inline-flex h-7 w-7 items-center justify-center rounded-full border text-[10px] font-medium ring-2">
                  +{overflow}
                </span>
              ) : null}
            </div>
            <span className="text-muted-foreground text-xs">
              업데이트 {formatRelativeKorean(updatedAt)}
            </span>
          </div>
        </div>
      </div>
    </Link>
  );
}
