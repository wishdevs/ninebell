/**
 * 에이전트 REST 클라이언트 — 관리자용 세부설정 갱신.
 *
 * 공용 {@link api} 래퍼가 credentials·에러 정규화를 처리한다.
 *
 * 백엔드 계약(고정):
 *   PATCH /agents/{id}/settings {settings: {key: value}} → 갱신된 Agent JSON
 *   admin 미만 403, 검증 실패 400(detail 메시지 — 호출부가 errorMessage 로 토스트).
 */

import type { Agent } from '@/lib/data/agents';
import { api } from './client';

/** `PATCH /agents/{id}/settings` — 세부설정 저장. 갱신된 Agent 를 반환한다. */
export function patchAgentSettings(
  id: string,
  settings: Record<string, number | string | boolean>,
): Promise<Agent> {
  return api.patch<Agent>(`/agents/${encodeURIComponent(id)}/settings`, { settings });
}
