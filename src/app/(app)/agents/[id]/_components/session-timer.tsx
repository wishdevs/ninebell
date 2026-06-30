'use client';

import { useEffect, useState } from 'react';
import { RiCheckLine, RiTimeLine, RiMoonLine, RiTimerFlashLine } from '@remixicon/react';
import type { Agent } from '@/lib/data/agents';
import { cn } from '@/lib/utils';

function mmss(total: number): string {
  const t = Math.max(0, Math.floor(total));
  const m = Math.floor(t / 60);
  const s = t % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

const LIVE: ReadonlySet<Agent['status']> = new Set(['running', 'waiting_input']);

/**
 * 실시간 세션 타이머. 에이전트는 워커/큐가 아니라 **타임아웃을 가진 실시간
 * 세션**으로 돌기 때문에, 경과(↑)와 남은 시간(↓ 타임아웃까지)을 라이브로 보여준다.
 *
 * 초기 렌더 값은 픽스처(elapsedSeconds) 기준으로 결정적이라 SSR/CSR이 일치하며,
 * 마운트 이후에만 1초 간격으로 갱신한다(하이드레이션 안전).
 */
export function SessionTimer({ agent }: { agent: Agent }) {
  const live = LIVE.has(agent.status);
  const [elapsed, setElapsed] = useState(agent.elapsedSeconds);

  useEffect(() => {
    if (!live) return;
    const id = setInterval(() => {
      setElapsed((e) => Math.min(agent.timeoutSeconds, e + 1));
    }, 1000);
    return () => clearInterval(id);
  }, [live, agent.timeoutSeconds]);

  if (agent.status === 'idle') {
    return (
      <Shell tone="muted" icon={<RiMoonLine size={13} aria-hidden />}>
        <span className="text-foreground-tertiary">세션 없음</span>
        <span className="text-foreground-tertiary">· 타임아웃 {mmss(agent.timeoutSeconds)}</span>
      </Shell>
    );
  }

  if (agent.status === 'completed' || agent.status === 'failed') {
    return (
      <Shell
        tone={agent.status === 'completed' ? 'success' : 'danger'}
        icon={<RiCheckLine size={13} aria-hidden />}
      >
        <span className="text-foreground-secondary">소요</span>
        <span className="text-foreground font-semibold tabular-nums">
          {mmss(agent.elapsedSeconds)}
        </span>
        <span className="text-foreground-tertiary">/ 제한 {mmss(agent.timeoutSeconds)}</span>
      </Shell>
    );
  }

  const remaining = Math.max(0, agent.timeoutSeconds - elapsed);
  const ratio = remaining / agent.timeoutSeconds;
  const lowTone = ratio <= 0.2 ? 'danger' : ratio <= 0.4 ? 'warning' : 'info';

  return (
    <div className="flex flex-col gap-1">
      <Shell tone={lowTone} icon={<RiTimeLine size={13} aria-hidden />}>
        <span className="text-foreground-tertiary">실시간 세션</span>
        <span className="text-foreground-tertiary">
          경과 <span className="text-foreground-secondary tabular-nums">{mmss(elapsed)}</span>
        </span>
        <span className="text-foreground-tertiary">·</span>
        <span className="text-foreground-tertiary inline-flex items-center gap-1">
          <RiTimerFlashLine size={11} aria-hidden />
          남은
        </span>
        <span
          className={cn(
            'font-semibold tabular-nums',
            lowTone === 'danger'
              ? 'text-danger'
              : lowTone === 'warning'
                ? 'text-warning'
                : 'text-foreground',
          )}
        >
          {mmss(remaining)}
        </span>
        <span className="text-foreground-tertiary">/ {mmss(agent.timeoutSeconds)}</span>
      </Shell>
      <div className="bg-muted h-1 w-full overflow-hidden rounded-full">
        <div
          className={cn(
            'h-full rounded-full transition-[width] duration-1000 ease-linear',
            lowTone === 'danger' ? 'bg-danger' : lowTone === 'warning' ? 'bg-warning' : 'bg-accent',
          )}
          style={{ width: `${ratio * 100}%` }}
          suppressHydrationWarning
        />
      </div>
    </div>
  );
}

function Shell({
  tone,
  icon,
  children,
}: {
  tone: 'info' | 'warning' | 'danger' | 'success' | 'muted';
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  const toneClass =
    tone === 'danger'
      ? 'text-danger'
      : tone === 'warning'
        ? 'text-warning'
        : tone === 'success'
          ? 'text-success'
          : tone === 'muted'
            ? 'text-foreground-tertiary'
            : 'text-accent';
  return (
    <div className="flex items-center gap-1.5 text-[11px]">
      <span className={cn('shrink-0', toneClass)}>{icon}</span>
      {children}
    </div>
  );
}
