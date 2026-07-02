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
import type { AgentAccess, OrgUnit } from '@/lib/data/org-units';
import { cn } from '@/lib/utils';

/**
 * 조직구분 관리 — 두 탭.
 * - 조직구분: 조직구분 CRUD(추가·이름변경·순서변경·삭제). 백엔드 `/org-units`.
 * - 에이전트 접근: 실 에이전트별 사용 가능 조직구분을 체크박스로 관리. 백엔드 `/agent-access`.
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
        description="조직구분을 관리하고, 조직구분별로 각 에이전트의 사용 권한을 설정합니다. 최초 설정은 모두 선택입니다."
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

function OrgUnitsTab({ status, error, orgUnits, onReload, onOrgsChanged }: OrgUnitsTabProps) {
  const [newLabel, setNewLabel] = useState('');
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<{ id: string; label: string } | null>(null);
  const [pendingDelete, setPendingDelete] = useState<OrgUnit | null>(null);

  if (status === 'loading' || status === 'error') {
    return <LoadState error={error} onReload={onReload} />;
  }

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

  const addOrg = async () => {
    const label = newLabel.trim();
    if (!label) return;
    await runMutation(async () => {
      await api.post('/org-units', { label });
      setNewLabel('');
    });
  };

  const saveRename = async () => {
    if (!editing) return;
    const label = editing.label.trim();
    if (!label) return;
    const id = editing.id;
    await runMutation(async () => {
      await api.patch(`/org-units/${id}`, { label });
      setEditing(null);
    });
  };

  const move = async (index: number, dir: -1 | 1) => {
    const next = index + dir;
    if (next < 0 || next >= orgUnits.length) return;
    const orderedIds = orgUnits.map((o) => o.id);
    [orderedIds[index], orderedIds[next]] = [orderedIds[next], orderedIds[index]];
    await runMutation(() => api.post('/org-units/reorder', { orderedIds }));
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="border-border bg-surface flex items-center gap-2 rounded-[var(--radius-lg)] border p-4 shadow-[var(--shadow-card)]">
        <input
          value={newLabel}
          onChange={(e) => setNewLabel(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void addOrg();
          }}
          placeholder="새 조직구분 이름"
          maxLength={120}
          className="border-border focus-visible:ring-accent/40 min-w-0 flex-1 rounded-[var(--radius-sm)] border bg-transparent px-3 py-2 text-sm focus-visible:ring-2 focus-visible:outline-none"
        />
        <Button size="sm" onClick={() => void addOrg()} disabled={busy || !newLabel.trim()}>
          <RiAddLine size={15} aria-hidden className="mr-1" />
          추가
        </Button>
      </div>

      {orgUnits.length === 0 ? (
        <EmptyState
          icon={<RiErrorWarningLine size={18} aria-hidden />}
          title="조직구분이 없습니다"
          description="위에서 조직구분을 추가하세요."
        />
      ) : (
        <ul className="border-border bg-surface flex flex-col divide-y divide-[var(--color-border-subtle)] overflow-hidden rounded-[var(--radius-lg)] border shadow-[var(--shadow-card)]">
          {orgUnits.map((org, i) => (
            <li key={org.id} className="flex items-center gap-3 px-4 py-3">
              <span className="text-foreground-tertiary w-6 text-center text-[length:var(--text-body-sm)] tabular-nums">
                {i + 1}
              </span>
              {editing?.id === org.id ? (
                <input
                  autoFocus
                  value={editing.label}
                  onChange={(e) => setEditing({ id: org.id, label: e.target.value })}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void saveRename();
                    if (e.key === 'Escape') setEditing(null);
                  }}
                  maxLength={120}
                  className="border-border focus-visible:ring-accent/40 min-w-0 flex-1 rounded-[var(--radius-sm)] border bg-transparent px-2 py-1 text-sm focus-visible:ring-2 focus-visible:outline-none"
                />
              ) : (
                <span className="text-foreground min-w-0 flex-1 truncate text-sm font-medium">
                  {org.label}
                </span>
              )}
              <div className="flex items-center gap-1">
                {editing?.id === org.id ? (
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
                      onClick={() => void move(i, -1)}
                      disabled={busy || i === 0}
                    >
                      <RiArrowUpSLine size={16} aria-hidden />
                    </IconBtn>
                    <IconBtn
                      label="아래로"
                      onClick={() => void move(i, 1)}
                      disabled={busy || i === orgUnits.length - 1}
                    >
                      <RiArrowDownSLine size={16} aria-hidden />
                    </IconBtn>
                    <IconBtn
                      label="이름 변경"
                      onClick={() => setEditing({ id: org.id, label: org.label })}
                      disabled={busy}
                    >
                      <RiPencilLine size={15} aria-hidden />
                    </IconBtn>
                    <IconBtn
                      label="삭제"
                      onClick={() => setPendingDelete(org)}
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

      <ConfirmDialog
        open={pendingDelete !== null}
        onClose={() => setPendingDelete(null)}
        title="조직구분 삭제"
        message={
          pendingDelete
            ? `'${pendingDelete.label}'을(를) 삭제하면 각 에이전트의 이 조직구분 접근 설정도 함께 제거됩니다.`
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

  // 체크 옵션 = 실 조직구분 + '미지정'(조직 미배정 사용자 허용, 항상 마지막).
  const options: { id: string; label: string }[] = [
    ...orgUnits.map((o) => ({ id: o.id, label: o.label })),
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

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
              {options.map((org) => {
                const on = selected.has(org.id);
                return (
                  <button
                    key={org.id}
                    type="button"
                    role="checkbox"
                    aria-checked={on}
                    onClick={() => toggle(agent.agentId, org.id)}
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
                        on
                          ? 'border-accent bg-accent text-white'
                          : 'border-border-strong bg-surface',
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
      })}
    </div>
  );
}
