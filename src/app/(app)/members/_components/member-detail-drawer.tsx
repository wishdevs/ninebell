'use client';

import type { ReactNode } from 'react';
import { Avatar } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { Drawer, DrawerBody } from '@/components/ui/drawer';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select-dropdown';
import { StatusDotPill, StatusPill } from '@/components/ui/status-pill';
import type { Role } from '@/lib/auth/permissions';
import { formatDate, formatRelativeKorean } from '@/lib/data/format';
import {
  MEMBER_ROLE_BADGE,
  MEMBER_ROLE_LABEL,
  MEMBER_ROLE_OPTIONS,
  ORG_NONE,
  type MemberStatus,
  type WorkspaceMember,
} from '@/lib/data/members';
import { buildOrgUnitTree, orgUnitLabel, type OrgUnit } from '@/lib/data/org-units';
import { cn } from '@/lib/utils';
import type { MemberCaps } from './members-client';

interface MemberDetailDrawerProps {
  /** null이면 닫힘. detailId로 부모가 실시간 조회한 최신 멤버 객체 — 낙관적 수정이 즉시 반영된다. */
  member: WorkspaceMember | null;
  orgUnits: readonly OrgUnit[];
  caps: MemberCaps;
  currentUserId: string;
  onClose: () => void;
  onRoleChange: (member: WorkspaceMember, role: Role) => void;
  onOrgUnitChange: (member: WorkspaceMember, orgUnitId: string | null) => void;
  /** 절대값 상태 설정(활성/정지) — 토글이 아니라 명시적 상태라 'invited'에서도 올바르게 동작한다. */
  onSetStatus: (member: WorkspaceMember, status: MemberStatus) => void;
  onRequestRemove: (member: WorkspaceMember) => void;
}

/** 멤버 상세 드로워 — 이름 클릭으로 열리며 정보 열람 + 역할/조직구분/상태 인라인 편집. */
export function MemberDetailDrawer({
  member,
  orgUnits,
  caps,
  currentUserId,
  onClose,
  onRoleChange,
  onOrgUnitChange,
  onSetStatus,
  onRequestRemove,
}: MemberDetailDrawerProps) {
  const isSelf = member?.id === currentUserId;

  return (
    <Drawer
      open={member !== null}
      onClose={onClose}
      title={member?.name ?? ''}
      description={member?.email}
      footer={
        member ? (
          <DrawerFooterActions
            member={member}
            canDelete={caps.canDelete && !isSelf}
            onClose={onClose}
            onRequestRemove={onRequestRemove}
          />
        ) : null
      }
    >
      {member ? (
        <DrawerBody className="gap-6">
          <IdentitySection member={member} />
          <InfoSection member={member} />
          <AccessSection
            member={member}
            orgUnits={orgUnits}
            caps={caps}
            isSelf={isSelf}
            onRoleChange={onRoleChange}
            onOrgUnitChange={onOrgUnitChange}
            onSetStatus={onSetStatus}
          />
        </DrawerBody>
      ) : null}
    </Drawer>
  );
}

function SectionKicker({ children }: { children: ReactNode }) {
  return (
    <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.04em] uppercase">
      {children}
    </p>
  );
}

function IdentitySection({ member }: { member: WorkspaceMember }) {
  return (
    <div className="flex items-center gap-3">
      <Avatar userId={member.id} hasAvatar={false} label={member.name} size={48} />
      <div className="flex min-w-0 flex-col gap-1.5">
        <p className="text-foreground truncate text-base font-semibold">{member.name}</p>
        <div className="flex flex-wrap items-center gap-1.5">
          <StatusPill
            label={MEMBER_ROLE_LABEL[member.role]}
            variant="custom"
            toneClassName={MEMBER_ROLE_BADGE[member.role]}
          />
          {/* 초대됨(invited)은 활성/정지 이분법에 없으므로 비활성 라벨만 상태에 맞춰 바꾼다. */}
          <StatusDotPill
            active={member.status === 'active'}
            labelActive="활성"
            labelInactive={member.status === 'suspended' ? '정지' : '초대됨'}
          />
        </div>
      </div>
    </div>
  );
}

