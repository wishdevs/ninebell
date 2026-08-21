/**
 * 화면 시뮬레이션 패널 레지스트리 — agentId → 패널 컴포넌트.
 *
 * 백엔드 자동화 그래프가 아직 없는(= workflow_id 미지정, 실행 비활성) 에이전트가
 * "화면 흐름부터 확정"하는 단계에 쓰는 더미 패널이다. 실행 API 를 타지 않고 프론트 상태만으로
 * 흐른다. 그래프가 붙어 workflow_id 가 생기면 이 레지스트리에서 항목을 빼고
 * pre-run/PRE_RUN_FORMS(workflowId 키) 또는 라이브 개입으로 승격한다.
 *
 * (레지스트리 키가 workflowId 가 아니라 agentId 인 이유: 시뮬레이션 대상은 정의상
 *  workflowId 가 없다.)
 */

import type { ComponentType } from 'react';
import type { Agent } from '@/lib/data/agents';

export interface SimulationPanelProps {
  agent: Agent;
}

export const SIMULATION_PANELS: Record<string, ComponentType<SimulationPanelProps>> = {
  // tax-invoice 는 2026-08-19 pre-run/PRE_RUN_FORMS('tax-invoice')로 승격 — 여기서 제거.
  // purchase-order-demo 는 2026-08-21 데모 종료로 제거(공용 조각은 purchase-order/ 에 잔존,
  // LivePlannerCard 가 사용). 메커니즘은 유지 — 새 화면 흐름 확정용 패널은 여기 등록한다.
};

/**
 * 전체폭이 필요한 시뮬레이션 — 대형 트리 테이블(구매발주 BOM 등)은 split 레이아웃의
 * 우측 열로는 좁다. 여기 등록된 agentId 는 agent-detail-client 가 layoutLevel 을
 * 'full'(그리드 개입과 동일 — 라이브 대기 스테이지 숨김)로 올린다. 나머지는 종전 split.
 */
export const FULL_WIDTH_SIMULATION_AGENTS: ReadonlySet<string> = new Set<string>();
