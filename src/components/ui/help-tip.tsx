'use client';

import { type ReactNode } from 'react';
import { RiQuestionLine } from '@remixicon/react';
import { Popover, PopoverContent, PopoverTrigger } from './popover';
import { cn } from '@/lib/utils';

/**
 * 도움말 토글팁 — **보조 설명 전용**. 마우스 호버가 아니라 클릭/Enter/터치로 연다.
 *
 * 왜 Tooltip 이 아니라 Popover 인가:
 * 호버로만 열리는 툴팁은 터치 기기에 호버가 없어 아예 열 수 없고, 키보드 포커스로 열려도
 * 내용 위로 포인터를 옮기는 순간 닫혀 확대경 사용자가 읽지 못한다(WCAG 1.4.13 —
 * 내용이 dismissible·hoverable·persistent 여야 한다). 클릭으로 여는 토글팁은 호버/포커스
 * 트리거가 아니라 1.4.13 의 적용 대상 자체가 아니며, 마우스·키보드·터치가 모두 같은
 * 방법으로 연다. Radix Popover 가 Escape 닫기·포커스 관리·바깥 클릭 닫기를 처리한다.
 *
 * **작업 수행에 반드시 필요한 정보는 여기에 넣지 마라.** 열어야만 보이는 내용은 못 본 사람이
 * 생긴다 — 필수 안내는 화면에 상시 노출한다. 이 컴포넌트는 용어 풀이·배경 설명처럼
 * "있으면 좋지만 없어도 답할 수 있는" 것만 담는다.
 */
export function HelpTip({
  label,
  children,
  className,
  side = 'top',
}: {
  /** 스크린리더가 읽을 버튼 이름 — 무엇에 대한 도움말인지 밝힌다. */
  label: string;
  children: ReactNode;
  className?: string;
  side?: 'top' | 'right' | 'bottom' | 'left';
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={label}
          className={cn(
            // 28×28 — WCAG 2.5.8(최소 24×24) 위. 아이콘만 두면 타깃이 아이콘 크기로
            // 줄어드므로 버튼 자체에 크기를 준다.
            'text-foreground-tertiary hover:text-accent hover:border-accent border-border',
            'focus-visible:ring-accent inline-flex size-7 shrink-0 cursor-pointer items-center justify-center',
            'rounded-full border transition-colors focus-visible:ring-2 focus-visible:outline-none',
            className,
          )}
        >
          <RiQuestionLine size={15} aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent
        side={side}
        align="start"
        className="text-foreground-secondary w-72 p-3 text-[13px] leading-relaxed"
      >
        {children}
      </PopoverContent>
    </Popover>
  );
}
