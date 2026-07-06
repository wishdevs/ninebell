'use client';

import { useCallback, useEffect, useState } from 'react';
import { RiErrorWarningLine, RiLockLine, RiSettings3Line } from '@remixicon/react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { PageHeader } from '@/components/ui/page-header';
import { SectionCard } from '@/components/ui/section-card';
import { Spinner } from '@/components/ui/spinner';
import { usePermissions } from '@/hooks/use-permissions';
import { ROLES, roleAtLeast } from '@/lib/auth/permissions';
import { ApiError, api, errorMessage, toApiError } from '@/lib/api/client';
import { patchAgentSettings } from '@/lib/api/agents';
import type { Agent, AgentSettingDef } from '@/lib/data/agents';

type Phase = 'loading' | 'ready' | 'error';

/** 스키마 항목의 현재 유효값 — 저장값(settings)이 없으면 스키마 기본값. */
function effectiveValue(agent: Agent, def: AgentSettingDef): number | string | boolean {
  return agent.settings?.[def.key] ?? def.default;
}

/** 폼 초안(문자열) — input 값과 1:1로 두고 저장 시에만 숫자로 파싱한다. */
function toDraft(agent: Agent): Record<string, string> {
  return Object.fromEntries(
    (agent.settingsSchema ?? []).map((def) => [def.key, String(effectiveValue(agent, def))]),
  );
}

/**
 * 에이전트 관리(관리자 전용) — `GET /agents`에서 settingsSchema 가 있는 에이전트만
 * SectionCard 로 나열하고, 스키마 기반 자동 폼으로 세부설정을 편집·저장한다.
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

  // 스키마가 있는(설정 가능한) 에이전트만 노출 대상이다.
  const configurable = agents.filter((agent) => (agent.settingsSchema?.length ?? 0) > 0);

  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-8">
      <PageHeader
        caption="운영"
        title="에이전트 관리"
        description="에이전트별 세부설정을 관리합니다. 저장한 값은 다음 실행부터 적용됩니다."
      />

      {!isAdmin ? (
        <EmptyState
          icon={<RiLockLine size={18} aria-hidden />}
          title="접근 권한이 없습니다"
          description="에이전트 관리는 관리자 이상만 사용할 수 있습니다."
        />
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
      ) : configurable.length === 0 ? (
        <EmptyState
          icon={<RiSettings3Line size={18} aria-hidden />}
          title="설정 가능한 에이전트가 없습니다"
          description="세부설정 스키마를 가진 에이전트가 아직 없습니다."
        />
      ) : (
        <div className="flex flex-col gap-6">
          {configurable.map((agent) => (
            <AgentSettingsCard
              key={agent.id}
              agent={agent}
              onSaved={(updated) =>
                // 저장 응답(갱신된 Agent)으로 목록 상태를 동기화한다.
                setAgents((prev) => prev.map((a) => (a.id === updated.id ? updated : a)))
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── 에이전트 1개 = 카드 1장(스키마 기반 자동 폼) ─────────────────────────────

interface AgentSettingsCardProps {
  agent: Agent;
  onSaved: (updated: Agent) => void;
}

function AgentSettingsCard({ agent, onSaved }: AgentSettingsCardProps) {
  const schema = agent.settingsSchema ?? [];
  const [draft, setDraft] = useState<Record<string, string>>(() => toDraft(agent));
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  // 서버 값과 다른 항목이 하나라도 있어야 저장 버튼이 활성화된다.
  const dirty = schema.some(
    (def) => (draft[def.key] ?? '').trim() !== String(effectiveValue(agent, def)),
  );

  function handleChange(key: string, value: string): void {
    setDraft((prev) => ({ ...prev, [key]: value }));
    // 해당 필드의 이전 검증 에러는 입력이 바뀌면 지운다.
    setFieldErrors((prev) => {
      if (!(key in prev)) return prev;
      const { [key]: _removed, ...rest } = prev;
      return rest;
    });
  }

  async function handleSave(): Promise<void> {
    // 클라이언트 검증 — 숫자 파싱/범위 실패는 서버로 보내기 전에 필드 에러로 보여준다.
    // (백엔드도 동일 검증을 강제한다 — 실패 시 400 detail.)
    const settings: Record<string, number> = {};
    const errors: Record<string, string> = {};
    for (const def of schema) {
      const raw = (draft[def.key] ?? '').trim();
      const value = Number(raw);
      if (raw === '' || !Number.isFinite(value)) {
        errors[def.key] = '숫자를 입력하세요.';
        continue;
      }
      if (def.min != null && value < def.min) {
        errors[def.key] = `${def.min} 이상이어야 합니다.`;
        continue;
      }
      if (def.max != null && value > def.max) {
        errors[def.key] = `${def.max} 이하여야 합니다.`;
        continue;
      }
      settings[def.key] = value;
    }
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;

    setSaving(true);
    try {
      const updated = await patchAgentSettings(agent.id, settings);
      onSaved(updated);
      setDraft(toDraft(updated));
      toast.success('저장했습니다');
    } catch (err) {
      // 400 이면 서버 detail(한글 검증 메시지)이 그대로 노출된다.
      toast.error(errorMessage(err, '저장하지 못했습니다.'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <SectionCard density="comfortable" title={agent.name} description={agent.description}>
      {schema.map((def) => {
        const id = `agent-setting-${agent.id}-${def.key}`;
        return (
          <FormField
            key={def.key}
            id={id}
            label={def.unit ? `${def.label} (${def.unit})` : def.label}
            hint={def.description}
            error={fieldErrors[def.key]}
          >
            <Input
              id={id}
              type="number"
              inputMode="numeric"
              min={def.min ?? undefined}
              max={def.max ?? undefined}
              value={draft[def.key] ?? ''}
              onChange={(event) => handleChange(def.key, event.target.value)}
              aria-invalid={fieldErrors[def.key] ? true : undefined}
              className="max-w-[12rem]"
            />
          </FormField>
        );
      })}

      <div className="border-border-subtle flex justify-end border-t pt-5">
        <Button type="button" onClick={() => void handleSave()} disabled={!dirty || saving}>
          {saving ? (
            <>
              <Spinner size={14} /> 저장 중…
            </>
          ) : (
            '저장'
          )}
        </Button>
      </div>
    </SectionCard>
  );
}
