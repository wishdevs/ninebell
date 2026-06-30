import { Avatar } from '@/components/ui/avatar';
import { Chip, ChipSet } from '@/components/ui/chip-set';
import { SectionCard } from '@/components/ui/section-card';
import { type Project } from '@/lib/data/projects';
import { formatPercent } from '@/lib/data/format';

interface OverviewTabProps {
  project: Project;
}

/**
 * 개요 탭 — 진행 요약(진행률 바 + 카운트), 멤버 리스트, 활성 모듈 칩.
 */
export function OverviewTab({ project }: OverviewTabProps) {
  const stats = [
    { label: '진행률', value: formatPercent(project.progress, 0) },
    { label: '열린 업무', value: String(project.openWorkCount) },
    { label: '전체 업무', value: String(project.workCount) },
  ];

  return (
    <div className="grid gap-4">
      <SectionCard caption="진행 상황" title="진행 요약">
        <div
          className="bg-muted h-2 w-full overflow-hidden rounded-full"
          role="progressbar"
          aria-valuenow={project.progress}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="프로젝트 진행률"
        >
          <div
            className="h-full rounded-full transition-[width] duration-500"
            style={{ width: `${project.progress}%`, backgroundColor: project.color }}
          />
        </div>
        <dl className="grid grid-cols-3 gap-3">
          {stats.map(({ label, value }) => (
            <div
              key={label}
              className="border-border-subtle bg-surface-raised rounded-[var(--radius-md)] border p-3"
            >
              <dt className="text-foreground-tertiary text-xs">{label}</dt>
              <dd className="text-foreground mt-1 text-xl font-semibold tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
      </SectionCard>

      <div className="grid gap-4 md:grid-cols-2">
        <SectionCard caption="참여" title={`멤버 ${project.members.length}명`}>
          <ul className="grid gap-1">
            {project.members.map((member) => (
              <li
                key={member.id}
                className="row-hover -mx-2 flex items-center gap-3 rounded-[var(--radius-md)] px-2 py-2"
              >
                <Avatar userId={member.id} hasAvatar={false} label={member.name} size={32} />
                <span className="text-foreground text-sm font-medium">{member.name}</span>
              </li>
            ))}
          </ul>
        </SectionCard>

        <SectionCard caption="구성" title="활성 모듈">
          {project.modules.length > 0 ? (
            <ChipSet>
              {project.modules.map((module) => (
                <Chip key={module} shape="badge">
                  {module}
                </Chip>
              ))}
            </ChipSet>
          ) : (
            <p className="text-muted-foreground text-sm">연결된 모듈이 없습니다.</p>
          )}
        </SectionCard>
      </div>
    </div>
  );
}
