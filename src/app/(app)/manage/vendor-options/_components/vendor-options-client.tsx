'use client';

import { useCallback, useEffect, useState } from 'react';
import { RiErrorWarningLine } from '@remixicon/react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { LockedEmptyState } from '@/components/ui/list-state';
import { SectionCard } from '@/components/ui/section-card';
import { Spinner } from '@/components/ui/spinner';
import { usePermissions } from '@/hooks/use-permissions';
import { ROLES, roleAtLeast } from '@/lib/auth/permissions';
import { ApiError, api, errorMessage, toApiError } from '@/lib/api/client';
import { patchAgentSettings } from '@/lib/api/agents';
import type { Agent } from '@/lib/data/agents';
import {
  VENDOR_OPTIONS_KEY,
  vendorOptionsFromSettings,
  type VendorOptions,
} from '@/lib/purchase/vendor-options';
import { VendorOptionsFields } from './vendor-options-card';

type Phase = 'loading' | 'ready' | 'error';

/** 거래처 후보를 소유한 에이전트 — 저장 위치는 agents.settings.vendor_options 다. */
const AGENT_ID = 'purchase-order';

/**
 * 통합 지정 거래처 관리(관리자 전용) — `GET /agents/purchase-order` 의 settings 에서 후보를
 * 읽어 편집하고 `PATCH /agents/purchase-order/settings` 로 저장한다(발주 패턴과 같은 흐름,
 * 2026-08-26 별도 페이지로 분리 — 사용자 요청). 게이트는 UX 보조일 뿐이며 백엔드가 PATCH
 * 에서 admin 을 최종 강제한다(미만 403).
 */
export function VendorOptionsClient() {
  const { role } = usePermissions();
  const isAdmin = roleAtLeast(role, ROLES.ADMIN);

  const [phase, setPhase] = useState<Phase>('loading');
  const [error, setError] = useState<ApiError | null>(null);
  const [vendors, setVendors] = useState<VendorOptions | null>(null);
  const [loadedSig, setLoadedSig] = useState('');
  const [saving, setSaving] = useState(false);
  const [invalid, setInvalid] = useState<string | null>(null);

  const seed = useCallback((next: VendorOptions) => {
    setVendors(next);
    setLoadedSig(JSON.stringify(next));
    setInvalid(null);
  }, []);

  const load = useCallback(async () => {
    setPhase('loading');
    setError(null);
    try {
      const agent = await api.get<Agent>(`/agents/${AGENT_ID}`);
      seed(vendorOptionsFromSettings(agent.settings));
      setPhase('ready');
    } catch (err: unknown) {
      setError(toApiError(err));
      setPhase('error');
    }
  }, [seed]);

  useEffect(() => {
    if (isAdmin) void load();
  }, [isAdmin, load]);

  const dirty = vendors != null && JSON.stringify(vendors) !== loadedSig;

  function handleChange(next: VendorOptions): void {
    setVendors(next);
    if (invalid) setInvalid(null);
  }

  async function handleSave(): Promise<void> {
    if (!vendors) return;
    const emptyClass = Object.entries(vendors).find(([, list]) => list.length === 0)?.[0];
    if (emptyClass) {
      setInvalid(`'${emptyClass}' 거래처를 최소 1개 이상 등록하세요.`);
      return;
    }
    setInvalid(null);
    setSaving(true);
    try {
      const updated = await patchAgentSettings(AGENT_ID, { [VENDOR_OPTIONS_KEY]: vendors });
      seed(vendorOptionsFromSettings(updated.settings));
      toast.success('저장했습니다');
    } catch (err) {
      // 400 이면 서버 detail(한글 검증 메시지)이 그대로 노출된다.
      toast.error(errorMessage(err, '저장하지 못했습니다.'));
    } finally {
      setSaving(false);
    }
  }

  if (!isAdmin) {
    return (
      <LockedEmptyState description="통합 지정 거래처 관리는 관리자 이상만 사용할 수 있습니다." />
    );
  }

  if (phase === 'loading' || !vendors) {
    if (phase === 'error') {
      return (
        <EmptyState
          icon={<RiErrorWarningLine size={18} aria-hidden />}
          title="거래처 후보를 불러오지 못했습니다"
          description={errorMessage(error)}
          action={
            <Button variant="secondary" size="sm" onClick={() => void load()}>
              다시 시도
            </Button>
          }
        />
      );
    }
    return (
      <div className="text-muted-foreground flex items-center justify-center gap-2 py-16 text-sm">
        <Spinner size={18} />
        거래처 후보를 불러오는 중…
      </div>
    );
  }

  return (
    <SectionCard
      density="comfortable"
      caption="구매발주"
      title="분류별 거래처 후보"
      description="계획서의 통합 지정·발주단위 거래처 그룹에 뜨는 후보 목록입니다. 기본으로 표시한 거래처가 계획서 첫 진입값이 됩니다."
    >
      <VendorOptionsFields value={vendors} disabled={saving} onChange={handleChange} />

      {invalid ? (
        <p role="alert" className="text-danger text-xs leading-relaxed">
          {invalid}
        </p>
      ) : null}

      {/* 실행 바 — 발주 패턴 관리와 같은 sticky 하단 바 문법(-mx-6 -mb-6 = comfortable p-6). */}
      <div className="border-border-subtle bg-surface/95 sticky bottom-0 z-10 -mx-6 -mb-6 flex flex-wrap items-center justify-end gap-2 rounded-b-[var(--radius-lg)] border-t px-6 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] backdrop-blur">
        <p className="text-foreground-tertiary mr-auto text-xs">
          {dirty ? '저장하지 않은 변경이 있습니다.' : '변경 없음'}
        </p>
        <Button
          type="button"
          variant="secondary"
          onClick={() => {
            if (loadedSig) setVendors(JSON.parse(loadedSig) as VendorOptions);
            setInvalid(null);
          }}
          disabled={!dirty || saving}
          title="마지막으로 불러온 값으로 되돌립니다"
        >
          되돌리기
        </Button>
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
