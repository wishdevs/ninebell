'use client';

import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select-dropdown';
import type { Role } from '@/lib/auth/permissions';
import {
  MEMBER_ROLE_LABEL,
  MEMBER_ROLE_OPTIONS,
  ORG_NONE,
  type MemberStatus,
} from '@/lib/data/members';
import { buildOrgUnitTree, type OrgUnit } from '@/lib/data/org-units';
import type { MemberCaps } from './members-client';

interface MembersBulkBarProps {
  selectedCount: number;
  caps: MemberCaps;
  orgUnits: readonly OrgUnit[];
  onSetOrgUnit: (orgUnitId: string | null) => void;
  onSetRole: (role: Role) => void;
  onSetStatus: (status: MemberStatus) => void;
  onClearSelection: () => void;
}

/**
 * 선택된 멤버가 있을 때만 나타나는 일괄 작업 바. 조직구분/역할 셀렉트는 선택된 멤버들의
 * 값이 서로 다를 수 있어 "현재 값"을 표시하지 않는 액션 트리거로 동작한다 — 선택하는 즉시
 * 전체에 적용되고, 다음 렌더에서 selectedCount가 0이 되며 바 자체가 사라진다(항상
 * placeholder로 되돌아가는 게 자연스럽다).
 */
export function MembersBulkBar({
  selectedCount,
  caps,
  orgUnits,
  onSetOrgUnit,
  onSetRole,
  onSetStatus,
  onClearSelection,
}: MembersBulkBarProps) {
  const orgTree = buildOrgUnitTree(orgUnits);

  return (
    <div className="border-accent/30 bg-accent/5 flex flex-wrap items-center gap-3 rounded-[var(--radius-lg)] border px-4 py-2.5">
      <span className="text-foreground text-[length:var(--text-body-sm)] font-semibold tabular-nums">
        {selectedCount}명 선택
      </span>

      <span className="bg-border-subtle hidden h-5 w-px sm:block" aria-hidden />

      {caps.canWrite ? (
        <Select value="" onValueChange={(v) => onSetOrgUnit(v === ORG_NONE ? null : v)}>
          <SelectTrigger aria-label="선택 멤버 조직구분 일괄 변경" className="w-40">
            <SelectValue placeholder="조직구분 변경" />
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
      ) : null}

      {caps.canAssignRole ? (
        <Select value="" onValueChange={(v) => onSetRole(v as Role)}>
          <SelectTrigger aria-label="선택 멤버 역할 일괄 변경" className="w-32">
            <SelectValue placeholder="역할 변경" />
          </SelectTrigger>
          <SelectContent>
            {MEMBER_ROLE_OPTIONS.map((role) => (
              <SelectItem key={role} value={role}>
                {MEMBER_ROLE_LABEL[role]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : null}

      {caps.canWrite ? (
        <div className="flex items-center gap-1.5">
          <Button variant="secondary" size="sm" onClick={() => onSetStatus('active')}>
            활성
          </Button>
          <Button variant="danger" size="sm" onClick={() => onSetStatus('suspended')}>
            정지
          </Button>
        </div>
      ) : null}

      <Button variant="ghost" size="sm" className="ml-auto" onClick={onClearSelection}>
        선택 해제
      </Button>
    </div>
  );
}
