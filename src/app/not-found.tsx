import type { Metadata } from 'next';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';

export const metadata: Metadata = { title: '페이지를 찾을 수 없습니다' };

/**
 * 루트 not-found — 존재하지 않는 주소(잘못된 링크·비공개 라우트의 notFound())에
 * 기본 크래시풍 화면 대신 앱 표면 언어로 안내한다. 루트 레이아웃 안에서 렌더된다.
 */
export default function NotFound() {
  return (
    <div className="flex min-h-dvh items-center justify-center p-6">
      <EmptyState
        className="w-full max-w-md"
        icon={<span className="font-display text-sm font-semibold tabular-nums">404</span>}
        title="페이지를 찾을 수 없습니다"
        description="주소가 잘못되었거나, 이동/삭제되었거나, 접근할 수 없는 페이지입니다."
        action={
          <Button size="sm" asChild>
            <Link href="/">홈으로</Link>
          </Button>
        }
      />
    </div>
  );
}
