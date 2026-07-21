'use client';

import { useEffect, useMemo, useState } from 'react';
import { RiBuilding2Line, RiErrorWarningLine, RiFolder3Line } from '@remixicon/react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { ErpOrgSync } from './erp-org-sync';
import { PageHeader } from '@/components/ui/page-header';
import { Spinner } from '@/components/ui/spinner';
import { useApiResource } from '@/app/(app)/_lib/use-api-resource';
import { useUnsavedGuard } from '@/app/(app)/_lib/use-unsaved-guard';
import { ApiError, api, errorMessage } from '@/lib/api/client';
import {
  buildOrgUnitForest,
  descendantOwnMemberIds,
  hasOwnMembers,
  ownMemberUnits,
  type OrgUnit,
  type OrgUnitCostType,
  type OrgUnitNode,
} from '@/lib/data/org-units';
import { cn } from '@/lib/utils';

/** 비용구분 선택지 — 팀(leaf)의 비용구분 설정에 사용. */
const COST_TYPE_OPTIONS: readonly OrgUnitCostType[] = ['판관비', '제조원가'];

/**
 * 조직구분 관리 — ERP 조직도를 미러링한 조직 트리(읽기 전용 구조). 구조는 여기서 생성/수정/삭제하지
 * 않고 'ERP 조직도 불러오기'로만 동기화하며, 각 팀(leaf)의 비용구분만 설정한다. 백엔드 `/org-units`.
 * (에이전트별 사용 권한은 /manage/agents/access 로 이동했다.)
 */
export function OrgAccessClient() {
  const orgs = useApiResource<OrgUnit[]>('/org-units');

  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-8">
      <PageHeader
        caption="운영"
        title="조직구분 관리"
        description="ERP 조직도를 반영한 조직 구조를 확인하고, 각 팀의 비용구분을 설정합니다. 최초 설정은 모두 선택입니다."
      />

      <OrgUnitsTab
        status={orgs.status}
        error={orgs.error}
        orgUnits={orgs.data ?? []}
        onReload={orgs.reload}
        onOrgsChanged={orgs.reload}
      />
    </div>
  );
}

// ── 로딩/에러 공통 ───────────────────────────────────────────────────────────
function LoadState({ error, onReload }: { error: ApiError | null; onReload: () => void }) {
  if (error) {
    return (
      <EmptyState
        icon={<RiErrorWarningLine size={18} aria-hidden />}
        title="불러오지 못했습니다"
        description={errorMessage(error)}
        action={
          <Button variant="secondary" size="sm" onClick={onReload}>
            다시 시도
          </Button>
        }
      />
    );
  }
  return (
    <div className="text-muted-foreground flex items-center justify-center gap-2 py-16 text-sm">
      <Spinner size={18} label="불러오는 중" />
      불러오는 중…
    </div>
  );
}

// ── 조직구분 탭(읽기 전용 트리 + 팀 비용구분) ───────────────────────────────────
interface OrgUnitsTabProps {
  status: 'loading' | 'success' | 'error';
  error: ApiError | null;
  orgUnits: OrgUnit[];
  onReload: () => void;
  onOrgsChanged: () => void;
}

