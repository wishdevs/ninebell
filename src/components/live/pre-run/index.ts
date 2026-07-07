/**
 * 실행 전 입력 폼 레지스트리 — workflowId → 폼 컴포넌트.
 *
 * 일부 에이전트(출장 등)는 모든 입력이 사용자 제공이라 HITL 개입 없이 **실행 전 폼**으로
 * 파라미터를 받아 무개입 완주한다. agent-detail-client 가 idle 상태에서 이 레지스트리를 보고
 * 해당 에이전트에 폼을 렌더한다. 레지스트리에 없는 에이전트는 종전대로 바로 실행한다.
 *
 * (백엔드 inputSchema 기반 일반화는 두 번째 소비자가 생길 때까지 보류 — GROUP_TOOLS 하드코딩
 *  선례를 따른다.)
 */

import type { ComponentType } from 'react';
import type { Agent } from '@/lib/data/agents';
import { TripPreRunForm } from './trip-pre-run-form';

export interface PreRunFormProps {
  agent: Agent;
  disabled?: boolean;
  /** 초기값(마지막 제출 params) — 종료 후 폼 복귀 시 값 복원용. 부모가 key 로 remount 해 재시드한다. */
  initialParams?: Record<string, unknown>;
  /** 폼 제출 → 워크플로우 파라미터를 실어 라이브 실행을 시작한다. */
  onStart: (params: Record<string, unknown>) => void;
}

export const PRE_RUN_FORMS: Record<string, ComponentType<PreRunFormProps>> = {
  'trip-domestic': TripPreRunForm,
};
