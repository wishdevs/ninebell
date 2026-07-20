'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  RiBuilding2Line,
  RiCheckLine,
  RiErrorWarningLine,
  RiFolder3Line,
  RiPencilLine,
} from '@remixicon/react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Dialog, DialogBody } from '@/components/ui/dialog';
import { EmptyState } from '@/components/ui/empty-state';
import { ErpOrgSync } from './erp-org-sync';
import { PageHeader } from '@/components/ui/page-header';
import { Spinner } from '@/components/ui/spinner';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useApiResource } from '@/app/(app)/_lib/use-api-resource';
import { useUnsavedGuard } from '@/app/(app)/_lib/use-unsaved-guard';
import { ApiError, api, errorMessage } from '@/lib/api/client';
import {
  buildOrgUnitForest,
  descendantOwnMemberIds,
  hasOwnMembers,
  ownMemberUnits,
  type AgentAccess,
  type OrgUnit,
  type OrgUnitCostType,
  type OrgUnitNode,
} from '@/lib/data/org-units';
import { cn } from '@/lib/utils';

/** 비용구분 선택지 — 팀(leaf)의 비용구분 설정에 사용. */
const COST_TYPE_OPTIONS: readonly OrgUnitCostType[] = ['판관비', '제조원가'];

/**
 * 조직구분 관리 — 두 탭.
 * - 조직구분: ERP 조직도를 미러링한 조직 트리(읽기 전용 구조). 구조는 여기서 생성/수정/삭제하지
 *   않고 'ERP 조직도 불러오기'로만 동기화하며, 각 팀(leaf)의 비용구분만 설정한다. 백엔드 `/org-units`.
 * - 에이전트 접근: 실 에이전트별 사용 가능 팀을 체크박스로 관리. 백엔드 `/agent-access`.
 * 최초 설정은 모두 선택(백엔드 access_configured=false → 전체 반환).
 */
