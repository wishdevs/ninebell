import type React from 'react';
import { cn } from '@/lib/utils';

/**
 * 관리 테이블 공용 헤더/셀 — logs·audit·members 테이블이 동일하게 쓰던 Th/Td를 단일화.
 * 패딩·정렬 규격을 한 곳에서 소유한다(이전엔 3개 파일에 복제).
 */
export function Th({ children, className, ...rest }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th className={cn('px-4 py-3 font-medium whitespace-nowrap', className)} {...rest}>
      {children}
    </th>
  );
}

export function Td({ children, className }: { children: React.ReactNode; className?: string }) {
  return <td className={cn('px-4 py-3 align-middle', className)}>{children}</td>;
}
