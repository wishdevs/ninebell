'use client';

import { useEffect, useRef, useState } from 'react';
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
import { ApiError, api, errorMessage } from '@/lib/api/client';
import {
  buildOrgUnitForest,
  descendantLeafTeamIds,
  isLeafTeam,
  leafTeamUnits,
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

        <TabsContent value="org">
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
  // 비용구분 낙관적 오버레이(id→선택값). 새 목록이 도착하면 비운다(서버값이 진실).
  const [pending, setPending] = useState<Record<string, OrgUnitCostType>>({});
  useEffect(() => {
    setPending({});
  }, [orgUnits]);

  if (status === 'loading' || status === 'error') {
    return <LoadState error={error} onReload={onReload} />;
  }

  const forest = buildOrgUnitForest(orgUnits);

  const updateCostType = async (id: string, costType: OrgUnitCostType) => {
    setPending((prev) => ({ ...prev, [id]: costType }));
    try {
      await api.patch(`/org-units/${id}`, { costType });
      onReload(); // 서버 상태로 재동기화 → 오버레이는 목록 갱신 시 비워진다.
    } catch (err) {
      toast.error(errorMessage(err));
      setPending((prev) => {
        const next = { ...prev };
        delete next[id]; // 실패한 항목만 롤백.
        return next;
      });
    }
  };

  const costOf = (unit: OrgUnit): OrgUnitCostType | null => pending[unit.id] ?? unit.costType;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-muted-foreground text-[length:var(--text-body-sm)]">
          조직 구조는 ERP 조직도에서 동기화됩니다. 여기서는 각 팀의 비용구분만 설정할 수 있습니다.
        </p>
        <ErpOrgSync onApplied={onOrgsChanged} />
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
                onCostType={updateCostType}
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
 * 팀(점)을 아이콘·굵기로 구분하고, 팀(leaf)만 비용구분 세그먼트 토글, 상위 노드는 하위 팀 수 배지.
 */
function OrgTreeNode({
  node,
  costOf,
  onCostType,
}: {
  node: OrgUnitNode;
  costOf: (unit: OrgUnit) => OrgUnitCostType | null;
  onCostType: (id: string, costType: OrgUnitCostType) => void;
}) {
  const isTeam = isLeafTeam(node); // leaf + parentId!==null → 비용구분 대상.
  const hasChildren = node.children.length > 0;
  const isHq = node.unit.parentId === null;

  return (
    <li>
      <div className="group hover:bg-muted/40 flex items-center gap-2.5 rounded-[var(--radius-md)] px-2 py-1.5 transition-colors">
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
        {isTeam ? (
          <CostTypeToggle
            label={node.unit.label}
            value={costOf(node.unit)}
            onChange={(ct) => onCostType(node.unit.id, ct)}
          />
        ) : hasChildren ? (
          <span className="text-foreground-tertiary bg-muted shrink-0 rounded-full px-2 py-0.5 text-xs font-medium tabular-nums">
            {descendantLeafTeamIds(node).length}팀
          </span>
        ) : null}
      </div>
      {hasChildren ? (
        <ul className="border-border-subtle ml-[19px] flex flex-col border-l pl-2">
          {node.children.map((child) => (
            <OrgTreeNode key={child.unit.id} node={child} costOf={costOf} onCostType={onCostType} />
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
  onChange,
}: {
  label: string;
  value: OrgUnitCostType | null;
  onChange: (ct: OrgUnitCostType) => void;
}) {
  return (
    <div
      role="group"
      aria-label={`${label} 비용구분`}
      className="border-border bg-surface inline-flex shrink-0 items-center rounded-full border p-0.5"
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

  // 팀(leaf)만 접근 대상 — 본부·그룹(중간 노드)은 배정 단위가 아니다(백엔드가 거부).
  const forest = buildOrgUnitForest(orgUnits);
  const leaves = leafTeamUnits(forest);

  // 체크 옵션 = 실 팀 전체 + '미지정'(조직 미배정 사용자 허용, 항상 마지막).
  const options: { id: string; label: string }[] = [
    ...leaves.map((leaf) => ({ id: leaf.id, label: leaf.label })),
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

  // 상위 노드 '전체' 토글 — 그 노드 하위 팀 전부 선택/해제(on=true 선택).
  const toggleParent = (agentId: string, leafIds: string[], on: boolean) => {
    setLocal((prev) => {
      const current = new Set(prev[agentId] ?? []);
      for (const id of leafIds) {
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
              onToggleParent={(leafIds, on) => toggleParent(editing.agentId, leafIds, on)}
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
  onToggleParent: (leafIds: string[], on: boolean) => void;
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
 * 접근 편집 트리 노드(재귀). 팀(leaf)은 체크박스, 상위 노드는 하위 팀 전체 토글(tri-state)
 * 헤더 + 중첩 자식. 배정 대상 팀이 없는 가지는 렌더하지 않는다.
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
  onToggleParent: (leafIds: string[], on: boolean) => void;
}) {
  if (isLeafTeam(node)) {
    return (
      <OrgAccessCheckbox
        label={node.unit.label}
        checked={selected.has(node.unit.id)}
        onClick={() => onToggle(node.unit.id)}
      />
    );
  }

  const leafIds = descendantLeafTeamIds(node);
  if (leafIds.length === 0) return null; // 배정 대상 팀이 없는 본부/그룹은 숨김.
  const selCount = leafIds.filter((id) => selected.has(id)).length;
  const allOn = selCount === leafIds.length;

  return (
    <div className="border-border/60 overflow-hidden rounded-[var(--radius-md)] border">
      <div className="bg-muted/30 flex items-center gap-1.5 px-2 py-1.5">
        <button
          type="button"
          role="checkbox"
          aria-checked={allOn ? true : selCount > 0 ? 'mixed' : false}
          onClick={() => onToggleParent(leafIds, !allOn)}
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
          {selCount}/{leafIds.length}
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