export function OrgAccessClient() {
  const orgs = useApiResource<OrgUnit[]>('/org-units');
  const access = useApiResource<AgentAccess[]>('/agent-access');

  const reloadAll = () => {
    orgs.reload();
    access.reload();
  };

  return (
    <div className="animate-page-enter flex flex-col gap-8">
      <PageHeader
        caption="운영"
        title="조직구분 관리"
        description="ERP 조직도를 반영한 조직 구조를 확인하고, 팀별 비용구분과 각 에이전트의 사용 권한을 설정합니다. 최초 설정은 모두 선택입니다."
      />

      <Tabs defaultValue="org" className="flex flex-col gap-6">
        <TabsList>
          <TabsTrigger value="org">조직구분</TabsTrigger>
          <TabsTrigger value="access">에이전트 접근</TabsTrigger>
        </TabsList>

        {/* forceMount — 탭 전환(에이전트 접근 ↔ 조직구분) 시에도 언마운트되지 않아 비용구분 초안·이탈
            가드가 유지된다(비활성 시 Radix 가 hidden 처리). */}
        <TabsContent value="org" forceMount className="data-[state=inactive]:hidden">
          <OrgUnitsTab
            status={orgs.status}
            error={orgs.error}
            orgUnits={orgs.data ?? []}
            onReload={orgs.reload}
            onOrgsChanged={reloadAll}
          />
        </TabsContent>

        <TabsContent value="access">
          <AgentAccessTab
            orgUnits={orgs.data ?? []}
            orgStatus={orgs.status}
            orgError={orgs.error}
            accessStatus={access.status}
            accessError={access.error}
            accessData={access.data ?? []}
            onReload={access.reload}
          />
        </TabsContent>
      </Tabs>
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

// ── 에이전트 접근 탭 ─────────────────────────────────────────────────────────
interface AgentAccessTabProps {
  orgUnits: OrgUnit[];
  orgStatus: 'loading' | 'success' | 'error';
  orgError: ApiError | null;
  accessStatus: 'loading' | 'success' | 'error';
  accessError: ApiError | null;
  accessData: AgentAccess[];
  onReload: () => void;
}

/** 토글 병합 디바운스(ms) — rapid 클릭을 최종 상태 1회 PATCH로 합친다. */
const PERSIST_DEBOUNCE_MS = 400;

/** '미지정'(조직 미배정 사용자 허용) wire 센티널 — 백엔드 ORG_NONE_SENTINEL·멤버 화면과 동일. */
const ORG_NONE = '__none__';

function AgentAccessTab({
  orgUnits,
  orgStatus,
  orgError,
  accessStatus,
  accessError,
  accessData,
  onReload,
}: AgentAccessTabProps) {
  // 낙관적 로컬 미러(agentId → 선택된 org id 배열).
  const [local, setLocal] = useState<Record<string, string[]>>({});
  // 편집 팝업 대상(에이전트 id) — 목록은 요약 행만, 상세 조직 선택은 다이얼로그에서.
  const [editingId, setEditingId] = useState<string | null>(null);
  useEffect(() => {
    setLocal(Object.fromEntries(accessData.map((a) => [a.agentId, a.orgUnitIds])));
  }, [accessData]);

  // 에이전트별 디바운스 타이머 + 마지막 성공 스냅샷(실패 롤백용). 렌더와 무관하게 유지.
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const serverSnapshot = useRef<Record<string, string[]>>({});
  useEffect(() => {
    serverSnapshot.current = Object.fromEntries(accessData.map((a) => [a.agentId, a.orgUnitIds]));
  }, [accessData]);
  useEffect(() => {
    const t = timers.current;
    return () => {
      Object.values(t).forEach(clearTimeout);
    };
  }, []);

  // 조직구분·접근 리소스 둘 다 성공해야 안전하게 렌더/변경(리뷰 #2·#7: orgs 미로드 시 빈 payload 반영 방지).
  if (orgStatus !== 'success' || accessStatus !== 'success') {
    return <LoadState error={accessError ?? orgError} onReload={onReload} />;
  }

  // 직접 소속원을 가진 노드만 접근 대상 — 말단 팀 + 직속 인원이 있는 중간 그룹. 순수 컨테이너는 제외.
  const forest = buildOrgUnitForest(orgUnits);
  const assignableUnits = ownMemberUnits(forest);

  // 체크 옵션 = 배정 대상 노드 전체 + '미지정'(조직 미배정 사용자 허용, 항상 마지막).
  const options: { id: string; label: string }[] = [
    ...assignableUnits.map((unit) => ({ id: unit.id, label: unit.label })),
    { id: ORG_NONE, label: '미지정' },
  ];

  // 해당 에이전트만 최신 로컬 상태로 PATCH(디바운스). 실패 시 그 에이전트만 서버 스냅샷으로 롤백(리뷰 #1·#6·#8).
  const schedulePersist = (agentId: string) => {
    const existing = timers.current[agentId];
    if (existing) clearTimeout(existing);
    timers.current[agentId] = setTimeout(() => {
      delete timers.current[agentId];
      setLocal((cur) => {
        const orgUnitIds = cur[agentId] ?? [];
        api.patch(`/agent-access/${agentId}`, { orgUnitIds }).catch((err) => {
          toast.error(errorMessage(err));
          const snap = serverSnapshot.current[agentId] ?? [];
          setLocal((p) => ({ ...p, [agentId]: snap })); // 그 에이전트만 롤백.
        });
        return cur; // setLocal 은 최신값 읽기용, 상태 변경 없음.
      });
    }, PERSIST_DEBOUNCE_MS);
  };

  const setSelection = (agentId: string, orgUnitIds: string[]) => {
    setLocal((prev) => ({ ...prev, [agentId]: orgUnitIds }));
    schedulePersist(agentId);
  };

  const toggle = (agentId: string, orgId: string) => {
    // 최신 로컬 상태 기준으로 함수형 갱신(리뷰 #6: 클로저 stale 방지).
    setLocal((prev) => {
      const current = new Set(prev[agentId] ?? []);
      if (current.has(orgId)) current.delete(orgId);
      else current.add(orgId);
      const next = options.filter((o) => current.has(o.id)).map((o) => o.id);
      return { ...prev, [agentId]: next };
    });
    schedulePersist(agentId);
  };

  // 그룹 헤더 '전체' 토글 — 그 노드 하위(자기 포함) 배정 대상 전부 선택/해제(on=true 선택).
  const toggleParent = (agentId: string, unitIds: string[], on: boolean) => {
    setLocal((prev) => {
      const current = new Set(prev[agentId] ?? []);
      for (const id of unitIds) {
        if (on) current.add(id);
        else current.delete(id);
      }
      const next = options.filter((o) => current.has(o.id)).map((o) => o.id);
      return { ...prev, [agentId]: next };
    });
    schedulePersist(agentId);
  };

  const teamOptions = options.filter((o) => o.id !== ORG_NONE);

  // 요약 문구/톤 — 목록 행에 접근 상태를 한 줄로. 전체=모든 조직, 0=접근 없음, 그 외 팀 수(+미지정).
  const summarize = (sel: Set<string>): { text: string; tone: 'all' | 'some' | 'none' } => {
    const teamCount = teamOptions.filter((o) => sel.has(o.id)).length;
    const hasNone = sel.has(ORG_NONE);
    if (teamCount === teamOptions.length && hasNone) return { text: '모든 조직 허용', tone: 'all' };
    if (teamCount === 0 && !hasNone) return { text: '접근 조직 없음', tone: 'none' };
    const parts: string[] = [];
    if (teamCount > 0) parts.push(`${teamCount}개 팀`);
    if (hasNone) parts.push('미지정 포함');
    return { text: parts.join(' · '), tone: 'some' };
  };

  if (accessData.length === 0) {
    return (
      <EmptyState
        icon={<RiErrorWarningLine size={18} aria-hidden />}
        title="에이전트가 없습니다"
        description="사용 권한을 관리할 실 에이전트가 없습니다."
      />
    );
  }

  const editing = accessData.find((a) => a.agentId === editingId) ?? null;
  const editingSel = editing ? new Set(local[editing.agentId] ?? []) : new Set<string>();
  // 모두 선택 여부는 옵션 멤버십으로 판정(로컬에 중간 그룹 id 등 옵션 외 값이 섞여도 견고).
  const allSelected = options.every((o) => editingSel.has(o.id));

  return (
    <>
      <p className="text-muted-foreground mb-3 text-[length:var(--text-body-sm)] leading-relaxed">
        에이전트별로 실행을 허용할 조직(팀)을 지정합니다. 각 행의 <b>편집</b>에서 팝업으로
        선택하세요. 지정하지 않으면 모든 조직이 실행할 수 있습니다.
      </p>

      {/* 요약 행 목록 — 에이전트당 한 줄(이름 + 접근 요약 + 편집). */}
      <div className="border-border bg-surface divide-border-subtle flex flex-col divide-y rounded-[var(--radius-lg)] border shadow-[var(--shadow-card)]">
        {accessData.map((agent) => {
          const s = summarize(new Set(local[agent.agentId] ?? []));
          return (
            <div key={agent.agentId} className="flex items-center justify-between gap-3 px-4 py-3">
              <div className="min-w-0">
                <p className="text-foreground truncate font-medium">{agent.agentName}</p>
                <p
                  className={cn(
                    'mt-0.5 text-xs',
                    s.tone === 'all'
                      ? 'text-success'
                      : s.tone === 'none'
                        ? 'text-danger'
                        : 'text-foreground-secondary',
                  )}
                >
                  {s.text}
                </p>
              </div>
              <Button
                variant="secondary"
                size="sm"
                className="shrink-0"
                onClick={() => setEditingId(agent.agentId)}
              >
                <RiPencilLine size={14} aria-hidden />
                편집
              </Button>
            </div>
          );
        })}
      </div>

      {/* 편집 팝업 — 조직 트리(상위 노드 전체 토글) + 미지정. 변경은 자동 저장(디바운스). */}
      {editing ? (
        <Dialog
          open
          onClose={() => setEditingId(null)}
          title={`${editing.agentName} — 접근 조직`}
          description="이 에이전트를 실행할 수 있는 조직(팀)을 선택하세요. 변경은 자동 저장됩니다."
          size="lg"
          footer={
            <div className="flex items-center justify-between gap-3">
              <button
                type="button"
                onClick={() =>
                  setSelection(editing.agentId, allSelected ? [] : options.map((o) => o.id))
                }
                className="border-border text-foreground-secondary hover:bg-muted hover:text-foreground rounded-[var(--radius-sm)] border px-2.5 py-1.5 text-[length:var(--text-body-sm)] font-medium transition-colors"
              >
                {allSelected ? '모두 해제' : '모두 선택'}
              </button>
              <Button onClick={() => setEditingId(null)}>닫기</Button>
            </div>
          }
        >
          <DialogBody>
            <AgentAccessEditor
              forest={forest}
              selected={editingSel}
              noneChecked={editingSel.has(ORG_NONE)}
              onToggle={(id) => toggle(editing.agentId, id)}
              onToggleParent={(unitIds, on) => toggleParent(editing.agentId, unitIds, on)}
            />
          </DialogBody>
        </Dialog>
      ) : null}
    </>
  );
}

// ── 편집 팝업 내용 — 조직 트리(상위 노드 전체 토글) + 팀 체크박스 + 미지정 ──────────
function AgentAccessEditor({
  forest,
  selected,
  noneChecked,
  onToggle,
  onToggleParent,
}: {
  forest: OrgUnitNode[];
  selected: Set<string>;
  noneChecked: boolean;
  onToggle: (orgId: string) => void;
  onToggleParent: (unitIds: string[], on: boolean) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      {forest.map((node) => (
        <AgentAccessNode
          key={node.unit.id}
          node={node}
          selected={selected}
          onToggle={onToggle}
          onToggleParent={onToggleParent}
        />
      ))}

      <div className="mt-1">
        <OrgAccessCheckbox
          label="미지정 (조직 미배정 사용자 허용)"
          checked={noneChecked}
          onClick={() => onToggle(ORG_NONE)}
        />
      </div>
    </div>
  );
}

/**
 * 접근 편집 트리 노드(재귀).
 * - 자식이 없는 노드: 직접 소속원이 있으면 단일 체크박스, 없으면(0명 말단) 렌더하지 않는다.
 * - 자식이 있는 노드: 하위(자기 포함) 배정 대상 전체 토글(tri-state) 헤더 + 중첩 자식.
 *   직접 소속원을 가진 그룹은 자기 id도 헤더 토글/집계에 포함되어, 헤더 선택 시 그룹 자체도 선택된다.
 *   배정 대상이 하나도 없는 가지는 렌더하지 않는다.
 */
function AgentAccessNode({
  node,
  selected,
  onToggle,
  onToggleParent,
}: {
  node: OrgUnitNode;
  selected: Set<string>;
  onToggle: (orgId: string) => void;
  onToggleParent: (unitIds: string[], on: boolean) => void;
}) {
  const hasChildren = node.children.length > 0;

  if (!hasChildren) {
    if (!hasOwnMembers(node)) return null; // 직속 인원 0인 말단은 배정 대상 아님.
    return (
      <OrgAccessCheckbox
        label={node.unit.label}
        checked={selected.has(node.unit.id)}
        onClick={() => onToggle(node.unit.id)}
      />
    );
  }

  // 자식이 있는 노드 = 그룹 헤더. unitIds 는 하위(자기 포함) 배정 대상 전부 — 직접 소속원 그룹은 자기 id도 포함.
  const unitIds = descendantOwnMemberIds(node);
  if (unitIds.length === 0) return null; // 배정 대상이 없는 컨테이너는 숨김.
  const selCount = unitIds.filter((id) => selected.has(id)).length;
  const allOn = selCount === unitIds.length;

  return (
    <div className="border-border/60 overflow-hidden rounded-[var(--radius-md)] border">
      <div className="bg-muted/30 flex items-center gap-1.5 px-2 py-1.5">
        <button
          type="button"
          role="checkbox"
          aria-checked={allOn ? true : selCount > 0 ? 'mixed' : false}
          onClick={() => onToggleParent(unitIds, !allOn)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          <span
            aria-hidden
            className={cn(
              'flex size-[18px] shrink-0 items-center justify-center rounded-[6px] border transition-colors',
              allOn
                ? 'border-accent bg-accent text-white'
                : selCount > 0
                  ? 'border-accent bg-accent/20 text-accent'
                  : 'border-border-strong bg-surface',
            )}
          >
            {allOn ? <RiCheckLine size={13} /> : selCount > 0 ? '–' : null}
          </span>
          <span className="text-foreground truncate text-[length:var(--text-body-sm)] font-medium">
            {node.unit.label}
          </span>
        </button>
        <span className="text-foreground-tertiary shrink-0 text-xs tabular-nums">
          {selCount}/{unitIds.length}
        </span>
      </div>
      <div className="flex flex-col gap-1.5 p-2 pl-3">
        {node.children.map((child) => (
          <AgentAccessNode
            key={child.unit.id}
            node={child}
            selected={selected}
            onToggle={onToggle}
            onToggleParent={onToggleParent}
          />
        ))}
      </div>
    </div>
  );
}

function OrgAccessCheckbox({
  label,
  checked,
  onClick,
}: {
  label: string;
  checked: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      onClick={onClick}
      className={cn(
        'group flex items-center gap-2.5 rounded-[var(--radius-md)] border px-3 py-2.5 text-left transition-colors',
        'focus-visible:ring-accent/50 focus-visible:ring-2 focus-visible:outline-none',
        checked
          ? 'border-accent/50 bg-accent/5'
          : 'border-border bg-surface hover:border-border-strong hover:bg-muted/40',
      )}
    >
      <span
        aria-hidden
        className={cn(
          'flex size-[18px] shrink-0 items-center justify-center rounded-[6px] border transition-colors',
          checked ? 'border-accent bg-accent text-white' : 'border-border-strong bg-surface',
        )}
      >
        {checked ? <RiCheckLine size={13} /> : null}
      </span>
      <span
        className={cn(
          'text-[length:var(--text-body-sm)] font-medium',
          checked ? 'text-foreground' : 'text-foreground-secondary',
        )}
      >
        {label}
      </span>
    </button>
  );
}
