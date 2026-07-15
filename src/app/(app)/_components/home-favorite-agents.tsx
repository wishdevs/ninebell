'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { RiArrowRightLine, RiStarFill } from '@remixicon/react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { MetaChip } from '@/components/ui/meta-chip';
import { Spinner } from '@/components/ui/spinner';
import { errorMessage } from '@/lib/api/client';
import { fetchFavorites, removeFavorite, type Favorite } from '@/lib/api/me-codes';
import { type Agent, filterVisibleAgents } from '@/lib/data/agents';
import { useApiResource } from '@/app/(app)/_lib/use-api-resource';
import { AgentCardHeader } from '@/app/(app)/agents/_components/agent-card';
import { cn } from '@/lib/utils';

/** 홈에 노출할 즐겨찾기 에이전트 수(초과분은 '전체 보기'로 유도). */
const MAX_HOME_FAVORITES = 3;

/**
 * 홈 '자주쓰는 에이전트' 섹션.
 *
 * `/me/favorites?kind=agent`(code=에이전트 id, sortOrder 순) + `/agents` 를 조합해
 * 즐겨찾기된 에이전트 카드를 최대 3개 보여준다. ★ 해제는 낙관적으로 목록에서 지우고
 * 실패 시 롤백+토스트. 즐겨찾기가 없으면 에이전트 페이지로 유도하는 빈 상태를 보여준다.
 */
export function HomeFavoriteAgents() {
  const agents = useApiResource<Agent[]>('/agents');
  // 즐겨찾기는 해제(삭제) 변이가 필요해 로컬 상태로 관리한다. null = 로딩 중.
  const [favorites, setFavorites] = useState<Favorite[] | null>(null);

  useEffect(() => {
    let active = true;
    fetchFavorites('agent')
      .then((items) => {
        if (active) setFavorites(items);
      })
      .catch(() => {
        // 백엔드 미배포/일시 오류 — 빈 상태로 관대하게 처리(me-codes 계약).
        if (active) setFavorites([]);
      });
    return () => {
      active = false;
    };
  }, []);

  /** ★ 해제 — 낙관적으로 지우고 실패 시 롤백+토스트. */
  async function unfavorite(fav: Favorite) {
    setFavorites((prev) => (prev ? prev.filter((f) => f.id !== fav.id) : prev));
    try {
      await removeFavorite(fav.id);
    } catch (err) {
      setFavorites((prev) =>
        prev ? [...prev, fav].sort((a, b) => a.sortOrder - b.sortOrder) : prev,
      );
      toast.error(errorMessage(err, '자주쓰는 해제에 실패했습니다.'));
    }
  }

  const loading = favorites === null || agents.status === 'loading';

  // 즐겨찾기(sortOrder 순) ↔ 에이전트 정의 조인 — 정의가 사라진/숨김 대상 즐겨찾기는 숨긴다.
  const agentById = new Map(filterVisibleAgents(agents.data ?? []).map((a) => [a.id, a] as const));
  const matched = (favorites ?? [])
    .filter((f) => agentById.has(f.code))
    .sort((a, b) => a.sortOrder - b.sortOrder);
  const visible = matched.slice(0, MAX_HOME_FAVORITES);

  return (
    <section aria-labelledby="home-favorite-agents-heading" className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <h2
          id="home-favorite-agents-heading"
          className="text-foreground text-[length:var(--text-body-lg)] font-semibold tracking-tight"
        >
          자주쓰는 에이전트
        </h2>
        {matched.length > MAX_HOME_FAVORITES ? (
          <Link
            href="/agents"
            className="text-foreground-secondary hover:text-accent inline-flex items-center gap-1 text-xs font-medium transition-colors"
          >
            전체 보기
            <RiArrowRightLine size={14} aria-hidden />
          </Link>
        ) : null}
      </div>

      {loading ? (
        <div className="text-muted-foreground flex items-center gap-2 py-8 text-sm">
          <Spinner size={16} label="자주쓰는 에이전트 불러오는 중" />
          자주쓰는 에이전트를 불러오는 중…
        </div>
      ) : visible.length === 0 ? (
        <EmptyState
          compact
          title="자주쓰는 에이전트가 없습니다"
          description="에이전트 페이지에서 ★ 를 눌러 추가하세요."
          action={
            <Button asChild variant="secondary">
              <Link href="/agents">
                에이전트 살펴보기
                <RiArrowRightLine size={16} aria-hidden />
              </Link>
            </Button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {visible.map((fav) => {
            const agent = agentById.get(fav.code);
            if (!agent) return null;
            return (
              <FavoriteAgentCard key={fav.id} agent={agent} onUnfavorite={() => unfavorite(fav)} />
            );
          })}
        </div>
      )}
    </section>
  );
}

/**
 * 즐겨찾기 에이전트 카드(홈 전용 경량형) — 이름·설명(2줄)·대상 시스템 뱃지.
 * 카드 전체 클릭 = 상세 이동(제목 링크의 stretched-link), ★ 버튼은 오버레이 위(z-10)에서 해제.
 */
function FavoriteAgentCard({ agent, onUnfavorite }: { agent: Agent; onUnfavorite: () => void }) {
  return (
    <div className="card-interactive border-border bg-surface group relative flex flex-col gap-3 rounded-[var(--radius-lg)] border p-5 shadow-[var(--shadow-card)] transition-colors">
      <AgentCardHeader
        agent={agent}
        action={
          <button
            type="button"
            onClick={onUnfavorite}
            aria-pressed
            aria-label="자주쓰는 해제"
            title="자주쓰는 해제"
            className={cn(
              'relative z-10 -mt-1 flex size-7 shrink-0 items-center justify-center rounded-[var(--radius-sm)] transition-colors',
              'text-warning hover:bg-warning/10 focus-visible:ring-accent/40 outline-none focus-visible:ring-2',
            )}
          >
            <RiStarFill size={15} aria-hidden />
          </button>
        }
      />

      <div className="flex flex-wrap items-center gap-1.5">
        <MetaChip>{agent.targetSystem}</MetaChip>
      </div>
    </div>
  );
}
