'use client';

import { useEffect, useMemo, useState } from 'react';
import { RiErrorWarningLine, RiFilterOffLine, RiGroupLine } from '@remixicon/react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { PageHeader } from '@/components/ui/page-header';
import { Spinner } from '@/components/ui/spinner';
import { EmptyState } from '@/components/ui/empty-state';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Pagination } from '@/components/ui/pagination';
import { api, errorMessage } from '@/lib/api/client';
import { PERMISSIONS, type Role } from '@/lib/auth/permissions';
import { usePermissions } from '@/hooks/use-permissions';
import { useCurrentUser } from '@/app/(app)/providers/user-provider';
import { MEMBER_ROLE_LABEL, type MemberStatus, type WorkspaceMember } from '@/lib/data/members';
import type { OrgUnit } from '@/lib/data/org-units';
import { useApiResource } from '@/app/(app)/_lib/use-api-resource';
import { MembersTable } from './members-table';
import { MembersFilterBar, type OrgFilterValue } from './members-filter-bar';
import { MembersBulkBar } from './members-bulk-bar';
import { MemberDetailDrawer } from './member-detail-drawer';

/** 한 페이지에 보여줄 멤버 수. */
const PAGE_SIZE = 20;

/** 멤버 변경 권한 묶음 — 테이블이 어떤 어포던스를 노출할지 결정한다. */
export interface MemberCaps {
  /** 역할 변경(roles:assign). 없으면 역할 셀렉트 대신 읽기 전용 배지. */
  canAssignRole: boolean;
  /** 정지/활성·초대(users:write). */
  canWrite: boolean;
  /** 멤버 삭제(users:delete). */
  canDelete: boolean;
}

/**
 * 멤버 관리 화면의 상태 소유자. `GET /users`로 전역 사용자 목록을 로드하고,
 * 역할 변경/정지·활성/삭제를 낙관적으로 반영하되 실패 시 롤백한다. 모든 변경은
 * 권한(roles:assign·users:write·users:delete)으로 게이팅되며 `user` 롤은 읽기 전용.
 * 검색/역할/조직구분/상태 필터 + 페이징 + 다중 선택 일괄 변경 + 상세 드로워를 더한다.
 */
