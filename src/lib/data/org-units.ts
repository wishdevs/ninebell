/**
 * 조직구분(Org Unit) 타입.
 *
 * 데이터는 백엔드(`GET /org-units`)가 진실이다. 관리자가 조직구분 관리 화면에서 CRUD 하고,
 * 에이전트별 사용 권한(어떤 조직구분이 어떤 에이전트를 쓸 수 있는지)은 `/agent-access` 로 다룬다.
 */

export interface OrgUnit {
  id: string;
  label: string;
  sortOrder: number;
}

/** 에이전트별 사용 가능 조직구분(백엔드 `GET /agent-access`). */
export interface AgentAccess {
  agentId: string;
  agentName: string;
  orgUnitIds: string[];
}
