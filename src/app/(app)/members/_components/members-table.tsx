'use client';

import { RiCheckboxCircleLine, RiCheckLine } from '@remixicon/react';
import { Avatar } from '@/components/ui/avatar';
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
  MEMBER_ROLE_BADGE,
  MEMBER_ROLE_LABEL,
  MEMBER_ROLE_OPTIONS,
  MEMBER_STATUS_LABEL,
  MEMBER_STATUS_VARIANT,
  ORG_NONE,
  type WorkspaceMember,
} from '@/lib/data/members';
import { buildOrgUnitTree, orgUnitLabel, type OrgUnit } from '@/lib/data/org-units';
import { formatDate, formatRelativeKorean } from '@/lib/data/format';
import { cn } from '@/lib/utils';
import { MemberRowActions } from './member-row-actions';
import type { MemberCaps } from './members-client';

interface MembersTableProps {
  /** 현재 페이지에 표시할 행(이미 필터·페이징 적용됨). */
  members: readonly WorkspaceMember[];
  /** 필터 적용 후 전체 건수 — "총 N명" 라인과 범위 표기에 사용. */
  totalCount: number;
  page: number;
  pageSize: number;
  /** 배정 가능한 조직구분 목록(에이전트 실행 조직접근 게이트 기준). */
  orgUnits: readonly OrgUnit[];
  /** 현재 로그인한 사용자 id — 본인 행은 역할 변경/액션을 잠근다. */
  currentUserId: string;
  /** 현재 사용자의 멤버 변경 권한 — 어포던스 노출을 게이팅한다. */
  caps: MemberCaps;
  selectedIds: ReadonlySet<string>;
  /** 현재 페이지 행이 모두 선택되었는지(헤더 체크박스 상태). */
  allSelected: boolean;
  /** 현재 페이지 행 중 일부만 선택되었는지(헤더 체크박스 indeterminate). */
  someSelected: boolean;
  onToggleSelectAll: () => void;
  onToggleSelect: (id: string) => void;
  onOpenDetail: (member: WorkspaceMember) => void;
  onRoleChange: (member: WorkspaceMember, role: Role) => void;
  onOrgUnitChange: (member: WorkspaceMember, orgUnitId: string | null) => void;
  onToggleStatus: (member: WorkspaceMember) => void;
  onRequestRemove: (member: WorkspaceMember) => void;
}

export function MembersTable({
  members,
  totalCount,
  page,
  pageSize,
  orgUnits,
  currentUserId,
  caps,
  selectedIds,
  allSelected,
  someSelected,
  onToggleSelectAll,
  onToggleSelect,
  onOpenDetail,
  onRoleChange,
  onOrgUnitChange,
  onToggleStatus,
  onRequestRemove,
}: MembersTableProps) {
  // 조직구분 셀렉트는 본부▸팀 그룹으로 묶는다 — 멤버는 팀에만 배정 가능.
  const orgTree = buildOrgUnitTree(orgUnits);
  const rangeStart = totalCount === 0 ? 0 : (page - 1) * pageSize + 1;
  const rangeEnd = Math.min(page * pageSize, totalCount);

  return (
    <div className="flex flex-col gap-3">
      <p className="text-muted-foreground text-[length:var(--text-body-sm)]">
        총 <span className="text-foreground font-medium tabular-nums">{totalCount}</span>명
        {totalCount > 0 && members.length < totalCount ? (
          <span className="text-foreground-tertiary">
            {' '}
            · {rangeStart}–{rangeEnd} 표시
          </span>
        ) : null}
      </p>

      <div className="border-border bg-surface overflow-x-auto rounded-[var(--radius-lg)] border shadow-[var(--shadow-card)]">
        <table className="w-full min-w-[1000px] text-left text-sm">
          <thead className="border-border text-foreground-tertiary border-b text-[length:var(--text-caption)] font-medium tracking-[0.04em]">
            <tr>
              <Th className="w-10">
                <RowCheckbox
                  checked={allSelected}
                  indeterminate={someSelected}
                  onClick={onToggleSelectAll}
                  label="현재 페이지 전체 선택"
                />
              </Th>
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
              const selected = selectedIds.has(member.id);
              return (
                <tr
                  key={member.id}
                  className={cn(
                    'border-border-subtle row-hover border-b last:border-0',
                    selected && 'bg-accent/5',
                  )}
                >
                  <Td>
                    <RowCheckbox
                      checked={selected}
                      onClick={() => onToggleSelect(member.id)}
                      label={`${member.name} 선택`}
                    />
                  </Td>

                  <Td>
                    <button
                      type="button"
                      onClick={() => onOpenDetail(member)}
                      className="group flex items-center gap-3 text-left"
                    >
                      <Avatar userId={member.id} hasAvatar={false} label={member.name} size={36} />
                      <div className="grid gap-0.5">
                        <p className="text-foreground group-hover:text-accent font-medium underline-offset-2 group-hover:underline">
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
                    </button>
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
                          {MEMBER_ROLE_OPTIONS.map((role) => (
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
                        toneClassName={MEMBER_ROLE_BADGE[member.role]}
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
                        {orgUnitLabel(orgUnits, member.orgUnitId)}
                      </span>
                    )}
                  </Td>

                  <Td>
                    <StatusPill
                      label={MEMBER_STATUS_LABEL[member.status]}
                      variant={MEMBER_STATUS_VARIANT[member.status]}
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

interface RowCheckboxProps {
  checked: boolean;
  indeterminate?: boolean;
  onClick: () => void;
  label: string;
}

/** 컴팩트 체크박스(테이블 셀 전용) — org-access 트리 체크박스와 동일한 톤·모양을 축소해 재사용. */
function RowCheckbox({ checked, indeterminate = false, onClick, label }: RowCheckboxProps) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={indeterminate ? 'mixed' : checked}
      aria-label={label}
      onClick={onClick}
      className={cn(
        'flex size-4 shrink-0 items-center justify-center rounded-[var(--radius-sm)] border transition-colors',
        'focus-visible:ring-accent/50 focus-visible:ring-2 focus-visible:outline-none',
        checked || indeterminate
          ? 'border-accent bg-accent text-white'
          : 'border-border-strong bg-surface hover:border-border',
      )}
    >
      {checked ? (
        <RiCheckLine size={11} aria-hidden />
      ) : indeterminate ? (
        <span aria-hidden className="h-[2px] w-[8px] bg-white" />
      ) : null}
    </button>
  );
}
