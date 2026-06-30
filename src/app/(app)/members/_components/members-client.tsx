'use client';

import { useState } from 'react';
import { RiUserAddLine } from '@remixicon/react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { PageHeader } from '@/components/ui/page-header';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { WORKSPACE_MEMBERS, type MemberStatus, type WorkspaceMember } from '@/lib/data/members';
import { CURRENT_USER, ROLE_LABEL, type OrgRole } from '@/lib/data/workspace';
import { MembersTable } from './members-table';
import { InviteDialog, type InviteInput } from './invite-dialog';

/**
 * 멤버 관리 화면의 상태 소유자. WORKSPACE_MEMBERS를 로컬 state로 복사한 뒤
 * 역할 변경 / 정지·활성 / 삭제 / 초대를 모두 불변 업데이트로 낙관적 반영한다.
 * 백엔드가 없으므로 모든 변경은 메모리 안에서만 일어난다.
 */
export function MembersClient() {
  const [members, setMembers] = useState<WorkspaceMember[]>(() => [...WORKSPACE_MEMBERS]);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [pendingRemoval, setPendingRemoval] = useState<WorkspaceMember | null>(null);

  function handleRoleChange(member: WorkspaceMember, role: OrgRole) {
    if (member.role === role) return;
    setMembers((prev) => prev.map((m) => (m.id === member.id ? { ...m, role } : m)));
    toast.success(`${member.name} 님의 역할을 ${ROLE_LABEL[role]}(으)로 변경했습니다`);
  }

  function handleToggleStatus(member: WorkspaceMember) {
    const next: MemberStatus = member.status === 'suspended' ? 'active' : 'suspended';
    setMembers((prev) => prev.map((m) => (m.id === member.id ? { ...m, status: next } : m)));
    toast.success(
      next === 'suspended'
        ? `${member.name} 님을 정지했습니다`
        : `${member.name} 님을 활성화했습니다`,
    );
  }

  function handleConfirmRemove() {
    if (!pendingRemoval) return;
    const removed = pendingRemoval;
    setMembers((prev) => prev.filter((m) => m.id !== removed.id));
    toast.success(`${removed.name} 님을 삭제했습니다`);
  }

  function handleInvite({ email, role }: InviteInput) {
    const now = new Date().toISOString();
    const invited: WorkspaceMember = {
      id: `u-invite-${Date.now()}`,
      name: email.split('@')[0],
      email,
      role,
      status: 'invited',
      emailVerified: false,
      lastActiveAt: now,
      joinedAt: now,
    };
    setMembers((prev) => [...prev, invited]);
    toast.success('초대를 보냈습니다');
  }

  return (
    <div className="animate-page-enter flex flex-col gap-8">
      <PageHeader
        title="멤버"
        description="워크스페이스 멤버와 역할을 관리합니다."
        action={
          <Button variant="primary" onClick={() => setInviteOpen(true)}>
            <RiUserAddLine size={16} aria-hidden />
            멤버 초대
          </Button>
        }
      />

      <MembersTable
        members={members}
        currentUserId={CURRENT_USER.id}
        onRoleChange={handleRoleChange}
        onToggleStatus={handleToggleStatus}
        onRequestRemove={setPendingRemoval}
        onInviteClick={() => setInviteOpen(true)}
      />

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
              <span className="text-foreground font-medium">{pendingRemoval.name}</span> 님을 이
              워크스페이스에서 삭제합니다. 이 작업은 되돌릴 수 없습니다.
            </>
          }
          confirmLabel="삭제"
          onConfirm={handleConfirmRemove}
        />
      ) : null}
    </div>
  );
}
