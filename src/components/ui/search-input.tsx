'use client';

import { RiSearchLine } from '@remixicon/react';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

/**
 * 목록 검색 인풋 — relative 래퍼 + RiSearchLine 절대배치 + 공용 Input(h-9 rounded-full pl-9).
 * members-filter-bar·audit·logs·카탈로그가 자구 수준으로 복제하던 마크업을 단일 소유한다.
 * 검색 인풋의 형태·아이콘 규격 변경은 이 파일 한 곳에서 전 화면 반영.
 */

interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  ariaLabel: string;
  /** 래퍼 폭 제어 — 기본 'w-full sm:w-72'. */
  className?: string;
}

export function SearchInput({
  value,
  onChange,
  placeholder,
  ariaLabel,
  className,
}: SearchInputProps) {
  return (
    <div className={cn('relative w-full sm:w-72', className)}>
      <RiSearchLine
        size={16}
        aria-hidden
        className="text-foreground-tertiary pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2"
      />
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        aria-label={ariaLabel}
        className="h-9 rounded-full pl-9"
      />
    </div>
  );
}
