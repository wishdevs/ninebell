import { cn } from '@/lib/utils';

interface MetaChipProps {
  children: React.ReactNode;
  /** `default` = 실선 배경 배지, `soft` = 점선 테두리의 약한 배지. */
  tone?: 'default' | 'soft';
  className?: string;
}

/**
 * MetaChip — 카드 위에서 속성(구동방식·대상시스템·상호작용·개수 등)을 나열하는 작은
 * 배지. 에이전트 카탈로그 카드·홈 즐겨찾기 카드·그룹 카운트 배지에서 공유한다.
 */
export function MetaChip({ children, tone = 'default', className }: MetaChipProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium',
        tone === 'soft'
          ? 'border-border-subtle text-foreground-tertiary border-dashed'
          : 'border-border bg-surface-raised text-foreground-secondary',
        className,
      )}
    >
      {children}
    </span>
  );
}
