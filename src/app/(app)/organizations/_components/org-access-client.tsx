'use client';

import { useEffect, useRef, useState } from 'react';
import {
  RiAddLine,
  RiArrowDownSLine,
  RiArrowUpSLine,
  RiCheckLine,
  RiDeleteBinLine,
  RiErrorWarningLine,
  RiPencilLine,
} from '@remixicon/react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { EmptyState } from '@/components/ui/empty-state';
import { PageHeader } from '@/components/ui/page-header';
import { Spinner } from '@/components/ui/spinner';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useApiResource } from '@/app/(app)/_lib/use-api-resource';
import { ApiError, api, errorMessage } from '@/lib/api/client';
import {
  buildOrgUnitTree,
  type AgentAccess,
  type OrgUnit,
  type OrgUnitCostType,
} from '@/lib/data/org-units';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select-dropdown';
import { cn } from '@/lib/utils';

/** 비용구분 선택지 — 팀 생성/수정 시 사용. */
const COST_TYPE_OPTIONS: readonly OrgUnitCostType[] = ['판관비', '제조원가'];

/** 비용구분 배지 톤 — 판관비/제조원가를 구분하되 과하지 않게. */
const COST_TYPE_TONE: Record<OrgUnitCostType, string> = {
  판관비: 'bg-info/10 text-info',
  제조원가: 'bg-accent/10 text-accent',
};

function CostTypeBadge({ costType }: { costType: OrgUnitCostType }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold',
        COST_TYPE_TONE[costType],
      )}
    >
      {costType}
    </span>
  );
}

/**
 * 조직구분 관리 — 두 탭.
 * - 조직구분: 본부▸팀 CRUD(추가·이름변경·순서변경·삭제·팀 비용구분). 백엔드 `/org-units`.
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
        description="본부·팀 조직구분을 관리하고, 팀별로 각 에이전트의 사용 권한을 설정합니다. 최초 설정은 모두 선택입니다."
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

// ── 조직구분 CRUD 탭 ─────────────────────────────────────────────────────────
interface OrgUnitsTabProps {
  status: 'loading' | 'success' | 'error';
  error: ApiError | null;
  orgUnits: OrgUnit[];
  onReload: () => void;
  onOrgsChanged: () => void;
}

/** 인라인 편집 대상 — 본부(costType=null)와 팀(costType=선택값)을 함께 다룬다. */
interface EditingState {
  id: string;
  label: string;
  /** null 이면 본부(비용구분 없음), 문자열이면 팀. */
  costType: OrgUnitCostType | null;
}

