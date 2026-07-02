'use client';

import { useEffect, useState } from 'react';
import { RiErrorWarningLine } from '@remixicon/react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { PageHeader } from '@/components/ui/page-header';
import { Spinner } from '@/components/ui/spinner';
import { EmptyState } from '@/components/ui/empty-state';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { ApiError, api } from '@/lib/api/client';
import { PERMISSIONS, type Role } from '@/lib/auth/permissions';
import { usePermissions } from '@/hooks/use-permissions';
import { useCurrentUser } from '@/app/(app)/providers/user-provider';
import { MEMBER_ROLE_LABEL, type MemberStatus, type WorkspaceMember } from '@/lib/data/members';
import type { OrgUnit } from '@/lib/data/org-units';
import { useApiResource } from '@/app/(app)/_lib/use-api-resource';
import { MembersTable } from './members-table';

/** 멤버 변경 권한 묶음 — 테이블이 어떤 어포던스를 노출할지 결정한다. */
export interface MemberCaps {
  /** 역할 변경(roles:assign). 없으면 역할 셀렉트 대신 읽기 전용 배지. */
  canAssignRole: boolean;
  /** 정지/활성·초대(users:write). */
  canWrite: boolean;
  /** 멤버 삭제(users:delete). */
  canDelete: boolean;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 403) return '이 작업을 수행할 권한이 없습니다.';
    if (err.status === 0) return '서버에 연결할 수 없습니다.';
    return err.message;
  }
  return '요청을 처리하지 못했습니다.';
}

/**
 * 멤버 관리 화면의 상태 소유자. `GET /users`로 전역 사용자 목록을 로드하고,
 * 역할 변경/정지·활성/삭제를 낙관적으로 반영하되 실패 시 롤백한다. 모든 변경은
 * 권한(roles:assign·users:write·users:delete)으로 게이팅되며 `user` 롤은 읽기 전용.
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

  // 서버 스냅샷이 도착/갱신되면 편집 가능한 로컬 상태로 동기화한다.
  useEffect(() => {
    if (data) setMembers(data);
  }, [data]);

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

  async function handleToggleStatus(member: WorkspaceMember) {
    const next: MemberStatus = member.status === 'suspended' ? 'active' : 'suspended';
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

  // 사용자 생성은 옴니솔 최초 로그인 → 회원가입 플로우가 담당한다(별도 초대 없음).
  return (
    <div className="animate-page-enter flex flex-col gap-8">
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
      ) : (
        <MembersTable
          members={members}
          orgUnits={orgUnits}
          currentUserId={me.id}
          caps={caps}
          onRoleChange={handleRoleChange}
          onOrgUnitChange={handleOrgUnitChange}
          onToggleStatus={handleToggleStatus}
          onRequestRemove={setPendingRemoval}
        />
      )}

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
