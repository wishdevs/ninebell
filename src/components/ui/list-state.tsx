'use client';

import type { ReactNode } from 'react';
import { RiErrorWarningLine, RiLockLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { Spinner } from '@/components/ui/spinner';
import type { ApiError } from '@/lib/api/client';
import type { ListPhase } from '@/hooks/use-paged-query';

/**
 * 목록 상태 패널 — loading/error/empty 3분기 삼항(members ↔ audit ↔ logs 자구 중복)을
 * 단일 소유한다. children 이 자유이므로 테이블·카드 그리드·마스터디테일 무엇이든 수용.
 * "전 화면 공통 기능"의 2차 착지 지점 — 예: 로딩을 Spinner→Skeleton 으로 바꾸는 결정은
 * 이 파일 한 곳 수정으로 전 목록 화면에 반영된다.
 */

interface ListStatePanelProps {
  /** usePagedQuery 결과 또는 useApiResource status 매핑. */
  phase: ListPhase;
  error: ApiError | null;
  /** 로딩 문구 — 예: '접속 기록을 불러오는 중…'. */
  loadingLabel: string;
  /** 에러 제목 — 예: '접속 기록을 불러오지 못했습니다'. */
  errorTitle: string;
  /** '다시 시도' 버튼 — usePagedQuery().reload 연결. */
  onRetry: () => void;
  /** phase==='ready' 인데 rows 가 0건. */
  isEmpty: boolean;
  empty: { icon?: ReactNode; title: string; description?: string; action?: ReactNode };
  /** 정상 상태 렌더 — 테이블이든 카드 그리드든 무엇이든. */
  children: ReactNode;
}

export function ListStatePanel({
  phase,
  error,
  loadingLabel,
  errorTitle,
  onRetry,
  isEmpty,
  empty,
  children,
}: ListStatePanelProps) {
  if (phase === 'loading') {
    return (
      <div className="text-muted-foreground flex items-center justify-center gap-2 py-16 text-sm">
        {/* 인접 텍스트(loadingLabel)가 상태를 전달하므로 Spinner 는 aria-hidden(spinner.tsx 지침). */}
        <Spinner size={18} />
        {loadingLabel}
      </div>
    );
  }

  if (phase === 'error') {
    return (
      <EmptyState
        icon={<RiErrorWarningLine size={18} aria-hidden />}
        title={errorTitle}
        description={error?.status === 0 ? '서버에 연결할 수 없습니다.' : (error?.message ?? '')}
        action={
          <Button variant="secondary" size="sm" onClick={onRetry}>
            다시 시도
          </Button>
        }
      />
    );
  }

  if (isEmpty) {
    return (
      <EmptyState
        icon={empty.icon}
        title={empty.title}
        description={empty.description}
        action={empty.action}
      />
    );
  }

  return <>{children}</>;
}

interface LockedEmptyStateProps {
  /** 권한 안내 문구 — 예: '감사 로그는 관리자 이상만 열람할 수 있습니다.'. */
  description: string;
}

/** 권한 없음 프리셋 — RiLockLine EmptyState(audit ↔ logs 자구 중복 흡수). */
export function LockedEmptyState({ description }: LockedEmptyStateProps) {
  return (
    <EmptyState
      icon={<RiLockLine size={18} aria-hidden />}
      title="접근 권한이 없습니다"
      description={description}
    />
  );
}
