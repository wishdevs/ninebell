import type { Metadata } from 'next';
import { ChatPanel } from '@/components/assistant/chat-panel';

export const metadata: Metadata = { title: 'AI 어시스턴트' };

/**
 * AI 어시스턴트 전용 화면 — 도킹 런처와 동일한 패널을 넓은 컬럼으로 제공한다.
 * 로그인한 모든 사용자가 사용(별도 권한 없음).
 */
export default function AssistantPage() {
  return (
    <div className="flex w-full max-w-[var(--content-max)] flex-1 flex-col">
      <div className="border-border bg-surface flex min-h-0 flex-1 flex-col overflow-hidden rounded-[var(--radius-lg)] border shadow-[var(--shadow-card)]">
        <ChatPanel layout="full" />
      </div>
    </div>
  );
}
