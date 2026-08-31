/**
 * 구매발주 계획서(저장본) API 클라이언트.
 *
 * 백엔드 계약(고정):
 *   GET /purchase-order/plans?limit&offset → {items, total, limit, offset} (최신순)
 *   GET /purchase-order/plans/{id}         → PlanRecord (요약 + plan 페이로드 + BOM 요약)
 */

import { api } from '@/lib/api/client';
import type { PlanSubmit } from '@/lib/live/types';

export interface PlanRecordSummary {
  id: string;
  runId: string | null;
  agentId: string;
  project: { code: string; name: string };
  wbs: string;
  unitCount: number;
  totalAmount: number;
  userId: string;
  userDisplayName: string | null;
  createdAt: string;
}

export interface PlanBomSummary {
  gridRows: number;
  machines: number;
  modules: number;
  parts: number;
  purchasableParts: number;
}

export interface PlanRecord extends PlanRecordSummary {
  plan: PlanSubmit;
  bomSummary: PlanBomSummary | null;
}

export async function fetchPlans(query: {
  limit: number;
  offset: number;
  q?: string;
}): Promise<{ items: PlanRecordSummary[]; total: number }> {
  const params = new URLSearchParams({
    limit: String(query.limit),
    offset: String(query.offset),
  });
  if (query.q?.trim()) params.set('q', query.q.trim());
  const res = await api.get<{ items?: PlanRecordSummary[]; total: number }>(
    `/purchase-order/plans?${params}`,
  );
  return { items: res.items ?? [], total: res.total };
}

export function fetchPlan(id: string): Promise<PlanRecord> {
  return api.get<PlanRecord>(`/purchase-order/plans/${encodeURIComponent(id)}`);
}

/** 자동 재개 후보 — 저장된 구매요청 중 상신·발주 미완이 남은 프로젝트(본인 런 기준). */
export interface ResumeCandidate {
  projectCode: string;
  projectName: string;
  pendingPrqs: string[];
  lastRunAt: string | null;
}

export function fetchResumeCandidates(): Promise<ResumeCandidate[]> {
  return api.get<ResumeCandidate[]>('/purchase-order/resume-candidates');
}
