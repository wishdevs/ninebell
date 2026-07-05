'use client';

import Link from 'next/link';
import { RiArrowLeftSLine, RiErrorWarningLine, RiSearchLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import { EmptyState } from '@/components/ui/empty-state';
import { type Agent } from '@/lib/data/agents';
import { useApiResource } from '@/app/(app)/_lib/use-api-resource';
import { AgentDetailClient } from './agent-detail-client';

/**
 * 에이전트 상세 로더 — `GET /agents/{id}`를 클라이언트에서 가져온다.
 *
 * 세션 쿠키가 브라우저에서만 첨부되므로 상세 데이터도 클라이언트에서 로드한다.
 * 404는 "찾을 수 없음", 그 외 오류는 재시도 상태로 분기하고, 성공 시 기존
 * 리치 상세 화면(AgentDetailClient)에 그대로 위임한다.
 */
export function AgentDetailLoader({ id }: { id: string }) {
  const { status, data, error, reload } = useApiResource<Agent>(`/agents/${id}`);

  if (status === 'loading') {
    return (
      <div className="text-muted-foreground flex flex-1 items-center justify-center gap-2 py-24 text-sm">
        <Spinner size={18} label="에이전트 불러오는 중" />
        에이전트를 불러오는 중…
      </div>
    );
  }

  if (status === 'error') {
    const notFound = error?.status === 404;
    return (
      <div className="flex flex-col gap-4">
        <Link
          href="/agents"
          className="text-muted-foreground hover:text-foreground inline-flex w-fit items-center gap-1 text-[length:var(--text-body-sm)] font-medium transition-colors"
        >
          <RiArrowLeftSLine size={15} aria-hidden />
          에이전트
        </Link>
        <EmptyState
          icon={
            notFound ? (
              <RiSearchLine size={18} aria-hidden />
            ) : (
              <RiErrorWarningLine size={18} aria-hidden />
            )
          }
          title={notFound ? '에이전트를 찾을 수 없습니다' : '에이전트를 불러오지 못했습니다'}
          description={
            notFound
              ? '요청한 에이전트가 없거나 삭제되었습니다.'
              : error?.status === 0
                ? '서버에 연결할 수 없습니다.'
                : (error?.message ?? '')
          }
          action={
            notFound ? (
              <Button variant="secondary" size="sm" asChild>
                <Link href="/agents">목록으로</Link>
              </Button>
            ) : (
              <Button variant="secondary" size="sm" onClick={reload}>
                다시 시도
              </Button>
            )
          }
        />
      </div>
    );
  }

  // status === 'success' 이므로 data는 항상 존재하나, 훅 반환 타입이 분기되지
  // 않아 좁혀지지 않으므로 명시적으로 가드한다.
  if (!data) return null;
  // 단계 계획(steps)을 포함한 모든 필드는 백엔드 /agents/{id} 가 단일 소스다
  // (이전의 프론트 픽스처 steps 오버레이는 제거 — 삼중 정의 해소).
  return <AgentDetailClient agent={data} />;
}