function OrgUnitsTab({ status, error, orgUnits, onReload, onOrgsChanged }: OrgUnitsTabProps) {
  const [newParentLabel, setNewParentLabel] = useState('');
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<EditingState | null>(null);
  const [pendingDelete, setPendingDelete] = useState<OrgUnit | null>(null);
  // 팀 추가 인라인 폼 — 한 번에 한 본부에서만 연다.
  const [addChildFor, setAddChildFor] = useState<string | null>(null);
  const [newChildLabel, setNewChildLabel] = useState('');
  const [newChildCostType, setNewChildCostType] = useState<OrgUnitCostType>('판관비');

  if (status === 'loading' || status === 'error') {
    return <LoadState error={error} onReload={onReload} />;
  }

  const tree = buildOrgUnitTree(orgUnits);

  const runMutation = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      // 성공/실패 모두 서버 상태로 재동기화(실패 시 stale 행 잔존 방지, 리뷰 #13).
      onOrgsChanged();
      setBusy(false);
    }
  };

  const addParent = async () => {
    const label = newParentLabel.trim();
    if (!label) return;
    await runMutation(async () => {
      await api.post('/org-units', { label });
      setNewParentLabel('');
    });
  };

  const openAddChild = (parentId: string) => {
    setAddChildFor(parentId);
    setNewChildLabel('');
    setNewChildCostType('판관비');
  };

  const addChild = async (parentId: string) => {
    const label = newChildLabel.trim();
    if (!label) return;
    await runMutation(async () => {
      await api.post('/org-units', { label, parentId, costType: newChildCostType });
      setAddChildFor(null);
    });
  };

  const saveRename = async () => {
    if (!editing) return;
    const label = editing.label.trim();
    if (!label) return;
    const { id, costType } = editing;
    await runMutation(async () => {
      await api.patch(`/org-units/${id}`, costType === null ? { label } : { label, costType });
      setEditing(null);
    });
  };

  const moveParent = async (index: number, dir: -1 | 1) => {
    const next = index + dir;
    if (next < 0 || next >= tree.length) return;
    const orderedIds = tree.map((g) => g.parent.id);
    [orderedIds[index], orderedIds[next]] = [orderedIds[next], orderedIds[index]];
    await runMutation(() => api.post('/org-units/reorder', { parentId: null, orderedIds }));
  };

  const moveChild = async (parentId: string, children: OrgUnit[], index: number, dir: -1 | 1) => {
    const next = index + dir;
    if (next < 0 || next >= children.length) return;
    const orderedIds = children.map((c) => c.id);
    [orderedIds[index], orderedIds[next]] = [orderedIds[next], orderedIds[index]];
    await runMutation(() => api.post('/org-units/reorder', { parentId, orderedIds }));
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="border-border bg-surface flex items-center gap-2 rounded-[var(--radius-lg)] border p-4 shadow-[var(--shadow-card)]">
        <input
          value={newParentLabel}
          onChange={(e) => setNewParentLabel(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void addParent();
          }}
          placeholder="새 본부 이름"
          maxLength={120}
          className="border-border focus-visible:ring-accent/40 min-w-0 flex-1 rounded-[var(--radius-sm)] border bg-transparent px-3 py-2 text-sm focus-visible:ring-2 focus-visible:outline-none"
        />
        <Button
          size="sm"
          onClick={() => void addParent()}
          disabled={busy || !newParentLabel.trim()}
        >
          <RiAddLine size={15} aria-hidden className="mr-1" />
          본부 추가
        </Button>
      </div>

      {tree.length === 0 ? (
        <EmptyState
          icon={<RiErrorWarningLine size={18} aria-hidden />}
          title="본부가 없습니다"
          description="위에서 본부를 추가하세요."
        />
      ) : (
        <div className="flex flex-col gap-4">
          {tree.map(({ parent, children }, pIndex) => (
            <section
              key={parent.id}
              className="border-border bg-surface overflow-hidden rounded-[var(--radius-lg)] border shadow-[var(--shadow-card)]"
            >
              <header className="bg-muted/30 border-border-subtle flex items-center gap-3 border-b px-4 py-3">
                <span className="text-foreground-tertiary w-6 text-center text-[length:var(--text-body-sm)] tabular-nums">
                  {pIndex + 1}
                </span>
                {editing?.id === parent.id ? (
                  <input
                    autoFocus
                    value={editing.label}
                    onChange={(e) => setEditing({ ...editing, label: e.target.value })}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') void saveRename();
                      if (e.key === 'Escape') setEditing(null);
                    }}
                    maxLength={120}
                    className="border-border focus-visible:ring-accent/40 min-w-0 flex-1 rounded-[var(--radius-sm)] border bg-transparent px-2 py-1 text-sm focus-visible:ring-2 focus-visible:outline-none"
                  />
                ) : (
                  <span className="text-foreground min-w-0 flex-1 truncate text-sm font-semibold">
                    {parent.label}
                  </span>
                )}
                <div className="flex items-center gap-1">
                  {editing?.id === parent.id ? (
                    <>
                      <Button size="sm" onClick={() => void saveRename()} disabled={busy}>
                        저장
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>
                        취소
                      </Button>
                    </>
                  ) : (
                    <>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => openAddChild(parent.id)}
                        disabled={busy}
                      >
                        <RiAddLine size={14} aria-hidden className="mr-1" />팀 추가
                      </Button>
                      <IconBtn
                        label="위로"
                        onClick={() => void moveParent(pIndex, -1)}
                        disabled={busy || pIndex === 0}
                      >
                        <RiArrowUpSLine size={16} aria-hidden />
                      </IconBtn>
                      <IconBtn
                        label="아래로"
                        onClick={() => void moveParent(pIndex, 1)}
                        disabled={busy || pIndex === tree.length - 1}
                      >
                        <RiArrowDownSLine size={16} aria-hidden />
                      </IconBtn>
                      <IconBtn
                        label="이름 변경"
                        onClick={() =>
                          setEditing({ id: parent.id, label: parent.label, costType: null })
                        }
                        disabled={busy}
                      >
                        <RiPencilLine size={15} aria-hidden />
                      </IconBtn>
                      <IconBtn
                        label="삭제"
                        onClick={() => setPendingDelete(parent)}
                        disabled={busy}
                        danger
                      >
                        <RiDeleteBinLine size={15} aria-hidden />
                      </IconBtn>
                    </>
                  )}
                </div>
              </header>

              {children.length === 0 ? (
                <p className="text-foreground-tertiary px-4 py-3 text-[length:var(--text-body-sm)]">
                  이 본부에 속한 팀이 없습니다.
                </p>
              ) : (
                <ul className="divide-border-subtle flex flex-col divide-y">
                  {children.map((child, cIndex) => (
                    <li key={child.id} className="flex items-center gap-3 py-2.5 pr-4 pl-10">
                      <span className="text-foreground-tertiary w-6 text-center text-[length:var(--text-body-sm)] tabular-nums">
                        {cIndex + 1}
                      </span>
                      {editing?.id === child.id ? (
                        <>
                          <input
                            autoFocus
                            value={editing.label}
                            onChange={(e) => setEditing({ ...editing, label: e.target.value })}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') void saveRename();
                              if (e.key === 'Escape') setEditing(null);
                            }}
                            maxLength={120}
                            className="border-border focus-visible:ring-accent/40 min-w-0 flex-1 rounded-[var(--radius-sm)] border bg-transparent px-2 py-1 text-sm focus-visible:ring-2 focus-visible:outline-none"
                          />
                          <Select
                            value={editing.costType ?? '판관비'}
                            onValueChange={(value) =>
                              setEditing({ ...editing, costType: value as OrgUnitCostType })
                            }
                          >
                            <SelectTrigger aria-label="비용구분" className="w-24">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {COST_TYPE_OPTIONS.map((ct) => (
                                <SelectItem key={ct} value={ct}>
                                  {ct}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </>
                      ) : (
                        <>
                          <span className="text-foreground min-w-0 flex-1 truncate text-sm">
                            {child.label}
                          </span>
                          {child.costType ? <CostTypeBadge costType={child.costType} /> : null}
                        </>
                      )}
                      <div className="flex items-center gap-1">
                        {editing?.id === child.id ? (
                          <>
                            <Button size="sm" onClick={() => void saveRename()} disabled={busy}>
                              저장
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>
                              취소
                            </Button>
                          </>
                        ) : (
                          <>
                            <IconBtn
                              label="위로"
                              onClick={() => void moveChild(parent.id, children, cIndex, -1)}
                              disabled={busy || cIndex === 0}
                            >
                              <RiArrowUpSLine size={16} aria-hidden />
                            </IconBtn>
                            <IconBtn
                              label="아래로"
                              onClick={() => void moveChild(parent.id, children, cIndex, 1)}
                              disabled={busy || cIndex === children.length - 1}
                            >
                              <RiArrowDownSLine size={16} aria-hidden />
                            </IconBtn>
                            <IconBtn
                              label="이름/비용구분 변경"
                              onClick={() =>
                                setEditing({
                                  id: child.id,
                                  label: child.label,
                                  costType: child.costType ?? '판관비',
                                })
                              }
                              disabled={busy}
                            >
                              <RiPencilLine size={15} aria-hidden />
                            </IconBtn>
                            <IconBtn
                              label="삭제"
                              onClick={() => setPendingDelete(child)}
                              disabled={busy}
                              danger
                            >
                              <RiDeleteBinLine size={15} aria-hidden />
                            </IconBtn>
                          </>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}

              {addChildFor === parent.id ? (
                <div className="border-border-subtle bg-muted/10 flex items-center gap-2 border-t px-4 py-3 pl-10">
                  <input
                    autoFocus
                    value={newChildLabel}
                    onChange={(e) => setNewChildLabel(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') void addChild(parent.id);
                      if (e.key === 'Escape') setAddChildFor(null);
                    }}
                    placeholder="새 팀 이름"
                    maxLength={120}
                    className="border-border focus-visible:ring-accent/40 min-w-0 flex-1 rounded-[var(--radius-sm)] border bg-transparent px-3 py-2 text-sm focus-visible:ring-2 focus-visible:outline-none"
                  />
                  <Select
                    value={newChildCostType}
                    onValueChange={(value) => setNewChildCostType(value as OrgUnitCostType)}
                  >
                    <SelectTrigger aria-label="비용구분" className="w-24">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {COST_TYPE_OPTIONS.map((ct) => (
                        <SelectItem key={ct} value={ct}>
                          {ct}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button
                    size="sm"
                    onClick={() => void addChild(parent.id)}
                    disabled={busy || !newChildLabel.trim()}
                  >
                    추가
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setAddChildFor(null)}>
                    취소
                  </Button>
                </div>
              ) : null}
            </section>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        onClose={() => setPendingDelete(null)}
        title={pendingDelete?.parentId === null ? '본부 삭제' : '팀 삭제'}
        message={
          pendingDelete
            ? pendingDelete.parentId === null
              ? `'${pendingDelete.label}'을(를) 삭제하면 그 아래 팀도 함께 삭제되고, 각 에이전트의 접근 설정도 함께 제거됩니다.`
              : `'${pendingDelete.label}'을(를) 삭제하면 각 에이전트의 이 팀 접근 설정도 함께 제거됩니다.`
            : ''
        }
        confirmLabel="삭제"
        variant="danger"
        onConfirm={async () => {
          if (!pendingDelete) return;
          const id = pendingDelete.id;
          setPendingDelete(null);
          await runMutation(() => api.delete(`/org-units/${id}`));
        }}
      />
    </div>
  );
}

function IconBtn({
  label,
  onClick,
  disabled,
  danger,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'text-foreground-tertiary hover:bg-muted flex size-8 items-center justify-center rounded-[var(--radius-sm)] transition-colors disabled:cursor-not-allowed disabled:opacity-40',
        danger ? 'hover:text-danger' : 'hover:text-foreground',
      )}
    >
      {children}
    </button>
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

  // 팀(leaf)만 접근 대상 — 본부는 배정 단위가 아니다(백엔드가 본부 id를 거부).
  const tree = buildOrgUnitTree(orgUnits);

  // 체크 옵션 = 실 팀 전체 + '미지정'(조직 미배정 사용자 허용, 항상 마지막).
  const options: { id: string; label: string }[] = [
    ...tree.flatMap((g) => g.children.map((c) => ({ id: c.id, label: c.label }))),
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

  if (accessData.length === 0) {
    return (
      <EmptyState
        icon={<RiErrorWarningLine size={18} aria-hidden />}
        title="에이전트가 없습니다"
        description="사용 권한을 관리할 실 에이전트가 없습니다."
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {accessData.map((agent) => {
        const selected = new Set(local[agent.agentId] ?? []);
        const count = selected.size;
        const total = options.length;
        const allOn = total > 0 && count === total;
        return (
          <section
            key={agent.agentId}
            className="border-border bg-surface flex flex-col gap-4 rounded-[var(--radius-lg)] border p-5 shadow-[var(--shadow-card)]"
          >
            <header className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-foreground text-base font-semibold tracking-tight">
                {agent.agentName}
              </h2>
              <div className="flex items-center gap-3">
                <span
                  className={cn(
                    'rounded-full px-2 py-0.5 text-[length:var(--text-body-sm)] font-semibold tabular-nums',
                    count === 0
                      ? 'bg-danger/10 text-danger'
                      : allOn
                        ? 'bg-success/10 text-success'
                        : 'bg-muted text-foreground-secondary',
                  )}
                >
                  {count}/{total}
                </span>
                <button
                  type="button"
                  onClick={() => setSelection(agent.agentId, allOn ? [] : options.map((o) => o.id))}
                  className="border-border text-foreground-secondary hover:bg-muted hover:text-foreground rounded-[var(--radius-sm)] border px-2.5 py-1.5 text-[length:var(--text-body-sm)] font-medium transition-colors"
                >
                  {allOn ? '모두 해제' : '모두 선택'}
                </button>
              </div>
            </header>

            <div className="flex flex-col gap-4">
              {tree.map(({ parent, children }) =>
                children.length === 0 ? null : (
                  <div key={parent.id} className="flex flex-col gap-2">
                    <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.04em] uppercase">
                      {parent.label}
                    </p>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
                      {children.map((child) => (
                        <OrgAccessCheckbox
                          key={child.id}
                          label={child.label}
                          checked={selected.has(child.id)}
                          onClick={() => toggle(agent.agentId, child.id)}
                        />
                      ))}
                    </div>
                  </div>
                ),
              )}

              <div className="flex flex-col gap-2">
                <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.04em] uppercase">
                  기타
                </p>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
                  <OrgAccessCheckbox
                    label="미지정"
                    checked={selected.has(ORG_NONE)}
                    onClick={() => toggle(agent.agentId, ORG_NONE)}
                  />
                </div>
              </div>
            </div>
          </section>
        );
      })}
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
