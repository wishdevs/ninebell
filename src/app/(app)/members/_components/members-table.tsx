'use client';

import { CheckCircle2, UserPlus, Users } from 'lucide-react';
import { Avatar } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { StatusPill } from '@/components/ui/status-pill';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select-dropdown';
import { cn } from '@/lib/utils';
import {
  MEMBER_STATUS_LABEL,
  type MemberStatus,
  type WorkspaceMember,
} from '@/lib/data/members';
import { ROLE_LABEL, type OrgRole } from '@/lib/data/workspace';
import { formatDate, formatRelativeKorean } from '@/lib/data/format';
import { MemberRowActions } from './member-row-actions';

interface MembersTableProps {
  members: readonly WorkspaceMember[];
  /** 현재 로그인한 사용자 id — 본인 행은 역할 변경/액션을 잠근다. */
  currentUserId: string;
  onRoleChange: (member: WorkspaceMember, role: OrgRole) => void;
  onToggleStatus: (member: WorkspaceMember) => void;
  onRequestRemove: (member: WorkspaceMember) => void;
  /** 빈 상태에서 초대 다이얼로그를 여는 콜백. */
  onInviteClick: () => void;
}

/** 모든 역할 옵션 — 인라인 역할 셀렉트에서 사용. */
const ROLE_OPTIONS: readonly OrgRole[] = ['owner', 'admin', 'member', 'client'];

/** 상태 → StatusPill 톤 매핑. */
const STATUS_VARIANT: Record<MemberStatus, 'success' | 'info' | 'danger'> = {
  active: 'success',
  invited: 'info',
  suspended: 'danger',
};

/** 본인 행에서 셀렉트 대신 보여줄 역할 배지 톤. */
const ROLE_BADGE: Record<OrgRole, string> = {
  owner: 'bg-accent/10 text-accent',
  admin: 'bg-warning/10 text-warning',
  member: 'bg-muted text-muted-foreground',
  client: 'bg-info/10 text-info',
};

export function MembersTable({
  members,
  currentUserId,
  onRoleChange,
  onToggleStatus,
  onRequestRemove,
  onInviteClick,
}: MembersTableProps) {
  if (members.length === 0) {
    return (
      <EmptyState
        icon={<Users size={18} aria-hidden />}
        title="멤버가 없습니다"
        description="아직 이 워크스페이스에 멤버가 없습니다. 새 멤버를 초대해 협업을 시작하세요."
        action={
          <Button variant="primary" size="sm" onClick={onInviteClick}>
            <UserPlus size={16} aria-hidden />
            멤버 초대
          </Button>
        }
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-muted-foreground text-[length:var(--text-body-sm)]">
        총 <span className="text-foreground font-medium tabular-nums">{members.length}</span>명
      </p>

      <div className="border-border bg-surface overflow-x-auto rounded-[var(--radius-lg)] border shadow-[var(--shadow-card)]">
        <table className="w-full min-w-[860px] text-left text-sm">
          <thead className="border-border text-foreground-tertiary border-b text-[length:var(--text-caption)] font-medium tracking-[0.04em] uppercase">
            <tr>
              <Th>이름</Th>
              <Th>역할</Th>
              <Th>상태</Th>
              <Th>이메일 인증</Th>
              <Th>마지막 활동</Th>
              <Th>가입일</Th>
              <th className="px-4 py-3">
                <span className="sr-only">액션</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {members.map((member) => {
              const isSelf = member.id === currentUserId;
              return (
                <tr key={member.id} className="border-border-subtle row-hover border-b last:border-0">
                  <Td>
                    <div className="flex items-center gap-3">
                      <Avatar userId={member.id} hasAvatar={false} label={member.name} size={36} />
                      <div className="grid gap-0.5">
                        <p className="text-foreground font-medium">
                          {member.name}
                          {isSelf ? (
                            <span className="text-foreground-tertiary ml-1.5 text-xs font-normal">
                              (나)
                            </span>
                          ) : null}
                        </p>
                        <p className="text-muted-foreground font-mono text-xs">{member.email}</p>
                      </div>
                    </div>
                  </Td>

                  <Td>
                    {isSelf ? (
                      <RoleBadge role={member.role} />
                    ) : (
                      <Select
                        value={member.role}
                        onValueChange={(value) => onRoleChange(member, value as OrgRole)}
                      >
                        <SelectTrigger
                          aria-label={`${member.name} 역할`}
                          className="w-[7.5rem]"
                        >
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {ROLE_OPTIONS.map((role) => (
                            <SelectItem key={role} value={role}>
                              {ROLE_LABEL[role]}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                  </Td>

                  <Td>
                    <StatusPill
                      label={MEMBER_STATUS_LABEL[member.status]}
                      variant={STATUS_VARIANT[member.status]}
                    />
                  </Td>

                  <Td>
                    {member.emailVerified ? (
                      <span className="text-muted-foreground inline-flex items-center gap-1 text-xs">
                        <CheckCircle2 size={13} className="text-success" aria-hidden />
                        인증됨
                      </span>
                    ) : (
                      <StatusPill label="미인증" variant="warn" />
                    )}
                  </Td>

                  <Td className="text-muted-foreground tabular-nums text-xs">
                    {formatRelativeKorean(member.lastActiveAt)}
                  </Td>

                  <Td className="text-muted-foreground tabular-nums text-xs">
                    {formatDate(member.joinedAt)}
                  </Td>

                  <Td className="text-right">
                    {isSelf ? (
                      <span className="text-foreground-tertiary text-xs">—</span>
                    ) : (
                      <MemberRowActions
                        member={member}
                        onToggleStatus={onToggleStatus}
                        onRequestRemove={onRequestRemove}
                      />
                    )}
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RoleBadge({ role }: { role: OrgRole }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium',
        ROLE_BADGE[role],
      )}
    >
      {ROLE_LABEL[role]}
    </span>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-4 py-3 font-medium whitespace-nowrap">{children}</th>;
}

function Td({ children, className }: { children: React.ReactNode; className?: string }) {
  return <td className={cn('px-4 py-3 align-middle', className)}>{children}</td>;
}