function OrgUnitsTab({ status, error, orgUnits, onReload, onOrgsChanged }: OrgUnitsTabProps) {
  // 비용구분 초안(id→변경값). 서버값과 다른 항목만 담는다(즉시저장 아님 — 저장 버튼으로 일괄).
  const [draft, setDraft] = useState<Record<string, OrgUnitCostType>>({});
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    setDraft({}); // 새 목록(서버 갱신·불러오기) 도착 시 초안 리셋.
  }, [orgUnits]);

  const serverCost = useMemo(() => new Map(orgUnits.map((u) => [u.id, u.costType])), [orgUnits]);
  const dirtyIds = Object.keys(draft);
  const dirty = dirtyIds.length > 0;
  useUnsavedGuard(dirty); // 변경 있으면 새로고침·앱내 이동 시 이탈 확인.

  if (status === 'loading' || status === 'error') {
    return <LoadState error={error} onReload={onReload} />;
  }

  const forest = buildOrgUnitForest(orgUnits);

  // 스테이징 — 서버값과 같아지면 초안에서 제거(변경 없음 처리).
  const stageCostType = (id: string, costType: OrgUnitCostType) => {
    setDraft((prev) => {
      const next = { ...prev };
      if (serverCost.get(id) === costType) delete next[id];
      else next[id] = costType;
      return next;
    });
  };

  const costOf = (unit: OrgUnit): OrgUnitCostType | null => draft[unit.id] ?? unit.costType;
  const isStaged = (id: string): boolean => id in draft; // 초안에 담긴(변경된) 노드인지.
  // 미선택(effective cost=null) 직접 소속원 노드 수 — 상단 안내·발견성용(신규 편입). 컨테이너는 제외.
  const unsetCount = ownMemberUnits(forest).filter((u) => costOf(u) === null).length;

  const save = async () => {
    setSaving(true);
    try {
      await Promise.all(
        dirtyIds.map((id) => api.patch(`/org-units/${id}`, { costType: draft[id] })),
      );
      toast.success(`비용구분 ${dirtyIds.length}건 저장했습니다`);
      setDraft({});
      onReload();
    } catch (err) {
      toast.error(errorMessage(err, '저장하지 못했습니다.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {/* 상단 툴바 — 안내·ERP 불러오기·저장 컨트롤을 한 줄에. 저장 바는 항상 상단 노출(하단 sticky
          제거 — 플로팅 채팅 버튼과 겹치지 않게). 저장/되돌리기는 항상 렌더하되 변경 없음·저장 중엔 비활성. */}
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-muted-foreground min-w-0 flex-1 text-[length:var(--text-body-sm)]">
            조직 구조는 ERP 조직도에서 동기화됩니다. 여기서는 각 팀의 비용구분만 설정할 수 있습니다.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <ErpOrgSync onApplied={onOrgsChanged} />
            <span className="bg-border-subtle mx-0.5 hidden h-5 w-px sm:block" aria-hidden />
            {dirty ? (
              <span className="text-foreground-secondary text-xs whitespace-nowrap">
                <b className="text-foreground tabular-nums">{dirtyIds.length}건</b> 변경
              </span>
            ) : null}
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setDraft({})}
              disabled={!dirty || saving}
            >
              되돌리기
            </Button>
            <Button size="sm" onClick={() => void save()} disabled={!dirty || saving}>
              {saving ? (
                <>
                  <Spinner size={14} /> 저장 중…
                </>
              ) : (
                '저장'
              )}
            </Button>
          </div>
        </div>

        {/* 미선택(신규 편입 팀) 안내 — 발견 가능하도록 상단에 건수 노출. */}
        {unsetCount > 0 ? (
          <div className="border-warning/40 bg-warning/5 text-warning flex items-center gap-2 rounded-[var(--radius-md)] border border-dashed px-3 py-2 text-xs">
            <RiErrorWarningLine size={14} aria-hidden />
            <span>
              비용구분 <b className="tabular-nums">미선택 {unsetCount}개</b> — 새로 편입된 팀의
              판관비/제조원가를 선택하세요.
            </span>
          </div>
        ) : null}
      </div>

      {forest.length === 0 ? (
        <EmptyState
          icon={<RiErrorWarningLine size={18} aria-hidden />}
          title="조직이 없습니다"
          description="상단의 ‘ERP 조직도 불러오기’로 조직 구조를 가져오세요."
        />
      ) : (
        <div className="border-border bg-surface rounded-[var(--radius-lg)] border p-2 shadow-[var(--shadow-card)]">
          <ul className="flex flex-col">
            {forest.map((node) => (
              <OrgTreeNode
                key={node.unit.id}
                node={node}
                costOf={costOf}
                isStaged={isStaged}
                onCostType={stageCostType}
              />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/**
 * 조직 트리 노드(재귀). 임의 깊이를 중첩 `ul`(좌측 가이드선)로 들여쓴다. 본부(building)·그룹(folder)·
 * 팀(점)을 아이콘·굵기로 구분하고, 직접 소속원을 가진 노드는 비용구분 세그먼트 토글(자식이 있어도
 * 아래에 그대로 중첩), 순수 컨테이너는 하위 배정 대상 수 배지.
 */
function OrgTreeNode({
  node,
  costOf,
  isStaged,
  onCostType,
}: {
  node: OrgUnitNode;
  costOf: (unit: OrgUnit) => OrgUnitCostType | null;
  isStaged: (id: string) => boolean;
  onCostType: (id: string, costType: OrgUnitCostType) => void;
}) {
  const hasOwn = hasOwnMembers(node); // 직접 소속원 보유 → 비용구분 대상(말단 팀·중간 그룹 모두).
  const hasChildren = node.children.length > 0;
  const isHq = node.unit.parentId === null;
  const effectiveCost = hasOwn ? costOf(node.unit) : null;
  const unset = hasOwn && effectiveCost === null; // 비용구분 미선택(신규 편입) — 주의(amber) 표시.
  const staged = hasOwn && isStaged(node.unit.id); // 초안에 담긴 변경 — accent '변경됨' 표시.

  return (
    <li>
      <div
        className={cn(
          'group flex items-center gap-2.5 rounded-[var(--radius-md)] px-2 py-1.5 transition-colors',
          unset
            ? 'bg-warning/5 ring-warning/30 ring-1 ring-inset'
            : staged
              ? 'bg-accent/5 ring-accent/20 hover:bg-accent/10 ring-1 ring-inset'
              : 'hover:bg-muted/40',
        )}
      >
        <span
          aria-hidden
          className={cn(
            'flex size-5 shrink-0 items-center justify-center',
            isHq ? 'text-accent' : 'text-foreground-tertiary',
          )}
        >
          {isHq ? (
            <RiBuilding2Line size={16} />
          ) : hasChildren ? (
            <RiFolder3Line size={15} />
          ) : (
            <span className="bg-border-strong size-1.5 rounded-full" />
          )}
        </span>
        <span
          className={cn(
            'min-w-0 flex-1 truncate text-sm',
            isHq
              ? 'text-foreground font-semibold'
              : hasChildren
                ? 'text-foreground-secondary font-medium'
                : 'text-foreground-secondary',
          )}
        >
          {node.unit.label}
        </span>
        {hasOwn ? (
          <div className="flex shrink-0 items-center gap-2">
            {unset ? (
              <span className="bg-warning/10 text-warning inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold">
                <RiErrorWarningLine size={11} aria-hidden />
                선택 필요
              </span>
            ) : staged ? (
              <span className="text-accent inline-flex items-center gap-1 text-[10px] font-semibold">
                <span className="bg-accent size-1.5 rounded-full" aria-hidden />
                변경됨
              </span>
            ) : null}
            <CostTypeToggle
              label={node.unit.label}
              value={effectiveCost}
              attention={unset}
              onChange={(ct) => onCostType(node.unit.id, ct)}
            />
          </div>
        ) : hasChildren ? (
          <span className="text-foreground-tertiary bg-muted shrink-0 rounded-full px-2 py-0.5 text-xs font-medium tabular-nums">
            {descendantOwnMemberIds(node).length}팀
          </span>
        ) : null}
      </div>
      {hasChildren ? (
        <ul className="border-border-subtle ml-[19px] flex flex-col border-l pl-2">
          {node.children.map((child) => (
            <OrgTreeNode
              key={child.unit.id}
              node={child}
              costOf={costOf}
              isStaged={isStaged}
              onCostType={onCostType}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/** 팀 비용구분 세그먼트 토글 — 판관비/제조원가를 한눈에, 클릭 즉시 전환. */
function CostTypeToggle({
  label,
  value,
  attention = false,
  onChange,
}: {
  label: string;
  value: OrgUnitCostType | null;
  attention?: boolean;
  onChange: (ct: OrgUnitCostType) => void;
}) {
  return (
    <div
      role="group"
      aria-label={`${label} 비용구분`}
      className={cn(
        'inline-flex shrink-0 items-center rounded-full border p-0.5',
        attention ? 'border-warning/60 bg-warning/5' : 'border-border bg-surface',
      )}
    >
      {COST_TYPE_OPTIONS.map((ct) => {
        const active = value === ct;
        return (
          <button
            key={ct}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(ct)}
            className={cn(
              'rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors',
              'focus-visible:ring-accent/50 focus-visible:ring-2 focus-visible:outline-none',
              active
                ? 'bg-accent text-white'
                : 'text-foreground-tertiary hover:text-foreground-secondary',
            )}
          >
            {ct}
          </button>
        );
      })}
    </div>
  );
}
