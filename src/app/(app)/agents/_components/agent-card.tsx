import Link from 'next/link';
import {
  RiArrowRightUpLine,
  RiRepeatLine,
  RiSafariLine,
  RiStarFill,
  RiStarLine,
  RiTimerLine,
} from '@remixicon/react';
import { MetaChip } from '@/components/ui/meta-chip';
import { AGENT_DRIVE_LABEL, AGENT_INTERACTION_LABEL, type Agent } from '@/lib/data/agents';
import { formatRelativeKorean, formatSeconds } from '@/lib/data/format';
import { cn } from '@/lib/utils';

interface AgentCardProps {
  agent: Agent;
  /** 자주쓰는 ★ 토글 — 주어지면 카드 우상단에 ★ 버튼을 노출한다(홈 '자주쓰는 에이전트' 소스). */
  favorite?: {
    active: boolean;
    onToggle: () => void;
  };
}

/**
 * 에이전트 카탈로그 카드. 에이전트는 워커로 상주 실행되지 않고, 상세 화면을 열 때
 * 비로소 라이브 세션이 시작되고 화면을 벗어나면 큐를 반납하며 종료된다. 따라서
 * 리스트에서는 "실행 중/개입 대기" 같은 상주 상태 대신, 실행 이력(성공률·횟수·
 * 평균·최근 실행)만 보여준다.
 *
 * 카드 전체 클릭 = 상세 이동(제목 링크의 stretched-link). ★ 버튼은 링크 안에 중첩되지
 * 않도록 오버레이 위(z-10)의 별도 버튼으로 둔다.
 */
export function AgentCard({ agent, favorite }: AgentCardProps) {
  return (
    <div className="card-lift grid min-w-0">
      <div className="card-interactive border-border bg-surface group relative flex flex-col gap-4 rounded-[var(--radius-lg)] border p-5 shadow-[var(--shadow-card)] transition-colors">
        <AgentCardHeader
          agent={agent}
          action={
            <>
              {favorite ? (
                <button
                  type="button"
                  onClick={favorite.onToggle}
                  aria-pressed={favorite.active}
                  aria-label={favorite.active ? '자주쓰는 해제' : '자주쓰는 추가'}
                  title={favorite.active ? '자주쓰는 해제' : '자주쓰는 추가'}
                  className={cn(
                    'relative z-10 -mt-1 flex size-7 shrink-0 items-center justify-center rounded-[var(--radius-sm)] transition-colors',
                    'focus-visible:ring-accent/40 outline-none focus-visible:ring-2',
                    favorite.active
                      ? 'text-warning hover:bg-warning/10'
                      : 'text-foreground-tertiary hover:bg-muted',
                  )}
                >
                  {favorite.active ? (
                    <RiStarFill size={15} aria-hidden />
                  ) : (
                    <RiStarLine size={15} aria-hidden />
                  )}
                </button>
              ) : null}
              <RiArrowRightUpLine
                size={15}
                aria-hidden
                className="text-foreground-tertiary group-hover:text-accent mt-0.5 shrink-0 transition-colors"
              />
            </>
          }
        />

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
          {/* 실행 이력 없는 에이전트(준비 중 더미 등)는 '—' — null 이 1970년 기준 상대시간
            ('2947주 전')으로 포맷되는 오표시 방지. */}
          <span className="ml-auto tabular-nums">
            최근 {agent.lastRunAt ? formatRelativeKorean(agent.lastRunAt) : '—'}
          </span>
        </div>
      </div>
    </div>
  );
}

interface AgentCardHeaderProps {
  agent: Agent;
  /** 우측 오버레이 슬롯(★ 버튼·화살표 아이콘 등) — stretched-link 위 z-10에 뜬다. */
  action?: React.ReactNode;
}

/**
 * 카드 헤더 쉘(아이콘 아바타 + 제목 stretched-link + 설명 2줄) — 이 파일의 `AgentCard`와
 * 홈 '자주쓰는 에이전트' 경량 카드가 공유한다. 배지·통계 등 본문 구성은 각자 다르므로
 * 헤더까지만 공유하고 나머지는 호출부에서 조립한다.
 */
export function AgentCardHeader({ agent, action }: AgentCardHeaderProps) {
  return (
    <div className="flex items-start gap-3">
      <span
        aria-hidden
        className="bg-accent/10 text-accent flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-md)]"
      >
        <RiSafariLine size={18} />
      </span>
      <div className="min-w-0 flex-1">
        <h3 className="text-foreground truncate text-[length:var(--text-body-lg)] font-semibold tracking-tight">
          <Link
            href={`/agents/${agent.id}`}
            aria-label={`${agent.name} 실행`}
            className="focus-visible:after:ring-accent/40 outline-none after:absolute after:inset-0 after:rounded-[var(--radius-lg)] after:content-[''] focus-visible:after:ring-2"
          >
            {agent.name}
          </Link>
        </h3>
        <p className="text-muted-foreground mt-1 line-clamp-2 text-xs leading-relaxed">
          {agent.description}
        </p>
      </div>
      {action}
    </div>
  );
}
