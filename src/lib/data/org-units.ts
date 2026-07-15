/**
 * 조직구분(Org Unit) 타입.
 *
 * 데이터는 백엔드(`GET /org-units`)가 진실이며, 조직 구조는 ERP 조직도에서 미러링된다
 * (관리 화면에서 직접 생성/수정/삭제하지 않는다). 각 팀(leaf)의 비용구분(costType)만 설정 가능하고,
 * 에이전트별 사용 권한은 `/agent-access` 로 다룬다.
 *
 * 트리는 parentId 로 임의 깊이를 이룬다(루트=parentId===null). 비용구분·접근 배정 대상은
 * 팀(leaf, parentId!==null)뿐이다 — 루트 본부·중간 그룹은 비용을 지지 않는다.
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

/**
 * 임의 깊이 조직 트리 노드. ERP 조직도를 미러링한 구조로, children 은 sortOrder→label 정렬.
 * depth 는 렌더 들여쓰기용(루트=0).
 */
export interface OrgUnitNode {
  unit: OrgUnit;
  depth: number;
  children: OrgUnitNode[];
}

/**
 * 평탄한 `GET /org-units` 응답을 parentId 기준 임의 깊이 forest 로 구성한다.
 * 루트 = parentId===null, 형제는 sortOrder→label 로 정렬한다. seen 가드로 (비정상)순환을 방지.
 */
export function buildOrgUnitForest(orgUnits: readonly OrgUnit[]): OrgUnitNode[] {
  const byParent = new Map<string | null, OrgUnit[]>();
  for (const unit of orgUnits) {
    const siblings = byParent.get(unit.parentId) ?? [];
    siblings.push(unit);
    byParent.set(unit.parentId, siblings);
  }
  const sortSiblings = (a: OrgUnit, b: OrgUnit): number =>
    a.sortOrder - b.sortOrder || a.label.localeCompare(b.label);

  const seen = new Set<string>();
  const build = (parentId: string | null, depth: number): OrgUnitNode[] =>
    (byParent.get(parentId) ?? [])
      .slice()
      .sort(sortSiblings)
      .filter((unit) => !seen.has(unit.id))
      .map((unit) => {
        seen.add(unit.id);
        return { unit, depth, children: build(unit.id, depth + 1) };
      });

  return build(null, 0);
}

/**
 * 접근/비용구분 대상 = 팀(leaf, 자식 없음)이면서 루트(본부)가 아닌 노드.
 * 루트 본부·중간 그룹은 비용을 지지 않고 접근 배정 대상도 아니다(백엔드도 parentId null 을 거부).
 */
export function isLeafTeam(node: OrgUnitNode): boolean {
  return node.children.length === 0 && node.unit.parentId !== null;
}

/** forest 를 pre-order 로 순회하며 배정 대상 팀(leaf) unit 만 트리 순서로 모은다. */
export function leafTeamUnits(forest: readonly OrgUnitNode[]): OrgUnit[] {
  const out: OrgUnit[] = [];
  const walk = (nodes: readonly OrgUnitNode[]): void => {
    for (const node of nodes) {
      if (isLeafTeam(node)) out.push(node.unit);
      walk(node.children);
    }
  };
  walk(forest);
  return out;
}

/** 노드 하위(자기 포함)의 배정 대상 팀 id 전부 — 상위 노드 '전체 선택' 토글 대상. */
export function descendantLeafTeamIds(node: OrgUnitNode): string[] {
  const out: string[] = [];
  const walk = (n: OrgUnitNode): void => {
    if (isLeafTeam(n)) out.push(n.unit.id);
    for (const child of n.children) walk(child);
  };
  walk(node);
  return out;
}
