'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { SectionCard } from '@/components/ui/section-card';
import { Spinner } from '@/components/ui/spinner';
import { errorMessage } from '@/lib/api/client';
import { patchAgentSettings } from '@/lib/api/agents';
import type { Agent, AgentSettingDef } from '@/lib/data/agents';
import { FUEL_CLASSES_KEY, fuelClassesFromSettings } from '@/lib/trip/fuel-calc';
import {
  FuelClassesEditor,
  type FuelClassDraft,
  isClassDraftValid,
  toClassDraft,
} from './fuel-classes-editor';

/** 스키마 항목의 현재 유효값(스칼라) — 저장값(settings)이 없거나 스칼라가 아니면 스키마 기본값. */
export function effectiveValue(agent: Agent, def: AgentSettingDef): number | string | boolean {
  const v = agent.settings?.[def.key];
  return typeof v === 'number' || typeof v === 'string' || typeof v === 'boolean' ? v : def.default;
}

/** 폼 초안(문자열) — input 값과 1:1로 두고 저장 시에만 숫자로 파싱한다. */
export function toDraft(agent: Agent): Record<string, string> {
  return Object.fromEntries(
    (agent.settingsSchema ?? []).map((def) => [def.key, String(effectiveValue(agent, def))]),
  );
}

interface AgentSettingsCardProps {
  agent: Agent;
  onSaved: (updated: Agent) => void;
}

/**
 * 에이전트 1개 = 카드 1장(스키마 기반 자동 폼). 스키마의 number 필드를 렌더하고 검증·저장한다.
 * 에이전트 관리 최상위(단독)와 그룹 드릴인 화면이 공유한다.
 */
export function AgentSettingsCard({ agent, onSaved }: AgentSettingsCardProps) {
  const schema = agent.settingsSchema ?? [];
  const [draft, setDraft] = useState<Record<string, string>>(() => toDraft(agent));
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  // 차량종류 기준연비(동적 목록)를 갖는 에이전트(출장 국내/자차)면 전용 에디터를 함께 노출한다.
  const hasFuelClasses = FUEL_CLASSES_KEY in (agent.settings ?? {});
  const [classes, setClasses] = useState<FuelClassDraft[]>(() =>
    toClassDraft(fuelClassesFromSettings(agent.settings)),
  );
  // 초기 차량종류 시그니처(label/kmPerL 순서 포함) — 변경 여부(dirty) 판정용.
  const classesSig = (rows: FuelClassDraft[]) =>
    JSON.stringify(rows.map((r) => [r.label.trim(), r.kmPerL.trim()]));
  const initialClassesSig = classesSig(toClassDraft(fuelClassesFromSettings(agent.settings)));

  // 서버 값과 다른 항목이 하나라도 있어야 저장 버튼이 활성화된다(스칼라 또는 차량종류 변경).
  const scalarDirty = schema.some(
    (def) => (draft[def.key] ?? '').trim() !== String(effectiveValue(agent, def)),
  );
  const classesDirty = hasFuelClasses && classesSig(classes) !== initialClassesSig;
  const dirty = scalarDirty || classesDirty;

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

    // 차량종류(동적 목록) 검증 — 최소 1행 + 각 행 라벨·기준연비(1~100). 위반 시 저장 중단.
    const payload: Record<string, unknown> = { ...settings };
    if (hasFuelClasses) {
      if (classes.length === 0 || !classes.every(isClassDraftValid)) {
        toast.error('차량종류의 이름과 기준연비(1~100)를 확인하세요. 최소 1개가 필요합니다.');
        return;
      }
      payload[FUEL_CLASSES_KEY] = classes.map((c) => ({
        id: c.id,
        label: c.label.trim(),
        kmPerL: Number(c.kmPerL),
      }));
    }

    setSaving(true);
    try {
      const updated = await patchAgentSettings(agent.id, payload);
      onSaved(updated);
      setDraft(toDraft(updated));
      setClasses(toClassDraft(fuelClassesFromSettings(updated.settings)));
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

      {hasFuelClasses ? (
        <FormField
          id={`agent-setting-${agent.id}-fuel-classes`}
          label="차량종류별 기준연비"
          hint="유류비 계산에 쓰는 차량종류 목록입니다. 필요한 만큼 추가/삭제하세요(예: 1,800cc 미만·전기차)."
        >
          <FuelClassesEditor value={classes} disabled={saving} onChange={setClasses} />
        </FormField>
      ) : null}

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
