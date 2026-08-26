'use client';

import { useCallback, useEffect, useState } from 'react';
import { RiErrorWarningLine, RiInformationLine } from '@remixicon/react';
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
  ORDER_PATTERNS_KEY,
  orderPatternsFromSettings,
  type PatternGroup,
} from '@/lib/purchase/order-patterns';
import {
  OrderPatternsEditor,
  fromPatternDraft,
  patternsSig,
  toPatternDraft,
  validatePatterns,
  type GroupDraft,
} from './order-patterns-editor';

type Phase = 'loading' | 'ready' | 'error';

/** 발주 패턴을 소유한 에이전트 — 저장 위치는 agents.settings.order_patterns 다. */
const AGENT_ID = 'purchase-order';

/** 저장된 v2 패턴이 있는지 — 값은 `{groups: [...]}` 다(v1 의 플랫 배열은 저장분으로 보지 않는다). */
function hasStoredGroups(settings: Record<string, unknown> | undefined | null): boolean {
  const raw = settings?.[ORDER_PATTERNS_KEY];
  if (typeof raw !== 'object' || raw === null) return false;
  return Array.isArray((raw as Record<string, unknown>).groups);
}

/**
 * 발주 패턴 관리(관리자 전용) — `GET /agents/purchase-order` 의 settings 에서 패턴을 읽어
 * 편집하고 `PATCH /agents/purchase-order/settings` 로 통째로 저장한다.
 * 게이트는 UX 보조일 뿐이며 백엔드가 PATCH 에서 admin 을 최종 강제한다(미만 403).
 */
export function OrderPatternsClient() {
  const { role } = usePermissions();
  const isAdmin = roleAtLeast(role, ROLES.ADMIN);

  const [phase, setPhase] = useState<Phase>('loading');
  const [error, setError] = useState<ApiError | null>(null);
  const [rows, setRows] = useState<GroupDraft[]>([]);
  const [loadedSig, setLoadedSig] = useState('');
  const [loadedRows, setLoadedRows] = useState<GroupDraft[]>([]);
  const [saving, setSaving] = useState(false);
  const [invalid, setInvalid] = useState<string | null>(null);
  // 저장값이 없어 코드 기본값(9그룹)으로 시드된 상태 — 저장 전까지는 화면만의 값이다.
  const [seededFromDefaults, setSeededFromDefaults] = useState(false);

  const seed = useCallback((next: readonly PatternGroup[]) => {
    const draft = toPatternDraft(next);
    setRows(draft);
    setLoadedRows(draft);
    setLoadedSig(patternsSig(draft));
    setInvalid(null);
  }, []);

  const load = useCallback(async () => {
    setPhase('loading');
    setError(null);
    try {
      const agent = await api.get<Agent>(`/agents/${AGENT_ID}`);
      seed(orderPatternsFromSettings(agent.settings));
      setSeededFromDefaults(!hasStoredGroups(agent.settings));
      setPhase('ready');
    } catch (err: unknown) {
      setError(toApiError(err));
      setPhase('error');
    }
  }, [seed]);

  useEffect(() => {
    if (isAdmin) void load();
  }, [isAdmin, load]);

  const dirty = patternsSig(rows) !== loadedSig;

  function handleChange(next: GroupDraft[]): void {
    setRows(next);
    if (invalid) setInvalid(null);
  }

  async function handleSave(): Promise<void> {
    const problem = validatePatterns(rows);
    if (problem) {
      setInvalid(problem);
      return;
    }
    setInvalid(null);
    setSaving(true);
    try {
      const updated = await patchAgentSettings(AGENT_ID, {
        [ORDER_PATTERNS_KEY]: { groups: fromPatternDraft(rows) },
      });
      // 응답에 패턴이 없으면 저장이 반영됐는지 알 수 없다 — 초안을 덮지 않고 그대로 알린다
      // (덮으면 코드 기본값으로 되돌아가 편집 내용이 조용히 사라진다).
      if (!hasStoredGroups(updated.settings)) {
        toast.error('서버가 발주 패턴을 돌려주지 않았습니다. 저장 여부를 확인하세요.');
        return;
      }
      seed(orderPatternsFromSettings(updated.settings));
      setSeededFromDefaults(false);
      toast.success('저장했습니다');
    } catch (err) {
      // 400 이면 서버 detail(한글 검증 메시지)이 그대로 노출된다.
      toast.error(errorMessage(err, '저장하지 못했습니다.'));
    } finally {
      setSaving(false);
    }
  }

  if (!isAdmin) {
    return <LockedEmptyState description="발주 패턴 관리는 관리자 이상만 사용할 수 있습니다." />;
  }

  if (phase === 'loading') {
    return (
      <div className="text-muted-foreground flex items-center justify-center gap-2 py-16 text-sm">
        <Spinner size={18} />
        발주 패턴을 불러오는 중…
      </div>
    );
  }

  if (phase === 'error') {
    return (
      <EmptyState
        icon={<RiErrorWarningLine size={18} aria-hidden />}
        title="발주 패턴을 불러오지 못했습니다"
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
    <SectionCard
      density="comfortable"
      caption="구매발주"
      title="발주그룹"
      description="위에서부터 아래 순서대로 발주단위를 편성합니다. 그룹 1개가 발주 1건이고, 그룹이 모듈·납기 규칙·구매사유·예외를 소유합니다."
      action={
        <span className="text-foreground-tertiary text-xs tabular-nums">{rows.length}그룹</span>
      }
    >
      {seededFromDefaults ? (
        <p className="border-border-subtle bg-muted/40 text-foreground-secondary flex items-start gap-2 rounded-[var(--radius-md)] border px-3 py-2 text-xs leading-relaxed">
          <RiInformationLine size={15} aria-hidden className="mt-0.5 shrink-0" />
          아직 저장된 패턴이 없어 코드 기본값을 보여주고 있습니다. 저장하면 이 목록이 기준이 됩니다.
        </p>
      ) : null}

      <OrderPatternsEditor value={rows} disabled={saving} onChange={handleChange} />

      {invalid ? (
        <p role="alert" className="text-danger text-xs leading-relaxed">
          {invalid}
        </p>
      ) : null}

      {/* 실행 바 — 그룹이 많으면 카드가 아주 길어져 하단 버튼이 안 보이므로 카드 안에서 sticky.
          `-mx-6 -mb-6` 로 카드 패딩(comfortable = p-6)을 먹어 좌우·아래로 꽉 채우고, 안쪽 패딩을
          다시 준다. 부모 `.animate-page-enter` 는 fill-mode backwards 라 종료 후 transform 이
          남지 않아 sticky 를 깨지 않는다(globals.css 주석 참조). */}
      <div className="border-border-subtle bg-surface/95 sticky bottom-0 z-10 -mx-6 -mb-6 flex flex-wrap items-center justify-end gap-2 rounded-b-[var(--radius-lg)] border-t px-6 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] backdrop-blur">
        {/* 변경 여부를 바 안에서 알린다 — 버튼만 있으면 눌러도 되는 상태인지 알기 어렵다. */}
        <p className="text-foreground-tertiary mr-auto text-xs">
          {dirty ? '저장하지 않은 변경이 있습니다.' : '변경 없음'}
        </p>
        <Button
          type="button"
          variant="secondary"
          onClick={() => {
            setRows(loadedRows);
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
