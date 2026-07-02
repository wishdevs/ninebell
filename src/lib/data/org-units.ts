/**
 * 조직구분(Org Unit) 기준 데이터.
 *
 * 에이전트 사용 권한을 조직구분 단위로 관리한다(조직구분 관리 메뉴). 각 에이전트는 이 조직구분들
 * 중 일부를 "사용 가능"으로 가질 수 있고, 최초 설정은 전체 선택이다. 백엔드가 없으므로 members
 * 픽스처와 동일하게 클라이언트 로컬 state 로 다룬다.
 */

export interface OrgUnit {
  id: string;
  label: string;
}

export const ORG_UNITS: readonly OrgUnit[] = [
  { id: 'exec', label: '임원실' },
  { id: 'mgmt', label: '경영본부' },
  { id: 'sales', label: '영업본부' },
  { id: 'china', label: '중국법인' },
  { id: 'fa-lab', label: 'FA연구소' },
  { id: 'mfg', label: '제조본부' },
  { id: 'imp-lab', label: 'IMP연구소' },
];

/** 전체 조직구분 id — 에이전트 최초 설정(모두 선택)에 쓴다. */
export const ALL_ORG_UNIT_IDS: readonly string[] = ORG_UNITS.map((o) => o.id);
