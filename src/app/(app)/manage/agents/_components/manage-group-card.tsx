import Link from 'next/link';
import { RiArrowRightSLine, RiFolderSettingsLine } from '@remixicon/react';
import { MetaChip } from '@/components/ui/meta-chip';
import type { Agent } from '@/lib/data/agents';

/**
 * 에이전트 관리(설정) 그룹 폴더 카드 — 클릭 시 /manage/agents/groups/[id]로 드릴인해
 * 그 그룹의 **설정 가능한**(settingsSchema 보유) 에이전트만 설정 폼으로 나열한다.
 * 카탈로그 GroupCard 와 달리 count·목록은 설정 가능한 에이전트로 한정한다(드릴인과 개수 일치).
 */
export function ManageGroupCard({
  group,
  agents,
}: {
  group: NonNullable<Agent['group']>;
  agents: readonly Agent[];
}) {
  const names = agents.map((a) => a.name).join(' · ');
  return (
    <div className="card-interactive border-border bg-surface group relative flex flex-col gap-4 rounded-[var(--radius-lg)] border p-5 shadow-[var(--shadow-card)] transition-colors">
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className="bg-accent/10 text-accent flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-md)]"
        >
          <RiFolderSettingsLine size={18} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="text-foreground truncate text-[length:var(--text-body-lg)] font-semibold tracking-tight">
              <Link
                href={`/manage/agents/groups/${group.id}`}
                aria-label={`${group.name} 설정 열기 (에이전트 ${agents.length}개)`}
                className="focus-visible:after:ring-accent/40 outline-none after:absolute after:inset-0 after:rounded-[var(--radius-lg)] after:content-[''] focus-visible:after:ring-2"
              >
                {group.name}
              </Link>
            </h3>
            <MetaChip className="shrink-0 tabular-nums">{agents.length}</MetaChip>
          </div>
          <p className="text-muted-foreground mt-1 line-clamp-2 text-xs leading-relaxed">
            설정 가능한 에이전트 {agents.length}개
          </p>
        </div>
        <RiArrowRightSLine
          size={18}
          aria-hidden
          className="text-foreground-tertiary group-hover:text-accent mt-0.5 shrink-0 transition-colors"
        />
      </div>

      <div className="border-border-subtle text-foreground-tertiary flex items-center gap-1 border-t pt-3 text-[11px]">
        <span className="truncate">{names}</span>
      </div>
    </div>
  );
}
