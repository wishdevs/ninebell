/**
 * 조직구분(Org Unit) 타입.
 *
 * 데이터는 백엔드(`GET /org-units`)가 진실이며, 조직 구조는 ERP 조직도에서 미러링된다
 * (관리 화면에서 직접 생성/수정/삭제하지 않는다). 직접 소속원을 가진 노드의 비용구분(costType)만
 * 설정 가능하고, 에이전트별 사용 권한은 `/agent-access` 로 다룬다.
 *
 * 트리는 parentId 로 임의 깊이를 이룬다(루트=parentId===null). 비용구분·접근 배정 대상은
 * 직접 소속원을 가진 노드(hasOwnMembers)다 — 순수 컨테이너(직속 인원 0)는 비용을 지지 않는다.
 */

export type OrgUnitCostType = '판관비' | '제조원가';

export interface OrgUnit {
  id: string;
  label: string;
  parentId: string | null;
  costType: OrgUnitCostType | null;
  /** ERP 조직도 기준 하위(자기 포함) 인원 수. 미집계 시 null. 직접 소속원 판정(hasOwnMembers)에 사용. */
  memberCount: number | null;
  sortOrder: number;
}

/** 에이전트별 사용 가능 조직구분(백엔드 `GET /agent-access`). 직접 소속원을 가진 노드 id만 포함된다. */
export interface AgentAccess {
  agentId: string;
  agentName: string;
  /** 소속 에이전트 그룹 id — 그룹 없는 단독 에이전트는 null. */
  groupId: string | null;
  orgUnitIds: string[];
}

/**
 * 에이전트 그룹별 사용 가능 조직구분(백엔드 `GET /agent-group-access`).
 * 최종 접근 = 그룹 허용 AND 에이전트 허용 — 그룹 없는 단독 에이전트는 에이전트 게이트만 적용된다.
 * 미설정 그룹은 백엔드가 전체 조직 id + '__none__' 로 반환한다.
 */
export interface AgentGroupAccess {
  groupId: string;
  groupName: string;
  orgUnitIds: string[];
}

/** 조직구분 id → 라벨. 못 찾거나 id가 null이면 '미지정'(멤버 테이블·상세 드로워 공용). */
export function orgUnitLabel(orgUnits: readonly OrgUnit[], id: string | null): string {
  return (id && orgUnits.find((o) => o.id === id)?.label) || '미지정';
}

/** 조직구분 셀렉트 옵션 1개 — depth 는 들여쓰기용(본부 직계=0). */
export interface OrgUnitOption {
  unit: OrgUnit;
  depth: number;
}

/** 본부(루트) 1개 + 하위 전 깊이 노드 옵션 목록(pre-order). */
export interface OrgUnitOptionGroup {
  parent: OrgUnit;
  options: OrgUnitOption[];
}

/**
 * 조직구분 셀렉트용 옵션 그룹 — 본부(루트)별로 하위 노드를 **전 깊이** pre-order 평탄화한다.
 * 백엔드(users PATCH)가 루트 배정을 거부하므로 루트 자신은 옵션에 넣지 않는다.
 * 2단계만 만들면 깊이 3 팀(예: 경영본부▸재무자원관리그룹▸회계팀)이 누락되어
 * 배정된 값이 셀렉트에 공백으로 보인다 — 반드시 전 깊이를 포함할 것.
 */
export function buildOrgUnitOptionGroups(orgUnits: readonly OrgUnit[]): OrgUnitOptionGroup[] {
  return buildOrgUnitForest(orgUnits).map((root) => {
    const options: OrgUnitOption[] = [];
    const walk = (nodes: readonly OrgUnitNode[], depth: number): void => {
      for (const node of nodes) {
        options.push({ unit: node.unit, depth });
        walk(node.children, depth + 1);
      }
    };
    walk(root.children, 0);
    return { parent: root.unit, options };
  });
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

/**
 * 노드가 '직접 소속원'을 가지는가 = ERP 하위 인원(자기 포함)에서 직속 자식들의 인원을 뺀 값이 양수.
 * 말단 팀뿐 아니라 직속 인원이 있는 중간 그룹(재무자원관리그룹·임원실·IMP연구소 등)도 참이 되며,
 * 순수 컨테이너(경영본부·영업본부 등, 직속 0)는 거짓. 이 노드들이 비용구분·접근 배정 대상이다.
 */
export function hasOwnMembers(node: OrgUnitNode): boolean {
  return (
    (node.unit.memberCount ?? 0) -
      node.children.reduce((sum, child) => sum + (child.unit.memberCount ?? 0), 0) >
    0
  );
}

/** forest 를 pre-order 로 순회하며 직접 소속원을 가진(배정 대상) unit 만 트리 순서로 모은다. */
export function ownMemberUnits(forest: readonly OrgUnitNode[]): OrgUnit[] {
  const out: OrgUnit[] = [];
  const walk = (nodes: readonly OrgUnitNode[]): void => {
    for (const node of nodes) {
      if (hasOwnMembers(node)) out.push(node.unit);
      walk(node.children);
    }
  };
  walk(forest);
  return out;
}

/**
 * 노드 하위(자기 포함)의 배정 대상 id 전부 — 상위 노드 '전체 선택' 토글 대상.
 * 노드 자신이 직접 소속원을 가지면 자기 id도 포함한다(그룹 자체 배정/집계 가능).
 */
export function descendantOwnMemberIds(node: OrgUnitNode): string[] {
  const out: string[] = [];
  const walk = (n: OrgUnitNode): void => {
    if (hasOwnMembers(n)) out.push(n.unit.id);
    for (const child of n.children) walk(child);
  };
  walk(node);
  return out;
}
