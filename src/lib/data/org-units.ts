/**
 * 조직구분(Org Unit) 타입.
 *
 * 데이터는 백엔드(`GET /org-units`)가 진실이다. 관리자가 조직구분 관리 화면에서 CRUD 하고,
 * 에이전트별 사용 권한(어떤 조직구분이 어떤 에이전트를 쓸 수 있는지)은 `/agent-access` 로 다룬다.
 *
 * 2단계 트리: 본부(parentId===null) → 팀(parentId=본부 id). 비용구분(costType)은 팀에만 있다.
 */

export type OrgUnitCostType = '판관비' | '제조원가';

export interface OrgUnit {
  id: string;
  label: string;
  parentId: string | null;
  costType: OrgUnitCostType | null;
  sortOrder: number;
}

/** 에이전트별 사용 가능 조직구분(백엔드 `GET /agent-access`). 팀(leaf) id만 포함된다. */
export interface AgentAccess {
  agentId: string;
  agentName: string;
  orgUnitIds: string[];
}

/** 본부 1개 + 그 아래 팀 목록(sortOrder 정렬됨). */
export interface OrgUnitGroup {
  parent: OrgUnit;
  children: OrgUnit[];
}

/**
 * 평탄한 `GET /org-units` 응답을 본부▸팀 트리로 구성한다.
 * 본부·팀 각각 sortOrder 기준으로 정렬된다.
 */
export function buildOrgUnitTree(orgUnits: readonly OrgUnit[]): OrgUnitGroup[] {
  const parents = orgUnits
    .filter((o) => o.parentId === null)
    .slice()
    .sort((a, b) => a.sortOrder - b.sortOrder);

  return parents.map((parent) => ({
    parent,
    children: orgUnits
      .filter((o) => o.parentId === parent.id)
      .slice()
      .sort((a, b) => a.sortOrder - b.sortOrder),
  }));
}
