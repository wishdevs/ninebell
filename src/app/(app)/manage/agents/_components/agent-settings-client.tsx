'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import {
  RiArrowRightSLine,
  RiEqualizer2Line,
  RiErrorWarningLine,
  RiSettings3Line,
  RiShieldKeyholeLine,
} from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { LockedEmptyState } from '@/components/ui/list-state';
import { MetaChip } from '@/components/ui/meta-chip';
import { PageHeader } from '@/components/ui/page-header';
import { Spinner } from '@/components/ui/spinner';
import { usePermissions } from '@/hooks/use-permissions';
import { ROLES, roleAtLeast } from '@/lib/auth/permissions';
import { ApiError, api, errorMessage, toApiError } from '@/lib/api/client';
import type { Agent } from '@/lib/data/agents';
import { FUEL_CLASSES_KEY } from '@/lib/trip/fuel-calc';
import { MENU_ITEMS_KEY } from '@/lib/voucher/menu-items';
import { isConfigurable } from './agent-settings-card';

type Phase = 'loading' | 'ready' | 'error';

/** 행에 붙는 설정 요약 — 스칼라 스키마 라벨 + 동적 목록 설정 이름을 한 줄로 잇는다. */
function settingsSummary(agent: Agent): string {
  const parts = (agent.settingsSchema ?? []).map((def) => def.label);
  if (FUEL_CLASSES_KEY in (agent.settings ?? {})) parts.push('차량종류별 기준연비');
  if (MENU_ITEMS_KEY in (agent.settings ?? {})) parts.push('메뉴 필터 항목');
  return parts.join(' · ');
}

/**
 * 에이전트 관리(관리자 전용) — `GET /agents`에서 설정 가능한(isConfigurable) 에이전트를 **평면
 * 목록**으로 훑는 색인 화면이다. 편집은 하지 않는다: 각 행은 단일 설정 페이지
 * (/manage/agents/[id])로 보내고, 편집 표면은 그 페이지 하나로 일원화한다(사용자 결정
 * 2026-08-21 — 그룹 드릴인은 제거했고, 그룹별 진입은 에이전트 그룹 상세의 설정 버튼이 맡는다).
 * 게이트는 UX 보조일 뿐이며 백엔드가 PATCH 에서 admin 을 최종 강제한다(미만 403).
 */
export function AgentSettingsClient() {
  const { role } = usePermissions();
  const isAdmin = roleAtLeast(role, ROLES.ADMIN);

  const [agents, setAgents] = useState<Agent[]>([]);
  const [phase, setPhase] = useState<Phase>('loading');
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(async () => {
    setPhase('loading');
    setError(null);
    try {
      setAgents(await api.get<Agent[]>('/agents'));
      setPhase('ready');
    } catch (err: unknown) {
      setError(toApiError(err));
      setPhase('error');
    }
  }, []);

  useEffect(() => {
    if (isAdmin) void load();
  }, [isAdmin, load]);

  // 설정 가능한(스칼라 스키마 또는 동적 목록 설정을 가진) 에이전트만 노출 대상이다.
  const configurable = agents.filter(isConfigurable);

  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-8">
      <PageHeader
        caption="운영"
        title="에이전트 관리"
        description="세부설정을 가진 에이전트 목록입니다. 항목을 열어 설정을 편집합니다."
      />

      {!isAdmin ? (
        <LockedEmptyState description="에이전트 관리는 관리자 이상만 사용할 수 있습니다." />
      ) : phase === 'loading' ? (
        <div className="text-muted-foreground flex items-center justify-center gap-2 py-16 text-sm">
          <Spinner size={18} label="에이전트 불러오는 중" />
          에이전트를 불러오는 중…
        </div>
      ) : phase === 'error' ? (
        <EmptyState
          icon={<RiErrorWarningLine size={18} aria-hidden />}
          title="에이전트를 불러오지 못했습니다"
          description={errorMessage(error)}
          action={
            <Button variant="secondary" size="sm" onClick={() => void load()}>
              다시 시도
            </Button>
          }
        />
      ) : (
        <div className="flex flex-col gap-6">
          <div className="card-lift grid min-w-0">
            <Link
              href="/manage/agents/access"
              className="card-interactive border-border bg-surface group flex items-center gap-3 rounded-[var(--radius-lg)] border p-5 shadow-[var(--shadow-card)] transition-colors"
            >
              <span
                aria-hidden
                className="bg-accent/10 text-accent flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-md)]"
              >
                <RiShieldKeyholeLine size={18} />
              </span>
              <div className="min-w-0 flex-1">
                <h3 className="text-foreground text-[length:var(--text-body-lg)] font-semibold tracking-tight">
                  에이전트 접근
                </h3>
                <p className="text-muted-foreground mt-1 text-xs leading-relaxed">
                  에이전트별 실행 가능 조직(팀)을 설정합니다.
                </p>
              </div>
              <RiArrowRightSLine
                size={18}
                aria-hidden
                className="text-foreground-tertiary group-hover:text-accent shrink-0 transition-colors"
              />
            </Link>
          </div>

          {configurable.length === 0 ? (
            <EmptyState
              icon={<RiSettings3Line size={18} aria-hidden />}
              title="설정 가능한 에이전트가 없습니다"
              description="세부설정 스키마를 가진 에이전트가 아직 없습니다."
            />
          ) : (
            <div className="flex flex-col gap-2">
              {configurable.map((agent) => {
                const summary = settingsSummary(agent);
                return (
                  <Link
                    key={agent.id}
                    href={`/manage/agents/${encodeURIComponent(agent.id)}`}
                    className="card-interactive border-border bg-surface group flex items-center gap-3 rounded-[var(--radius-lg)] border px-5 py-4 shadow-[var(--shadow-card)] transition-colors"
                  >
                    <span
                      aria-hidden
                      className="bg-accent/10 text-accent flex h-9 w-9 shrink-0 items-center justify-center rounded-[var(--radius-md)]"
                    >
                      <RiEqualizer2Line size={17} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <h3 className="text-foreground truncate text-[length:var(--text-body)] font-semibold tracking-tight">
                          {agent.name}
                        </h3>
                        {agent.group ? (
                          <MetaChip className="shrink-0">{agent.group.name}</MetaChip>
                        ) : null}
                      </div>
                      {summary ? (
                        <p className="text-muted-foreground mt-0.5 truncate text-xs leading-relaxed">
                          {summary}
                        </p>
                      ) : null}
                    </div>
                    <RiArrowRightSLine
                      size={18}
                      aria-hidden
                      className="text-foreground-tertiary group-hover:text-accent shrink-0 transition-colors"
                    />
                  </Link>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
