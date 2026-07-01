'use client';

import { useEffect, useRef, useState } from 'react';
import {
  RiCheckLine,
  RiErrorWarningLine,
  RiLoader4Line,
  RiMoonLine,
  RiTimeLine,
} from '@remixicon/react';
import type { LiveRunStatus } from '@/lib/live/types';
import { cn } from '@/lib/utils';

function mmss(total: number): string {
  const t = Math.max(0, Math.floor(total));
  return `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`;
}

interface SessionStatusProps {
  /** 라이브 세션이 활성일 때 true. */
  isLive: boolean;
  status: LiveRunStatus;
}

/**
 * 실시간 세션 상태 — 정적 픽스처가 아니라 실제 라이브 런 기준으로 경과 시간과 상태를 보여준다.
 * 세션 시작(`connecting`)에서 경과를 0으로 리셋해 재시작/재생마다 다시 센다. 종료(성공/실패)
 * 시 경과를 고정한다. 미실행 시엔 오해되는 목업 타이머 대신 중립 "세션 없음"을 표시한다.
 *
 * 정적 SessionTimer(픽스처 status/elapsed 기반)를 대체한다.
 */
export function SessionStatus({ isLive, status }: SessionStatusProps) {
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef<number | null>(null);

  // 세션 시작(connecting)마다 경과 리셋 — 재시작·템플릿 재생에서도 다시 센다.
  useEffect(() => {
    if (status === 'connecting') {
      startRef.current = Date.now();
      setElapsed(0);
    }
  }, [status]);

  // 진행 중(연결/실행/개입 대기)에만 1초 간격 갱신. 종료되면 멈춰 경과를 고정한다.
  const ticking = isLive && status !== 'succeeded' && status !== 'failed';
  useEffect(() => {
    if (!ticking) return;
    if (startRef.current == null) startRef.current = Date.now();
    const id = setInterval(() => {
      if (startRef.current != null) {
        setElapsed(Math.floor((Date.now() - startRef.current) / 1000));
      }
    }, 1000);
    return () => clearInterval(id);
  }, [ticking]);

  if (!isLive) {
    return (
      <Shell tone="muted" icon={<RiMoonLine size={13} aria-hidden />}>
        <span className="text-foreground-tertiary">세션 없음</span>
      </Shell>
    );
  }

  if (status === 'connecting') {
    return (
      <Shell tone="info" icon={<RiLoader4Line size={13} className="animate-spin" aria-hidden />}>
        <span className="text-foreground-tertiary">세션 연결 중…</span>
      </Shell>
    );
  }

  if (status === 'succeeded' || status === 'failed') {
    const ok = status === 'succeeded';
    return (
      <Shell
        tone={ok ? 'success' : 'danger'}
        icon={
          ok ? <RiCheckLine size={13} aria-hidden /> : <RiErrorWarningLine size={13} aria-hidden />
        }
      >
        <span className="text-foreground-secondary">{ok ? '완료' : '중단'}</span>
        <span className="text-foreground font-semibold tabular-nums">{mmss(elapsed)}</span>
      </Shell>
    );
  }

  const waiting = status === 'waiting_input';
  return (
    <Shell tone={waiting ? 'warning' : 'info'} icon={<RiTimeLine size={13} aria-hidden />}>
      <span className="text-foreground-tertiary">{waiting ? '개입 대기' : '실시간 세션'}</span>
      <span className="text-foreground-tertiary">
        경과 <span className="text-foreground-secondary tabular-nums">{mmss(elapsed)}</span>
      </span>
      <span
        aria-hidden
        className={cn(
          'size-1.5 rounded-full',
          waiting ? 'bg-warning animate-pulse' : 'bg-accent animate-pulse',
        )}
      />
    </Shell>
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