export function MembersClient() {
  const me = useCurrentUser();
  const { has } = usePermissions();
  const caps: MemberCaps = {
    canAssignRole: has(PERMISSIONS.ROLES_ASSIGN),
    canWrite: has(PERMISSIONS.USERS_WRITE),
    canDelete: has(PERMISSIONS.USERS_DELETE),
  };

  const { status, data, error, reload } = useApiResource<WorkspaceMember[]>('/users');
  // 조직구분 배정 셀렉트용 목록(GET /org-units, 관리자 전용). 실패 시 빈 목록으로 무해히 강등.
  const { data: orgUnitsData } = useApiResource<OrgUnit[]>('/org-units');
  const orgUnits = orgUnitsData ?? [];
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [pendingRemoval, setPendingRemoval] = useState<WorkspaceMember | null>(null);

  const [query, setQuery] = useState('');
  const [roleFilter, setRoleFilter] = useState<'all' | Role>('all');
  const [orgFilter, setOrgFilter] = useState<OrgFilterValue>('all');
  const [statusFilter, setStatusFilter] = useState<'all' | MemberStatus>('all');
  const [page, setPage] = useState(1);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [detailId, setDetailId] = useState<string | null>(null);

  // 서버 스냅샷이 도착/갱신되면 편집 가능한 로컬 상태로 동기화한다.
  useEffect(() => {
    if (data) setMembers(data);
  }, [data]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return members.filter((m) => {
      if (roleFilter !== 'all' && m.role !== roleFilter) return false;
      if (statusFilter !== 'all' && m.status !== statusFilter) return false;
      if (orgFilter === '__none__') {
        if (m.orgUnitId !== null) return false;
      } else if (orgFilter !== 'all' && m.orgUnitId !== orgFilter) {
        return false;
      }
      if (!q) return true;
      return `${m.name} ${m.email}`.toLowerCase().includes(q);
    });
  }, [members, query, roleFilter, orgFilter, statusFilter]);

  // 필터가 바뀌면 1페이지로. 필터 값 자체가 dependency라 필터 변경 시에만 실행된다.
  useEffect(() => {
    setPage(1);
  }, [query, roleFilter, orgFilter, statusFilter]);

  // 필터·삭제·일괄변경으로 filtered가 줄어도 렌더 시점에 유효 페이지를 파생해 슬라이스한다
  // (setPage를 effect에서 하면 페인트 이후라 stale-high 페이지의 빈 테이블이 한 프레임 깜빡인다).
  const lastPage = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const effectivePage = Math.min(page, lastPage);

  // 파생값과 어긋난 page 상태는 페인트 이후 조용히 맞춘다(렌더는 이미 effectivePage 기준).
  useEffect(() => {
    if (page !== effectivePage) setPage(effectivePage);
  }, [page, effectivePage]);

  const paged = useMemo(
    () => filtered.slice((effectivePage - 1) * PAGE_SIZE, effectivePage * PAGE_SIZE),
    [filtered, effectivePage],
  );

  const pagedIds = useMemo(() => paged.map((m) => m.id), [paged]);
  const allPagedSelected = pagedIds.length > 0 && pagedIds.every((id) => selectedIds.has(id));
  const somePagedSelected = !allPagedSelected && pagedIds.some((id) => selectedIds.has(id));

  const detailMember = detailId ? (members.find((m) => m.id === detailId) ?? null) : null;

  function resetFilters() {
    setQuery('');
    setRoleFilter('all');
    setOrgFilter('all');
    setStatusFilter('all');
  }

  // 현재 페이지 행 기준 전체 선택/해제(다른 페이지에서 이미 선택된 항목은 유지).
  function toggleSelectAll() {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allPagedSelected) {
        pagedIds.forEach((id) => next.delete(id));
      } else {
        pagedIds.forEach((id) => next.add(id));
      }
      return next;
    });
  }

  function toggleSelectOne(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleRoleChange(member: WorkspaceMember, role: Role) {
    if (member.role === role) return;
    const snapshot = members;
    setMembers((prev) => prev.map((m) => (m.id === member.id ? { ...m, role } : m)));
    try {
      const updated = await api.patch<WorkspaceMember>(`/users/${member.id}/role`, { role });
      setMembers((prev) => prev.map((m) => (m.id === member.id ? updated : m)));
      toast.success(`${member.name} 님의 역할을 ${MEMBER_ROLE_LABEL[role]}(으)로 변경했습니다`);
    } catch (err: unknown) {
      setMembers(snapshot);
      toast.error(errorMessage(err));
    }
  }

  async function handleOrgUnitChange(member: WorkspaceMember, orgUnitId: string | null) {
    if ((member.orgUnitId ?? null) === orgUnitId) return;
    const snapshot = members;
    setMembers((prev) => prev.map((m) => (m.id === member.id ? { ...m, orgUnitId } : m)));
    try {
      const updated = await api.patch<WorkspaceMember>(`/users/${member.id}`, { orgUnitId });
      setMembers((prev) => prev.map((m) => (m.id === member.id ? updated : m)));
      const label = orgUnitId ? orgUnits.find((o) => o.id === orgUnitId)?.label : null;
      toast.success(
        label
          ? `${member.name} 님의 조직구분을 ${label}(으)로 설정했습니다`
          : `${member.name} 님의 조직구분을 해제했습니다`,
      );
    } catch (err: unknown) {
      setMembers(snapshot);
      toast.error(errorMessage(err));
    }
  }

  // 절대값 상태 설정 — 드로워 세그먼트(활성/정지)가 'invited'에서도 라벨대로 동작하도록 토글이 아닌 명시 상태.
  async function handleSetStatus(member: WorkspaceMember, next: MemberStatus) {
    if (member.status === next) return;
    const snapshot = members;
    setMembers((prev) => prev.map((m) => (m.id === member.id ? { ...m, status: next } : m)));
    try {
      const updated = await api.patch<WorkspaceMember>(`/users/${member.id}`, { status: next });
      setMembers((prev) => prev.map((m) => (m.id === member.id ? updated : m)));
      toast.success(
        next === 'suspended'
          ? `${member.name} 님을 정지했습니다`
          : `${member.name} 님을 활성화했습니다`,
      );
    } catch (err: unknown) {
      setMembers(snapshot);
      toast.error(errorMessage(err));
    }
  }

  // 행 액션(⋯) 전용 토글 — 현재 상태를 반전. 드로워는 절대값 handleSetStatus를 쓴다.
  function handleToggleStatus(member: WorkspaceMember) {
    void handleSetStatus(member, member.status === 'suspended' ? 'active' : 'suspended');
  }

  async function handleConfirmRemove() {
    if (!pendingRemoval) return;
    const removed = pendingRemoval;
    const snapshot = members;
    setMembers((prev) => prev.filter((m) => m.id !== removed.id));
    try {
      await api.delete(`/users/${removed.id}`);
      toast.success(`${removed.name} 님을 삭제했습니다`);
    } catch (err: unknown) {
      setMembers(snapshot);
      toast.error(errorMessage(err));
    }
  }

  /**
   * 일괄 변경 공용 러너 — ids 각각을 낙관적으로 반영하고 `Promise.allSettled`로 병렬 요청한다.
   * 실패한 id만 원래 값으로 롤백하고 "N명 변경, M명 실패" 요약 토스트를 띄운다(부분 실패 허용).
   * 백엔드에 벌크 엔드포인트가 없어 단건 PATCH를 개별 호출하는 방식이 유일한 선택지다.
   */
  async function bulkUpdate(
    ids: string[],
    optimistic: (m: WorkspaceMember) => WorkspaceMember,
    request: (id: string) => Promise<WorkspaceMember>,
  ): Promise<void> {
    const snapshot = new Map(members.filter((m) => ids.includes(m.id)).map((m) => [m.id, m]));
    setMembers((prev) => prev.map((m) => (snapshot.has(m.id) ? optimistic(m) : m)));

    const results = await Promise.allSettled(ids.map((id) => request(id)));
    const failedIds = new Set<string>();
    results.forEach((result, i) => {
      const id = ids[i];
      if (result.status === 'fulfilled') {
        const updated = result.value;
        setMembers((prev) => prev.map((m) => (m.id === id ? updated : m)));
      } else {
        failedIds.add(id);
      }
    });
    if (failedIds.size > 0) {
      setMembers((prev) => prev.map((m) => (failedIds.has(m.id) ? (snapshot.get(m.id) ?? m) : m)));
    }

    const ok = ids.length - failedIds.size;
    if (failedIds.size === 0) toast.success(`${ok}명 변경했습니다`);
    else toast.error(`${ok}명 변경, ${failedIds.size}명 실패`);
  }

  function handleBulkSetOrgUnit(orgUnitId: string | null) {
    const ids = Array.from(selectedIds);
    setSelectedIds(new Set());
    void bulkUpdate(
      ids,
      (m) => ({ ...m, orgUnitId }),
      (id) => api.patch<WorkspaceMember>(`/users/${id}`, { orgUnitId }),
    );
  }

  function handleBulkSetRole(role: Role) {
    // 본인 역할은 일괄 변경 대상에서 제외(행/드로워와 동일한 자기보호 — 자기 강등 방지).
    const ids = Array.from(selectedIds).filter((id) => id !== me.id);
    setSelectedIds(new Set());
    if (ids.length === 0) {
      toast.error('본인 역할은 일괄 변경할 수 없습니다');
      return;
    }
    void bulkUpdate(
      ids,
      (m) => ({ ...m, role }),
      (id) => api.patch<WorkspaceMember>(`/users/${id}/role`, { role }),
    );
  }

  function handleBulkSetStatus(memberStatus: MemberStatus) {
    // 본인 상태는 일괄 변경 대상에서 제외(자기 정지로 인한 잠금 방지).
    const ids = Array.from(selectedIds).filter((id) => id !== me.id);
    setSelectedIds(new Set());
    if (ids.length === 0) {
      toast.error('본인 상태는 일괄 변경할 수 없습니다');
      return;
    }
    void bulkUpdate(
      ids,
      (m) => ({ ...m, status: memberStatus }),
      (id) => api.patch<WorkspaceMember>(`/users/${id}`, { status: memberStatus }),
    );
  }

  // 사용자 생성은 옴니솔 최초 로그인 → 회원가입 플로우가 담당한다(별도 초대 없음).
  return (
    <div className="animate-page-enter flex flex-col gap-6">
      <PageHeader title="멤버" description="조직의 전역 사용자와 역할을 관리합니다." />

      {status === 'loading' ? (
        <div className="text-muted-foreground flex items-center justify-center gap-2 py-16 text-sm">
          <Spinner size={18} label="멤버 불러오는 중" />
          멤버 목록을 불러오는 중…
        </div>
      ) : status === 'error' ? (
        <EmptyState
          icon={<RiErrorWarningLine size={18} aria-hidden />}
          title="멤버를 불러오지 못했습니다"
          description={errorMessage(error)}
          action={
            <Button variant="secondary" size="sm" onClick={reload}>
              다시 시도
            </Button>
          }
        />
      ) : members.length === 0 ? (
        <EmptyState
          icon={<RiGroupLine size={18} aria-hidden />}
          title="멤버가 없습니다"
          description="아직 등록된 사용자가 없습니다. 옴니솔 계정으로 로그인하면 사용자가 등록됩니다."
        />
      ) : (
        <>
          <MembersFilterBar
            query={query}
            onQueryChange={setQuery}
            roleFilter={roleFilter}
            onRoleFilterChange={setRoleFilter}
            orgFilter={orgFilter}
            onOrgFilterChange={setOrgFilter}
            statusFilter={statusFilter}
            onStatusFilterChange={setStatusFilter}
            orgUnits={orgUnits}
            onReset={resetFilters}
          />

          {selectedIds.size > 0 ? (
            <MembersBulkBar
              selectedCount={selectedIds.size}
              caps={caps}
              orgUnits={orgUnits}
              onSetOrgUnit={handleBulkSetOrgUnit}
              onSetRole={handleBulkSetRole}
              onSetStatus={handleBulkSetStatus}
              onClearSelection={() => setSelectedIds(new Set())}
            />
          ) : null}

          {filtered.length === 0 ? (
            <EmptyState
              icon={<RiFilterOffLine size={18} aria-hidden />}
              title="조건에 맞는 멤버가 없습니다"
              description="검색어나 필터를 바꿔 보세요."
              action={
                <Button variant="secondary" size="sm" onClick={resetFilters}>
                  필터 초기화
                </Button>
              }
            />
          ) : (
            <>
              <MembersTable
                members={paged}
                totalCount={filtered.length}
                page={effectivePage}
                pageSize={PAGE_SIZE}
                orgUnits={orgUnits}
                currentUserId={me.id}
                caps={caps}
                selectedIds={selectedIds}
                allSelected={allPagedSelected}
                someSelected={somePagedSelected}
                onToggleSelectAll={toggleSelectAll}
                onToggleSelect={toggleSelectOne}
                onOpenDetail={(member) => setDetailId(member.id)}
                onRoleChange={handleRoleChange}
                onOrgUnitChange={handleOrgUnitChange}
                onToggleStatus={handleToggleStatus}
                onRequestRemove={setPendingRemoval}
              />
              <Pagination
                page={effectivePage}
                pageSize={PAGE_SIZE}
                total={filtered.length}
                onPageChange={setPage}
              />
            </>
          )}
        </>
      )}

      <MemberDetailDrawer
        member={detailMember}
        orgUnits={orgUnits}
        caps={caps}
        currentUserId={me.id}
        onClose={() => setDetailId(null)}
        onRoleChange={handleRoleChange}
        onOrgUnitChange={handleOrgUnitChange}
        onSetStatus={handleSetStatus}
        onRequestRemove={setPendingRemoval}
      />

      {pendingRemoval ? (
        <ConfirmDialog
          open
          onClose={() => setPendingRemoval(null)}
          title="멤버 삭제"
          message={
            <>
              <span className="text-foreground font-medium">{pendingRemoval.name}</span> 님을 전역
              사용자에서 삭제합니다. 이 작업은 되돌릴 수 없습니다.
            </>
          }
          confirmLabel="삭제"
          onConfirm={handleConfirmRemove}
        />
      ) : null}
    </div>
  );
}
