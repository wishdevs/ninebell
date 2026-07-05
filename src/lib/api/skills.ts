/**
 * 공용 스킬 카탈로그 REST 클라이언트.
 *
 * 백엔드 카탈로그(app/services/skills.py — 단일 소스)와 스킬별 사용 에이전트
 * 역인덱스를 조회한다. 인증(세션 쿠키) 필요. 공용 {@link api} 래퍼가
 * credentials·에러 정규화를 처리한다.
 *
 * 백엔드 계약(고정):
 *   GET /skills → {items: [{key, label, description, layer, agents: [{id, name}]}]}
 */

import { api } from './client';

/** 스킬 계층 — omnisol(더존 화면 조작) · common(시스템 공통) · llm(모델 판단). */
export type SkillLayer = 'omnisol' | 'common' | 'llm';

/** 스킬을 사용하는 에이전트 참조(상세 링크용). */
export interface SkillAgentRef {
  id: string;
  name: string;
}

/** 카탈로그 한 항목 + 사용 에이전트 역인덱스. */
export interface SkillItem {
  key: string;
  label: string;
  description: string;
  layer: SkillLayer;
  agents: SkillAgentRef[];
}

/** `GET /skills` — 스킬 카탈로그 전체(카탈로그 정의 순서). */
export async function fetchSkills(): Promise<SkillItem[]> {
  const res = await api.get<{ items?: SkillItem[] }>('/skills');
  return res.items ?? [];
}
