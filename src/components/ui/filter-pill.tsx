'use client';

import type { ReactNode } from 'react';
import { Select, SelectContent, SelectTrigger, SelectValue } from '@/components/ui/select-dropdown';
import { cn } from '@/lib/utils';

interface FilterPillProps {
  /** 접두 라벨(칩이 어떤 필터인지) — '역할'/'상태'/'에이전트' 등. */
  label: string;
  ariaLabel: string;
  value: string;
  /** 'all'이 아닐 때 accent 틴트로 적용 중임을 표시. */
  active: boolean;
  onValueChange: (value: string) => void;
  /** <SelectItem>/<SelectGroup> 자식. */
  children: ReactNode;
}

/**
 * 목록 필터 전용 칩 드롭다운 — rounded-full·라벨 접두·활성 시 accent 틴트. 테이블 행의 편집용
 * 사각 Select 와 형태를 분리한다(필터=칩 / 편집=셀). 멤버·감사·로깅 등 목록 화면 공용.
 * SelectValue 는 선택 항목 라벨만 보여주므로 'all' 항목 라벨은 '전체'로 두고 앞에 필터명을 접두.
 */
export function FilterPill({
  label,
  ariaLabel,
  value,
  active,
  onValueChange,
  children,
}: FilterPillProps) {
  return (
    <Select value={value} onValueChange={onValueChange}>
      <SelectTrigger
        aria-label={ariaLabel}
        className={cn(
          'h-9 gap-1.5 rounded-full px-3.5 font-normal',
          active
            ? 'border-accent/40 bg-accent/10 text-accent hover:bg-accent/15 hover:border-accent/50 data-[state=open]:bg-accent/15'
            : 'text-foreground-secondary',
        )}
      >
        <span className={cn(active ? 'text-accent/70' : 'text-foreground-tertiary')}>{label}</span>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>{children}</SelectContent>
    </Select>
  );
}
