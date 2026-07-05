interface InlineConfirmProps {
  /** 확인 질문 문구 (예: "전체 삭제할까요?"). */
  question: string;
  /** 확인 버튼 라벨 (예: "삭제", "중단"). */
  confirmLabel: string;
  /** 취소 버튼 라벨. 기본값 "취소". */
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  /** 확인 버튼 비활성화 — 다른 항목이 처리 중일 때 등. */
  disabled?: boolean;
}

/**
 * 인라인 파괴적 확인 바 — 삭제 · 중단처럼 되돌릴 수 없는 동작을 트리거 버튼 자리에서
 * 바로 한 번 더 확인시킨다(원클릭 즉시 실행 방지). 모달 `ConfirmDialog`보다 가벼운 대안으로,
 * 트리거 버튼 자체는 사용처마다 달라 트리거 · 확인모드 전환 상태는 호출부가 관리하고
 * 이 컴포넌트는 확인모드로 전환된 뒤의 바만 렌더링한다.
 */
export function InlineConfirm({
  question,
  confirmLabel,
  cancelLabel = '취소',
  onConfirm,
  onCancel,
  disabled = false,
}: InlineConfirmProps) {
  return (
    <div className="flex items-center gap-2 text-[length:var(--text-body-sm)]">
      <span className="text-foreground-secondary">{question}</span>
      <button
        type="button"
        onClick={onConfirm}
        disabled={disabled}
        className="text-danger hover:bg-danger/10 rounded-[var(--radius-sm)] px-2 py-1 font-medium disabled:opacity-40"
      >
        {confirmLabel}
      </button>
      <button
        type="button"
        onClick={onCancel}
        className="text-foreground-secondary hover:bg-muted rounded-[var(--radius-sm)] px-2 py-1"
      >
        {cancelLabel}
      </button>
    </div>
  );
}
