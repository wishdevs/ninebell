/**
 * 변경사항(릴리스 노트) API 클라이언트.
 *
 * 백엔드 계약(고정):
 *   GET    /changelog?q&status&hasMajorFix&limit&offset → {items, total, limit, offset} (세션)
 *   GET    /changelog/{id}                   → ChangelogEntry (세션)
 *   POST   /changelog {ChangelogInput}       → 201 ChangelogEntry (관리자, 아니면 403)
 *   PATCH  /changelog/{id} {ChangelogInput}  → ChangelogEntry (관리자, 전체 교체)
 *   DELETE /changelog/{id}                   → 204 (관리자)
 *
 * 일반 사용자에게는 백엔드가 status='released' 만 반환한다(draft 는 존재 자체를 숨김).
 * version 중복 시 409 — 화면은 errorMessage() 로 서버 문구를 그대로 노출한다.
 */

import { api } from '@/lib/api/client';

export type ChangelogStatus = 'draft' | 'released';

export interface ChangelogEntry {
  id: string;
  /** 릴리스 식별자(중복 불가). 예: 'v1.4.0'. */
  version: string;
  title: string;
  /** 마크다운 본문. */
  bodyMd: string;
  status: ChangelogStatus;
  /**
   * 잘못 저장·미저장·실행 불가·개인정보 등 '반드시 확인해야 할' 수정 포함 여부.
   * 목록 배지·필터가 본문을 파싱하지 않도록 구조화한 유일한 분류 필드 —
   * 나머지 분류(추가/개선/수정/변경/보안)는 본문 마크다운 섹션으로 표현한다.
   */
  hasMajorFix: boolean;
  /**
   * 릴리스 날짜 'yyyy-mm-dd' — 목록 정렬·표기 기준.
   * '시각'이 아니라 '달력 날짜'라 오프셋이 붙지 않는다(시간대에 따라 하루 밀리는 것 방지).
   */
  releasedAt: string;
  createdAt: string;
  updatedAt: string;
}

export interface ChangelogInput {
  version: string;
  title: string;
  bodyMd: string;
  status: ChangelogStatus;
  hasMajorFix: boolean;
  /** 'yyyy-mm-dd'. 생략 시 서버가 KST 기준 오늘로 채운다. */
  releasedAt?: string;
}

export interface ChangelogQuery {
  limit: number;
  offset: number;
  q?: string;
  /** 'all' 이면 미지정(관리자만 의미 있음). */
  status?: ChangelogStatus | 'all';
  /** 생략(undefined)이면 필터 없음. true = 주요 수정 포함 릴리스만. */
  hasMajorFix?: boolean;
}

export async function fetchChangelog(
  query: ChangelogQuery,
): Promise<{ items: ChangelogEntry[]; total: number }> {
  const params = new URLSearchParams({
    limit: String(query.limit),
    offset: String(query.offset),
  });
  if (query.q?.trim()) params.set('q', query.q.trim());
  if (query.status && query.status !== 'all') params.set('status', query.status);
  if (query.hasMajorFix !== undefined) params.set('hasMajorFix', String(query.hasMajorFix));
  const res = await api.get<{ items?: ChangelogEntry[]; total: number }>(`/changelog?${params}`);
  return { items: res.items ?? [], total: res.total };
}

export function createChangelogEntry(input: ChangelogInput): Promise<ChangelogEntry> {
  return api.post<ChangelogEntry>('/changelog', { ...input });
}

export function updateChangelogEntry(id: string, input: ChangelogInput): Promise<ChangelogEntry> {
  return api.patch<ChangelogEntry>(`/changelog/${encodeURIComponent(id)}`, { ...input });
}

export function deleteChangelogEntry(id: string): Promise<void> {
  return api.delete<void>(`/changelog/${encodeURIComponent(id)}`);
}
