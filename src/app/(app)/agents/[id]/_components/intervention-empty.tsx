import { RiHand } from '@remixicon/react';

/**
 * 개입 탭 중립 빈 상태 — 개입(대화·선택)은 라이브 실행이 요청할 때만 등장한다.
 * 미실행/HITL 이전에는 목업 대화 대신 이 안내를 보여준다(가짜 채팅 노출 방지).
 */
export function InterventionEmpty() {
  return (
    <div className="flex h-full min-h-[220px] flex-col items-center justify-center gap-2 px-4 text-center">
      <span
        aria-hidden
        className="bg-muted text-foreground-tertiary flex size-10 items-center justify-center rounded-full"
      >
        <RiHand size={20} />
      </span>
      <p className="text-foreground-secondary text-[length:var(--text-body-sm)] font-medium">
        개입 요청 없음
      </p>
      <p className="text-foreground-tertiary max-w-xs text-[11px] leading-relaxed">
        실행 중 에이전트가 개입(대화·선택)을 요청하면 여기에 표시됩니다.
      </p>
    </div>
  );
}
