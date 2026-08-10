'use client';

import { FilterPill } from '@/components/ui/filter-pill';
import { ListToolbar } from '@/components/ui/list-toolbar';
import { SearchInput } from '@/components/ui/search-input';
import { SelectGroup, SelectItem, SelectLabel } from '@/components/ui/select-dropdown';
import type { Role } from '@/lib/auth/permissions';
import {
  MEMBER_ROLE_LABEL,
  MEMBER_ROLE_OPTIONS,
  MEMBER_STATUS_LABEL,
  MEMBER_STATUS_OPTIONS,
  ORG_NONE,
  type MemberStatus,
} from '@/lib/data/members';
import { buildOrgUnitTree, type OrgUnit } from '@/lib/data/org-units';

/** 조직구분 필터 값 — 'all' | ORG_NONE('__none__') | 실제 orgUnitId. */
export type OrgFilterValue = 'all' | string;

interface MembersFilterBarProps {
  query: string;
  onQueryChange: (value: string) => void;
  roleFilter: 'all' | Role;
  onRoleFilterChange: (value: 'all' | Role) => void;
  orgFilter: OrgFilterValue;
  onOrgFilterChange: (value: OrgFilterValue) => void;
  statusFilter: 'all' | MemberStatus;
  onStatusFilterChange: (value: 'all' | MemberStatus) => void;
  orgUnits: readonly OrgUnit[];
  /** useListParams().isFiltered — 초기화 버튼 노출 여부(버튼 자체는 ListToolbar 소유). */
  isFiltered: boolean;
  onReset: () => void;
}

/**
 * 멤버 화면 상단 필터 툴바 — 셸·검색 인풋·초기화 버튼은 공용 레일(ListToolbar+SearchInput)이
 * 소유하고, 이 파일은 역할/조직구분/상태 **라벨 칩 드롭다운**만 남는다. 칩은 rounded-full·라벨
 * 접두·활성 시 accent 틴트로, 테이블 행의 사각 인라인 셀렉트(편집용)와 시각적으로 확실히
 * 구분한다(필터=칩 / 편집=셀). works-client 의 필터 칩 언어를 따른다. 조직구분은 본부▸팀
 * 그룹(멤버는 팀에만 배정 가능이라 본부 자체는 옵션 없음).
 */
export function MembersFilterBar({
  query,
  onQueryChange,
  roleFilter,
  onRoleFilterChange,
  orgFilter,
  onOrgFilterChange,
  statusFilter,
  onStatusFilterChange,
  orgUnits,
  isFiltered,
  onReset,
}: MembersFilterBarProps) {
  const orgTree = buildOrgUnitTree(orgUnits);

  return (
    <ListToolbar isFiltered={isFiltered} onReset={onReset}>
      <SearchInput
        value={query}
        onChange={onQueryChange}
        placeholder="이름 또는 이메일 검색"
        ariaLabel="멤버 검색"
      />

      <div className="flex flex-wrap items-center gap-2">
        <FilterPill
          label="역할"
          ariaLabel="역할 필터"
          value={roleFilter}
          active={roleFilter !== 'all'}
          onValueChange={(v) => onRoleFilterChange(v as 'all' | Role)}
        >
          <SelectItem value="all">전체</SelectItem>
          {MEMBER_ROLE_OPTIONS.map((role) => (
            <SelectItem key={role} value={role}>
              {MEMBER_ROLE_LABEL[role]}
            </SelectItem>
          ))}
        </FilterPill>

        <FilterPill
          label="조직"
          ariaLabel="조직구분 필터"
          value={orgFilter}
          active={orgFilter !== 'all'}
          onValueChange={onOrgFilterChange}
        >
          <SelectItem value="all">전체</SelectItem>
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
        </FilterPill>

        <FilterPill
          label="상태"
          ariaLabel="상태 필터"
          value={statusFilter}
          active={statusFilter !== 'all'}
          onValueChange={(v) => onStatusFilterChange(v as 'all' | MemberStatus)}
        >
          <SelectItem value="all">전체</SelectItem>
          {MEMBER_STATUS_OPTIONS.map((s) => (
            <SelectItem key={s} value={s}>
              {MEMBER_STATUS_LABEL[s]}
            </SelectItem>
          ))}
        </FilterPill>
      </div>
    </ListToolbar>
  );
}
