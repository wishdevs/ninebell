import { RiStarFill, RiStarLine } from '@remixicon/react';
import { cn } from '@/lib/utils';

interface FavoriteToggleProps {
  /** 즐겨찾기(자주쓰는) 활성 여부. */
  active: boolean;
  onToggle: () => void;
  disabled?: boolean;
  /** 커스텀 aria-label/title — 기본은 '자주쓰는 추가/해제'. */
  ariaLabel?: string;
  className?: string;
}

/**
 * 즐겨찾기(★) 토글 공용 버튼 — size-7·아이콘15·focus-visible 링을 표준 규격으로 고정한다
 * (agent-card.tsx 스펙 채택). LiveGridCard·code-catalog-manager 등 여러 곳에 흩어져
 * 크기·포커스링이 제각각이던 ★ 버튼을 이 컴포넌트로 통일한다.
 */
export function FavoriteToggle({
  active,
  onToggle,
  disabled,
  ariaLabel,
  className,
}: FavoriteToggleProps) {
  const label = ariaLabel ?? (active ? '자주쓰는 해제' : '자주쓰는 추가');
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={disabled}
      aria-pressed={active}
      aria-label={label}
      title={label}
      className={cn(
        'flex size-7 shrink-0 items-center justify-center rounded-[var(--radius-sm)] transition-colors',
        'focus-visible:ring-accent/40 outline-none focus-visible:ring-2',
        'disabled:cursor-not-allowed disabled:opacity-30',
        active ? 'text-warning hover:bg-warning/10' : 'text-foreground-tertiary hover:bg-muted',
        className,
      )}
    >
      {active ? <RiStarFill size={15} aria-hidden /> : <RiStarLine size={15} aria-hidden />}
    </button>
  );
}
