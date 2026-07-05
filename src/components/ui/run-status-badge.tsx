import { cn } from '@/lib/utils';

/**
 * 런(run) 상태 배지 — 라이브 스테이지(agents/[id]/live-browser-stage)와 로깅(logs-client)이
 * 공유하는 상태→{라벨,톤} 매핑을 한 곳에서 관리한다. 색 의미는 design-system 문서
 * (design-system/_components/domain-vocab-sections.tsx `RUN_STATUS_DOC`)를 그대로 따른다:
 * accent=진행, warning=사람 개입 필요, success=정상 종료, danger=실패 종료, muted=중립.
 *
 * 두 화면이 쓰는 상태 공간이 달라(라이브는 idle/connecting 을, 이력은 cancelled 를 추가로 씀)
 * 합집합을 여기 한 곳에서 관리한다 — 상태별 톤이 파일마다 따로 정의되면 waiting_input 같은
 * 상태가 한쪽에서만 danger 로 잘못 표시되는 드리프트가 생긴다(실제로 있었던 버그).
 */
export type RunBadgeStatus =
  | 'idle'
  | 'connecting'
  | 'running'
  | 'waiting_input'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'reconnecting'
  | (string & {});

const STATUS_STYLE: Record<string, { label: string; className: string }> = {
  idle: { label: '대기', className: 'border-border bg-muted text-muted-foreground' },
  connecting: { label: '연결 중', className: 'border-accent/30 bg-accent/10 text-accent' },
  running: { label: '실행 중', className: 'border-accent/30 bg-accent/10 text-accent' },
  waiting_input: { label: '개입 대기', className: 'border-warning/30 bg-warning/10 text-warning' },
  succeeded: { label: '완료', className: 'border-success/30 bg-success/10 text-success' },
  failed: { label: '실패', className: 'border-danger/30 bg-danger/10 text-danger' },
  cancelled: { label: '종료됨', className: 'border-border bg-muted text-muted-foreground' },
  // 소켓 재연결 시도 — 런 상태값은 아니지만(연결성 표시) 같은 배지 톤(warning)을 재사용한다.
  reconnecting: { label: '재연결 중', className: 'border-warning/30 bg-warning/10 text-warning' },
};

export interface RunStatusBadgeProps {
  status: RunBadgeStatus;
  /**
   * 상태 점 표시 방식 — 'pulse'는 진행/대기 중(지금 움직이고 있음)을 강조,
   * 'static'은 종료 상태의 장식용 점. 생략하면 점 없이 텍스트 필만 표시한다
   * (로깅 이력 테이블처럼 컴팩트한 맥락에 맞춘다).
   */
  dot?: 'static' | 'pulse';
  className?: string;
}

export function RunStatusBadge({ status, dot, className }: RunStatusBadgeProps) {
  const style = STATUS_STYLE[status] ?? {
    label: status,
    className: 'border-border bg-muted text-muted-foreground',
  };
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold tracking-wider',
        style.className,
        className,
      )}
    >
      {dot ? (
        <span
          className={cn('size-1.5 rounded-full bg-current', dot === 'pulse' && 'animate-pulse')}
          aria-hidden
        />
      ) : null}
      {style.label}
    </span>
  );
}
