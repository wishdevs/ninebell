'use client';

import { RiCheckboxCircleLine, RiGroupLine } from '@remixicon/react';
import { Avatar } from '@/components/ui/avatar';
import { EmptyState } from '@/components/ui/empty-state';
import { StatusPill } from '@/components/ui/status-pill';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select-dropdown';
import { Td, Th } from '@/components/ui/table-cell';
import type { Role } from '@/lib/auth/permissions';
import {
  MEMBER_ROLE_LABEL,
  MEMBER_STATUS_LABEL,
  type MemberStatus,
  type WorkspaceMember,
} from '@/lib/data/members';
import { buildOrgUnitTree, type OrgUnit } from '@/lib/data/org-units';
import { formatDate, formatRelativeKorean } from '@/lib/data/format';
import { MemberRowActions } from './member-row-actions';
import type { MemberCaps } from './members-client';

interface MembersTableProps {
  members: readonly WorkspaceMember[];
  /** 배정 가능한 조직구분 목록(에이전트 실행 조직접근 게이트 기준). */
  orgUnits: readonly OrgUnit[];
  /** 현재 로그인한 사용자 id — 본인 행은 역할 변경/액션을 잠근다. */
  currentUserId: string;
  /** 현재 사용자의 멤버 변경 권한 — 어포던스 노출을 게이팅한다. */
  caps: MemberCaps;
  onRoleChange: (member: WorkspaceMember, role: Role) => void;
  onOrgUnitChange: (member: WorkspaceMember, orgUnitId: string | null) => void;
  onToggleStatus: (member: WorkspaceMember) => void;
  onRequestRemove: (member: WorkspaceMember) => void;
}

/** 모든 역할 옵션 — 인라인 역할 셀렉트에서 사용. */
const ROLE_OPTIONS: readonly Role[] = ['super_admin', 'admin', 'user'];

/** 조직구분 셀렉트의 '미지정' 센티넬(Select 값은 문자열이라야 하므로 null 대체). */
const ORG_NONE = '__none__';

/** 상태 → StatusPill 톤 매핑. */
const STATUS_VARIANT: Record<MemberStatus, 'success' | 'info' | 'danger'> = {
  active: 'success',
  invited: 'info',
  suspended: 'danger',
};

/** 읽기 전용 역할 배지 톤. */
const ROLE_BADGE: Record<Role, string> = {
  super_admin: 'bg-accent/10 text-accent',
  admin: 'bg-warning/10 text-warning',
  user: 'bg-muted text-muted-foreground',
};

export function MembersTable({
  members,
  orgUnits,
  currentUserId,
  caps,
  onRoleChange,
  onOrgUnitChange,
  onToggleStatus,
  onRequestRemove,
}: MembersTableProps) {
  const orgLabel = (id: string | null): string =>
    (id && orgUnits.find((o) => o.id === id)?.label) || '미지정';
  // 조직구분 셀렉트는 본부▸팀 그룹으로 묶는다 — 멤버는 팀에만 배정 가능.
  const orgTree = buildOrgUnitTree(orgUnits);
  if (members.length === 0) {
    return (
      <EmptyState
        icon={<RiGroupLine size={18} aria-hidden />}
        title="멤버가 없습니다"
        description="아직 등록된 사용자가 없습니다. 옴니솔 계정으로 로그인하면 사용자가 등록됩니다."
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-muted-foreground text-[length:var(--text-body-sm)]">
        총 <span className="text-foreground font-medium tabular-nums">{members.length}</span>명
      </p>

      <div className="border-border bg-surface overflow-x-auto rounded-[var(--radius-lg)] border shadow-[var(--shadow-card)]">
        <table className="w-full min-w-[960px] text-left text-sm">
          <thead className="border-border text-foreground-tertiary border-b text-[length:var(--text-caption)] font-medium tracking-[0.04em]">
            <tr>
              <Th>이름</Th>
              <Th>역할</Th>
              <Th>조직구분</Th>
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
              // 역할 셀렉트는 본인이 아니고 roles:assign 권한이 있을 때만. 그 외는 읽기 전용 배지.
              const canEditRole = !isSelf && caps.canAssignRole;
              // 행 액션(정지/삭제)은 본인이 아니고 쓰기/삭제 권한 중 하나라도 있을 때만.
              const canActOnRow = !isSelf && (caps.canWrite || caps.canDelete);
              return (
                <tr
                  key={member.id}
                  className="border-border-subtle row-hover border-b last:border-0"
                >
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
                        <p className="text-muted-foreground font-mono text-xs">
                          {member.email || '—'}
                        </p>
                      </div>
                    </div>
                  </Td>

                  <Td>
                    {canEditRole ? (
                      <Select
                        value={member.role}
                        onValueChange={(value) => onRoleChange(member, value as Role)}
                      >
                        <SelectTrigger aria-label={`${member.name} 역할`} className="w-[7.5rem]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {ROLE_OPTIONS.map((role) => (
                            <SelectItem key={role} value={role}>
                              {MEMBER_ROLE_LABEL[role]}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <StatusPill
                        label={MEMBER_ROLE_LABEL[member.role]}
                        variant="custom"
                        toneClassName={ROLE_BADGE[member.role]}
                      />
                    )}
                  </Td>

                  <Td>
                    {caps.canWrite ? (
                      <Select
                        value={member.orgUnitId ?? ORG_NONE}
                        onValueChange={(value) =>
                          onOrgUnitChange(member, value === ORG_NONE ? null : value)
                        }
                      >
                        <SelectTrigger aria-label={`${member.name} 조직구분`} className="w-[9rem]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value={ORG_NONE}>미지정</SelectItem>
                          {orgTree.map(({ parent, children }) =>
                            children.length === 0 ? null : (
                              <SelectGroup key={parent.id}>
                                <SelectLabel>{parent.label}</SelectLabel>
                                {children.map((child) => (
                                  <SelectItem key={child.id} value={child.id}>
                                    {child.label}
                                  </SelectItem>
                                ))}
                              </SelectGroup>
                            ),
                          )}
                        </SelectContent>
                      </Select>
                    ) : (
                      <span className="text-muted-foreground text-xs">
                        {orgLabel(member.orgUnitId)}
                      </span>
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
                        <RiCheckboxCircleLine size={13} className="text-success" aria-hidden />
                        인증됨
                      </span>
                    ) : (
                      <StatusPill label="미인증" variant="warn" />
                    )}
                  </Td>

                  <Td className="text-muted-foreground text-xs tabular-nums">
                    {formatRelativeKorean(member.lastActiveAt)}
                  </Td>

                  <Td className="text-muted-foreground text-xs tabular-nums">
                    {formatDate(member.joinedAt)}
                  </Td>

                  <Td className="text-right">
                    {canActOnRow ? (
                      <MemberRowActions
                        member={member}
                        caps={caps}
                        onToggleStatus={onToggleStatus}
                        onRequestRemove={onRequestRemove}
                      />
                    ) : (
                      <span className="text-foreground-tertiary text-xs">—</span>
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
