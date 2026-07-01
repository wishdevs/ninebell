'use client';

import { useEffect, useState } from 'react';
import { RiUserAddLine, RiErrorWarningLine } from '@remixicon/react';
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
import { useApiResource } from '@/app/(app)/_lib/use-api-resource';
import { MembersTable } from './members-table';
import { InviteDialog, type InviteInput } from './invite-dialog';

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
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [inviteOpen, setInviteOpen] = useState(false);
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

  // 옴니솔 최초 로그인 시 사용자가 자동 등록되므로 별도 초대 API는 없다.
  // 초대 어포던스는 권한 게이팅만 유지하고, 제출은 안내 토스트로 처리한다(플레이스홀더).
  function handleInvite({ email }: InviteInput) {
    toast.message('초대 안내', {
      description: `${email} 사용자는 옴니솔 계정으로 최초 로그인하면 자동으로 등록됩니다.`,
    });
  }

  return (
    <div className="animate-page-enter flex flex-col gap-8">
      <PageHeader
        title="멤버"
        description="조직의 전역 사용자와 역할을 관리합니다."
        action={
          caps.canWrite ? (
            <Button variant="primary" onClick={() => setInviteOpen(true)}>
              <RiUserAddLine size={16} aria-hidden />
              멤버 초대
            </Button>
          ) : undefined
        }
      />

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
          currentUserId={me.id}
          caps={caps}
          onRoleChange={handleRoleChange}
          onToggleStatus={handleToggleStatus}
          onRequestRemove={setPendingRemoval}
          onInviteClick={() => setInviteOpen(true)}
        />
      )}

      <InviteDialog
        open={inviteOpen}
        onClose={() => setInviteOpen(false)}
        onInvite={handleInvite}
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
