import Link from 'next/link';
import { RiArrowRightSLine, RiDatabase2Line, RiFolder3Line } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { MetaChip } from '@/components/ui/meta-chip';
import type { Agent } from '@/lib/data/agents';

export interface GroupTool {
  label: string;
  href: string;
}

/**
 * 그룹별 기준정보(공유 관리 데이터) 진입점 — 그룹 상세에서 연다.
 * '결의서입력'의 예산단위·프로젝트·거래처는 소속 에이전트가 공유하는 프리필 소스라 특정
 * 에이전트가 아니라 그룹에 속한다. 새 그룹은 여기 한 줄로 자기 기준정보를 선언한다.
 */
export const GROUP_TOOLS: Record<string, readonly GroupTool[]> = {
  resolution: [
    { label: '예산단위 관리', href: '/manage/budget-units' },
    { label: '프로젝트 관리', href: '/manage/projects' },
    { label: '거래처 관리', href: '/manage/partners' },
  ],
};

/**
 * 그룹 기준정보 진입 버튼 — 그룹 상세 헤더 우측. 관리 화면(/manage/*)으로 이동하되
 * 사이드바가 아니라 '일하는 자리(그룹)'에서 열도록 한다.
 */
export function GroupTools({ tools }: { tools: readonly GroupTool[] }) {
  return (
    <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
      {tools.map((tool) => (
        <Button key={tool.href} asChild variant="secondary" size="sm">
          <Link href={tool.href}>
            <RiDatabase2Line size={14} aria-hidden />
            {tool.label}
          </Link>
        </Button>
      ))}
    </div>
  );
}

/**
 * 그룹(업무 묶음) 카드 — 한 단계 더 들어가는 폴더형 카드. 클릭 시 그룹 상세
 * (/agents/groups/[id])로 이동해 소속 에이전트를 나열한다. 새 에이전트가 그룹에
 * 추가돼도 목록 최상위가 평평하게 깔리지 않고 이 카드 안으로 들어간다.
 */
export function GroupCard({
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
          <RiFolder3Line size={18} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="text-foreground truncate text-[length:var(--text-body-lg)] font-semibold tracking-tight">
              <Link
                href={`/agents/groups/${group.id}`}
                aria-label={`${group.name} 열기 (에이전트 ${agents.length}개)`}
                className="focus-visible:after:ring-accent/40 outline-none after:absolute after:inset-0 after:rounded-[var(--radius-lg)] after:content-[''] focus-visible:after:ring-2"
              >
                {group.name}
              </Link>
            </h3>
            <MetaChip className="shrink-0 tabular-nums">{agents.length}</MetaChip>
          </div>
          {group.description ? (
            <p className="text-muted-foreground mt-1 line-clamp-2 text-xs leading-relaxed">
              {group.description}
            </p>
          ) : null}
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