function InfoSection({ member }: { member: WorkspaceMember }) {
  return (
    <section className="flex flex-col gap-2">
      <SectionKicker>정보</SectionKicker>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-[length:var(--text-body-sm)]">
        <dt className="text-muted-foreground">옴니솔 ID</dt>
        <dd className="text-foreground font-mono">{member.omnisolUserid || '—'}</dd>

        <dt className="text-muted-foreground">부서</dt>
        <dd className="text-foreground">{member.department || '—'}</dd>

        <dt className="text-muted-foreground">이메일 인증</dt>
        <dd className="text-foreground">{member.emailVerified ? '인증됨' : '미인증'}</dd>

        <dt className="text-muted-foreground">마지막 활동</dt>
        <dd className="text-foreground">{formatRelativeKorean(member.lastActiveAt)}</dd>

        <dt className="text-muted-foreground">가입일</dt>
        <dd className="text-foreground">{formatDate(member.joinedAt)}</dd>

        {member.updatedAt ? (
          <>
            <dt className="text-muted-foreground">수정일</dt>
            <dd className="text-foreground">{formatDate(member.updatedAt)}</dd>
          </>
        ) : null}
      </dl>
    </section>
  );
}

interface AccessSectionProps {
  member: WorkspaceMember;
  orgUnits: readonly OrgUnit[];
  caps: MemberCaps;
  isSelf: boolean;
  onRoleChange: (member: WorkspaceMember, role: Role) => void;
  onOrgUnitChange: (member: WorkspaceMember, orgUnitId: string | null) => void;
  onSetStatus: (member: WorkspaceMember, status: MemberStatus) => void;
}

function AccessSection({
  member,
  orgUnits,
  caps,
  isSelf,
  onRoleChange,
  onOrgUnitChange,
  onSetStatus,
}: AccessSectionProps) {
  const orgTree = buildOrgUnitTree(orgUnits);
  const canEditRole = caps.canAssignRole && !isSelf;
  const canEditStatus = caps.canWrite && !isSelf;

  return (
    <section className="flex flex-col gap-4">
      <SectionKicker>권한 · 소속</SectionKicker>

      <div className="flex flex-col gap-1.5">
        <Label className="text-foreground-secondary text-xs font-normal">역할</Label>
        {canEditRole ? (
          <Select value={member.role} onValueChange={(v) => onRoleChange(member, v as Role)}>
            <SelectTrigger aria-label="역할 변경" className="h-10 w-full rounded-sm px-3 text-sm">
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
            toneClassName={cn(MEMBER_ROLE_BADGE[member.role], 'w-fit')}
          />
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label className="text-foreground-secondary text-xs font-normal">조직구분</Label>
        {caps.canWrite ? (
          <Select
            value={member.orgUnitId ?? ORG_NONE}
            onValueChange={(v) => onOrgUnitChange(member, v === ORG_NONE ? null : v)}
          >
            <SelectTrigger
              aria-label="조직구분 변경"
              className="h-10 w-full rounded-sm px-3 text-sm"
            >
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
      </div>

      {canEditStatus ? (
        <div className="flex flex-col gap-1.5">
          <Label className="text-foreground-secondary text-xs font-normal">상태</Label>
          <StatusToggle member={member} onSetStatus={onSetStatus} />
        </div>
      ) : null}
    </section>
  );
}

/** 활성↔정지 세그먼트 토글. 절대값 setStatus를 호출하므로 'invited' 상태에서도 라벨대로 동작한다. */
function StatusToggle({
  member,
  onSetStatus,
}: {
  member: WorkspaceMember;
  onSetStatus: (member: WorkspaceMember, status: MemberStatus) => void;
}) {
  const options: { value: MemberStatus; label: string; activeClass: string }[] = [
    { value: 'active', label: '활성', activeClass: 'bg-accent text-white' },
    { value: 'suspended', label: '정지', activeClass: 'bg-danger text-white' },
  ];

  return (
    <div
      role="group"
      aria-label="상태 변경"
      className="border-border bg-surface inline-flex w-fit items-center rounded-full border p-0.5"
    >
      {options.map((opt) => {
        const active = member.status === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            aria-pressed={active}
            onClick={() => onSetStatus(member, opt.value)}
            className={cn(
              'rounded-full px-3 py-1 text-xs font-medium transition-colors',
              'focus-visible:ring-accent/50 focus-visible:ring-2 focus-visible:outline-none',
              active ? opt.activeClass : 'text-foreground-tertiary hover:text-foreground-secondary',
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

function DrawerFooterActions({
  member,
  canDelete,
  onClose,
  onRequestRemove,
}: {
  member: WorkspaceMember;
  canDelete: boolean;
  onClose: () => void;
  onRequestRemove: (member: WorkspaceMember) => void;
}) {
  return (
    <div
      className={cn(
        'flex w-full items-center gap-2',
        canDelete ? 'justify-between' : 'justify-end',
      )}
    >
      {canDelete ? (
        <Button
          type="button"
          variant="danger"
          size="sm"
          onClick={() => {
            onRequestRemove(member);
            onClose();
          }}
        >
          삭제
        </Button>
      ) : null}
      <Button type="button" variant="secondary" size="sm" onClick={onClose}>
        닫기
      </Button>
    </div>
  );
}
