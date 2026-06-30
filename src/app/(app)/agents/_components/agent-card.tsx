import Link from 'next/link';
import { RiArrowRightUpLine, RiSafariLine, RiRepeatLine, RiTimerLine } from '@remixicon/react';
import { AGENT_DRIVE_LABEL, AGENT_INTERACTION_LABEL, type Agent } from '@/lib/data/agents';
import { formatRelativeKorean, formatSeconds } from '@/lib/data/format';
import { cn } from '@/lib/utils';

/**
 * 에이전트 카탈로그 카드. 에이전트는 워커로 상주 실행되지 않고, 상세 화면을 열 때
 * 비로소 라이브 세션이 시작되고 화면을 벗어나면 큐를 반납하며 종료된다. 따라서
 * 리스트에서는 "실행 중/개입 대기" 같은 상주 상태 대신, 실행 이력(성공률·횟수·
 * 평균·최근 실행)만 보여준다.
 */
export function AgentCard({ agent }: { agent: Agent }) {
  return (
    <Link
      href={`/agents/${agent.id}`}
      aria-label={`${agent.name} 실행`}
      className="card-interactive border-border bg-surface group flex flex-col gap-4 rounded-[var(--radius-lg)] border p-5 shadow-[var(--shadow-card)] transition-colors"
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className="bg-accent/10 text-accent flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-md)]"
        >
          <RiSafariLine size={18} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-foreground truncate text-[length:var(--text-body-lg)] font-semibold tracking-tight">
            {agent.name}
          </h3>
          <p className="text-muted-foreground mt-1 line-clamp-2 text-xs leading-relaxed">
            {agent.description}
          </p>
        </div>
        <RiArrowRightUpLine
          size={15}
          aria-hidden
          className="text-foreground-tertiary group-hover:text-accent mt-0.5 shrink-0 transition-colors"
        />
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <MetaChip>{AGENT_DRIVE_LABEL[agent.drive]}</MetaChip>
        <MetaChip>{agent.targetSystem}</MetaChip>
        <MetaChip tone="soft">{AGENT_INTERACTION_LABEL[agent.interaction]}</MetaChip>
      </div>

      <div className="border-border-subtle text-foreground-tertiary flex items-center gap-4 border-t pt-3 text-[11px]">
        <span className="inline-flex items-center gap-1">
          <RiRepeatLine size={12} aria-hidden />
          <span className="tabular-nums">{agent.runCount}회</span>
        </span>
        <span className="inline-flex items-center gap-1">
          <RiTimerLine size={12} aria-hidden />
          <span className="tabular-nums">평균 {formatSeconds(agent.avgSeconds)}</span>
        </span>
        <span className="ml-auto tabular-nums">최근 {formatRelativeKorean(agent.lastRunAt)}</span>
      </div>
    </Link>
  );
}

function MetaChip({
  children,
  tone = 'default',
}: {
  children: React.ReactNode;
  tone?: 'default' | 'soft';
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium',
        tone === 'soft'
          ? 'border-border-subtle text-foreground-tertiary border-dashed'
          : 'border-border bg-surface-raised text-foreground-secondary',
      )}
    >
      {children}
    </span>
  );
}
