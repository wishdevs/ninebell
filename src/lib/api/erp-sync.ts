/**
 * ERP 동기화 통합 관리 REST 클라이언트 — 관리자 전용(`RequireAdmin`).
 *
 * 카탈로그 4종(예산단위·프로젝트·거래처·ERP 조직)의 마지막 동기화·최근 실행 이력을 한 화면에서
 * 보고 즉시 동기화한다. 매일 자정(Asia/Seoul) 자동 동기화의 활성 여부도 여기서 노출된다.
 *
 * 백엔드 계약(고정, 2026-09-02):
 *   GET  /admin/erp-sync                         → ErpSyncOverview
 *   POST /admin/erp-sync/{kind}                   → 202 {started:true} | 409/400(한글 detail)
 *   POST /admin/erp-sync/all                      → 202 {started:true, kinds:[…]} | 409
 *   GET  /admin/erp-sync/runs?kind=&limit=20      → {items: ErpSyncRunRow[]} 최신순
 */

import { api } from './client';
import type { OrgApplySummary, OrgReassign } from './me-codes';

/** 동기화 대상 4종 — 백엔드 `_VALID_KINDS` 와 동일. 응답 items 도 이 순서다. */
export type ErpSyncKind = 'budget_unit' | 'project' | 'partner' | 'org_unit';

export const ERP_SYNC_KINDS: readonly ErpSyncKind[] = [
  'budget_unit',
  'project',
  'partner',
  'org_unit',
];

export type ErpSyncTrigger = 'manual' | 'scheduled';
export type ErpSyncRunStatus = 'running' | 'succeeded' | 'failed' | 'skipped';

/** 실행 1건(erp_sync_runs). org_unit 만 applied·reassigned 가 채워진다. */
export interface ErpSyncRun {
  id: number;
  trigger: ErpSyncTrigger;
  status: ErpSyncRunStatus;
  startedAt: string;
  finishedAt: string | null;
  count: number | null;
  error: string | null;
  applied: OrgApplySummary | null;
  /** org_unit — department 기준 재배치된 사용자. 계약은 수(count)지만 실측(2026-09-02) 백엔드가
   * sync-status 와 같은 목록을 그대로 내려주므로 둘 다 받는다 — 화면은 {@link reassignedCount} 로 센다. */
  reassigned: number | OrgReassign[] | null;
  /** manual 이면 실행자 표시명. */
  actorName: string | null;
}

/** reassigned 가 수든 목록이든 재배치 인원수로 정규화한다. */
export function reassignedCount(run: Pick<ErpSyncRun, 'reassigned'>): number {
  if (run.reassigned == null) return 0;
  return Array.isArray(run.reassigned) ? run.reassigned.length : run.reassigned;
}

/** 이력 목록 행 — 실행 1건 + kind. */
export interface ErpSyncRunRow extends ErpSyncRun {
  kind: ErpSyncKind;
}

export interface ErpSyncItem {
  kind: ErpSyncKind;
  label: string;
  running: boolean;
  /** erp_code_catalog 행수(kind). */
  count: number;
  /** 성공 실행 max(finished_at), 없으면 카탈로그 max(synced_at) 폴백. */
  lastSuccessAt: string | null;
  lastRun: ErpSyncRun | null;
}

export interface ErpSyncSchedule {
  enabled: boolean;
  /** "HH:MM". */
  at: string;
  tz: string;
  kinds: ErpSyncKind[];
  /** ERP_SYNC_USERID/PASSWORD 존재 여부(값은 노출되지 않는다). */
  serviceAccountConfigured: boolean;
  /** enabled && serviceAccountConfigured — 스케줄러 루프가 실제로 도는가. */
  active: boolean;
  /** active 일 때만. */
  nextRunAt: string | null;
}

/** 이 관리자가 '지금 동기화'를 누르면 쓰이는 자격증명 — 세션 ERP 계정 / 서비스 계정 / 없음. */
export type ErpSyncCredentialSource = 'session' | 'service' | null;

export interface ErpSyncOverview {
  schedule: ErpSyncSchedule;
  credentialSource: ErpSyncCredentialSource;
  items: ErpSyncItem[];
}

/** `GET /admin/erp-sync` — 스케줄·자격증명·4종 현황. */
export function fetchErpSyncOverview(): Promise<ErpSyncOverview> {
  return api.get<ErpSyncOverview>('/admin/erp-sync');
}

/**
 * `POST /admin/erp-sync/{kind}` — 단건 즉시 동기화. 진행 중이면 409, 자격증명이 없으면
 * 409/400(한글 detail) — 호출부가 errorMessage 로 토스트한다.
 */
export function startErpSync(kind: ErpSyncKind): Promise<{ started: boolean }> {
  return api.post<{ started: boolean }>(`/admin/erp-sync/${kind}`, {});
}

/** `POST /admin/erp-sync/all` — 4종을 한 백그라운드 태스크에서 순차 실행. 진행 중이면 409. */
export function startErpSyncAll(): Promise<{ started: boolean; kinds: ErpSyncKind[] }> {
  return api.post<{ started: boolean; kinds: ErpSyncKind[] }>('/admin/erp-sync/all', {});
}

/** `GET /admin/erp-sync/runs` — 최근 실행 이력(최신순). */
export async function fetchErpSyncRuns(kind?: ErpSyncKind, limit = 20): Promise<ErpSyncRunRow[]> {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (kind) qs.set('kind', kind);
  const res = await api.get<{ items?: ErpSyncRunRow[] }>(`/admin/erp-sync/runs?${qs.toString()}`);
  return res.items ?? [];
}
