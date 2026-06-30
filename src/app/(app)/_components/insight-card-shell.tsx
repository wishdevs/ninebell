import type { ReactNode } from 'react';
import Link from 'next/link';
import { RiArrowRightUpLine } from '@remixicon/react';
import { cn } from '@/lib/utils';

interface InsightCardShellProps {
  /** 모듈 표시 라벨(예: "GEO 모니터링"). 캡션 아이브로로 렌더. */
  label: string;
  /** 라벨 아래 한 줄 설명 — 본문 기대치를 잡아준다. */
  caption: string;
  /** 카드 전체를 감싸는 이동 경로. */
  href: string;
  /** 한 줄 푸터 힌트(최근 활동/권장 액션). */
  hint?: ReactNode;
  /** 본문 — KPI 스트립, 스파크라인 등 모듈별 형태. */
  children: ReactNode;
  className?: string;
}

/**
 * 모듈 인사이트 카드 공용 셸. 표준 `radius-lg + p-5 + shadow-card` 표면을 고정해
 * 본문 형태가 카드마다 달라도(스파크라인 vs 지표 스트립 vs 버전 핀) Bento 그리드가
 * 하나의 일관된 세트로 읽히게 한다.
 *
 * 표면 전체를 `<Link>`로 감싸 클릭 타깃이 카드 전체에 걸치게 하고, 헤더 우상단의
 * `ArrowUpRight`는 호버 어포던스로만 동작한다.
 */
export function InsightCardShell({
  label,
  caption,
  href,
  hint,
  children,
  className,
}: InsightCardShellProps) {
  return (
    <Link
      href={href}
      aria-label={`${label} 모듈로 이동`}
      className={cn(
        'card-interactive border-border bg-surface group flex h-full flex-col gap-4 rounded-[var(--radius-lg)] border p-5 shadow-[var(--shadow-card)]',
        className,
      )}
    >
      <header className="flex items-start justify-between gap-3">
        <div className="grid gap-0.5">
          <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
            {label}
          </p>
          <p className="text-muted-foreground text-xs">{caption}</p>
        </div>
        <RiArrowRightUpLine
          size={14}
          aria-hidden
          className="text-foreground-tertiary group-hover:text-accent shrink-0 transition-colors"
        />
      </header>
      <div className="min-h-0 flex-1">{children}</div>
      {hint ? <p className="text-foreground-tertiary text-[11px] leading-relaxed">{hint}</p> : null}
    </Link>
  );
}
