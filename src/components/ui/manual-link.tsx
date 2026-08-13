import Link from 'next/link';
import { RiBookOpenLine } from '@remixicon/react';
import { cn } from '@/lib/utils';

interface ManualLinkProps {
  /** 메뉴얼 문서 id — `/manual/{docId}` 로 연결된다(에이전트 id 또는 정적 문서 id). */
  docId: string;
  className?: string;
}

/**
 * 사용 설명서 진입점 — 페이지 헤딩 옆에서 항상 보이는 필 형태 링크.
 *
 * 에이전트 상세와 계정 설정이 같은 버튼을 쓴다. 새 화면에 붙일 때도 스타일을
 * 복사하지 말고 이 컴포넌트를 쓸 것 — 클래스가 갈라지면 "같은 버튼"이 아니게 된다.
 * PageHeader 를 쓰는 화면은 `titleAdornment` 슬롯에 넣는다.
 */
export function ManualLink({ docId, className }: ManualLinkProps) {
  return (
    <Link
      href={`/manual/${docId}`}
      className={cn(
        'border-border bg-surface text-foreground-secondary hover:text-foreground inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1 text-[length:var(--text-body-sm)] font-medium shadow-sm transition-colors hover:bg-black/5 dark:hover:bg-white/5',
        className,
      )}
    >
      <RiBookOpenLine size={14} aria-hidden />
      메뉴얼
    </Link>
  );
}
