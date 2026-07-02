'use client';

import { useMemo, useState } from 'react';
import { RiCheckLine } from '@remixicon/react';
import { PageHeader } from '@/components/ui/page-header';
import { AGENTS } from '@/lib/data/agents';
import { ALL_ORG_UNIT_IDS, ORG_UNITS } from '@/lib/data/org-units';
import { cn } from '@/lib/utils';

/** agentId → 사용 가능한 조직구분 id 배열. */
type AccessMap = Record<string, string[]>;

/**
 * 조직구분 관리 — 조직구분 단위로 각 에이전트의 사용 권한을 켜고 끈다.
 *
 * 최초 설정은 모두 선택. 에이전트마다 7개 조직구분을 체크박스로 선택/해제한다. 백엔드가
 * 없으므로 members 화면과 동일하게 클라이언트 로컬 state로 다룬다(세션 한정, 새로고침 시 초기화).
 */
export function OrgAccessClient() {
  const [access, setAccess] = useState<AccessMap>(() =>
    Object.fromEntries(AGENTS.map((a) => [a.id, [...ALL_ORG_UNIT_IDS]])),
  );

  const toggle = (agentId: string, orgId: string) =>
    setAccess((prev) => {
      const current = new Set(prev[agentId] ?? []);
      if (current.has(orgId)) current.delete(orgId);
      else current.add(orgId);
      // 조직구분 정의 순서를 유지해 저장한다.
      return { ...prev, [agentId]: ORG_UNITS.filter((o) => current.has(o.id)).map((o) => o.id) };
    });

  const setAll = (agentId: string, on: boolean) =>
    setAccess((prev) => ({ ...prev, [agentId]: on ? [...ALL_ORG_UNIT_IDS] : [] }));

  return (
    <div className="animate-page-enter flex flex-col gap-8">
      <PageHeader
        caption="운영"
        title="조직구분 관리"
        description="조직구분 단위로 각 에이전트의 사용 권한을 관리합니다. 최초 설정은 모두 선택이며, 체크박스로 조직구분을 선택·해제할 수 있습니다."
      />

      <OrgLegend />

      <div className="flex flex-col gap-4">
        {AGENTS.map((agent) => (
          <AgentAccessCard
            key={agent.id}
            name={agent.name}
            meta={`${agent.targetSystem} · ${INTERACTION_LABEL[agent.interaction] ?? agent.interaction}`}
            selected={access[agent.id] ?? []}
            onToggle={(orgId) => toggle(agent.id, orgId)}
            onSetAll={(on) => setAll(agent.id, on)}
          />
        ))}
      </div>
    </div>
  );
}

const INTERACTION_LABEL: Record<string, string> = {
  readonly: '읽기 전용',
  conversational: '대화형',
  autonomous: '자율',
  hybrid: '하이브리드',
};

/** 상단 조직구분 범례 — 관리 대상 7개 조직구분을 한눈에. */
function OrgLegend() {
  return (
    <div className="border-border bg-surface flex flex-wrap items-center gap-2 rounded-[var(--radius-lg)] border p-4 shadow-[var(--shadow-card)]">
      <span className="text-foreground-tertiary mr-1 text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
        조직구분 {ORG_UNITS.length}
      </span>
      {ORG_UNITS.map((o) => (
        <span
          key={o.id}
          className="border-border-subtle bg-muted/40 text-foreground-secondary rounded-full border px-2.5 py-1 text-[length:var(--text-body-sm)] font-medium"
        >
          {o.label}
        </span>
      ))}
    </div>
  );
}

interface AgentAccessCardProps {
  name: string;
  meta: string;
  selected: readonly string[];
  onToggle: (orgId: string) => void;
  onSetAll: (on: boolean) => void;
}

function AgentAccessCard({ name, meta, selected, onToggle, onSetAll }: AgentAccessCardProps) {
  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const count = selectedSet.size;
  const total = ORG_UNITS.length;
  const allOn = count === total;

  return (
    <section className="border-border bg-surface flex flex-col gap-4 rounded-[var(--radius-lg)] border p-5 shadow-[var(--shadow-card)]">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid gap-0.5">
          <h2 className="text-foreground text-base font-semibold tracking-tight">{name}</h2>
          <p className="text-foreground-tertiary text-[length:var(--text-body-sm)]">{meta}</p>
        </div>
        <div className="flex items-center gap-3">
          <span
            className={cn(
              'rounded-full px-2 py-0.5 text-[length:var(--text-body-sm)] font-semibold tabular-nums',
              count === 0 ? 'bg-danger/10 text-danger' : allOn ? 'bg-success/10 text-success' : 'bg-muted text-foreground-secondary',
            )}
          >
            {count}/{total}
          </span>
          <button
            type="button"
            onClick={() => onSetAll(!allOn)}
            className="border-border text-foreground-secondary hover:bg-muted hover:text-foreground rounded-[var(--radius-sm)] border px-2.5 py-1.5 text-[length:var(--text-body-sm)] font-medium transition-colors"
          >
            {allOn ? '모두 해제' : '모두 선택'}
          </button>
        </div>
      </header>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
        {ORG_UNITS.map((org) => {
          const on = selectedSet.has(org.id);
          return (
            <button
              key={org.id}
              type="button"
              role="checkbox"
              aria-checked={on}
              onClick={() => onToggle(org.id)}
              className={cn(
                'group flex items-center gap-2.5 rounded-[var(--radius-md)] border px-3 py-2.5 text-left transition-colors',
                'focus-visible:ring-accent/50 focus-visible:ring-2 focus-visible:outline-none',
                on
                  ? 'border-accent/50 bg-accent/5'
                  : 'border-border bg-surface hover:border-border-strong hover:bg-muted/40',
              )}
            >
              <span
                aria-hidden
                className={cn(
                  'flex size-[18px] shrink-0 items-center justify-center rounded-[6px] border transition-colors',
                  on ? 'border-accent bg-accent text-white' : 'border-border-strong bg-surface',
                )}
              >
                {on ? <RiCheckLine size={13} /> : null}
              </span>
              <span
                className={cn(
                  'text-[length:var(--text-body-sm)] font-medium',
                  on ? 'text-foreground' : 'text-foreground-secondary',
                )}
              >
                {org.label}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
