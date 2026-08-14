/**
 * 런(run) REST 클라이언트 — SSE 라이브 스트림(useLiveRun)과 별개로, 종료(cancel)·
 * 실행 이력·템플릿을 다루는 백엔드 엔드포인트 래퍼.
 *
 * 인증은 앱 전역과 동일하게 httpOnly 세션 쿠키로 처리하므로 모든 호출에
 * `credentials:'include'`가 붙는다(공용 {@link api} 래퍼가 처리). 예외는 즉시 종료용
 * {@link cancelRun} 하나 — 언마운트/네비게이션 중에도 확실히 전송돼야 해서 공용 래퍼가
 * 아닌 keepalive fetch 를 직접 쓴다.
 *
 * 백엔드 계약(p5-backend, camelCase):
 *   POST   /runs/cancel            {runId}                      → 세션 즉시 close(멱등)
 *   GET    /runs?agentId=&status=&limit=&offset=                 → RunSummary[]
 *   GET    /runs/{id}                                           → RunDetail
 *   POST   /runs/templates         {agentId, name, selections}  → RunTemplate
 *   GET    /runs/templates?agentId                              → RunTemplate[]
 *   DELETE /runs/templates/{id}                                 → 204
 */

import { API_BASE, api } from '@/lib/api/client';
import type { LiveLogLevel } from './types';

// ── 도메인 타입 ──────────────────────────────────────────────────────

/** 런 상태. cancelled(즉시 종료)를 포함하며 미지의 값에도 견디도록 열어 둔다. */
export type RunStatus =
  'running' | 'waiting_input' | 'succeeded' | 'failed' | 'cancelled' | (string & {});

/** 이력 목록 한 줄(요약). */
export interface RunSummary {
  id: string;
  agentId: string;
  status: RunStatus;
  startedAt: string | null;
  finishedAt: string | null;
  resultSummary: string | null;
  /** 실패로 끝났을 때 어느 단계에서 멈췄는지(로깅 목록·상세용). 성공/미상 시 없음. */
  failedStep?: string | null;
  /** 실행자 표시 — 관리자(logs:read) 뷰에서 타인 실행을 구분한다. 백엔드가 주면 표시. */
  userDisplayName?: string | null;
  omnisolUserid?: string | null;
  userId?: string | null;
}

/** 정규화된 로그 한 줄(백엔드 저장 형태가 문자열/객체 어느 쪽이든 이 형태로 좁힌다). */
export interface RunLogEntry {
  message: string;
  level: LiveLogLevel;
  /** 저장 시각(epoch ms) — 백엔드가 additive 로 부여. 과거 런엔 없으므로 방어 렌더 필수. */
  ts?: number;
  /** step 프레임의 구조 필드(단계명). 일반 log 프레임엔 없다. */
  step?: string;
  /** step 프레임의 구조 필드(running|done|failed). 일반 log 프레임엔 없다. */
  status?: string;
}

/**
 * 대화형 실행이 누적하는 선택 하나 — 프론트는 내부를 들여다보지 않고 그대로 저장/재생만
 * 하므로 불투명 레코드로 둔다(백엔드 chat_form 이 정의).
 */
export type ChatSelection = Record<string, unknown>;

/**
 * 실행이 받은 입력 원천 — 대화형 실행이 누적한 선택/대화. 백엔드가 selections 를 최상위로
 * 주거나 `inputs` 컨테이너 안에 담을 수 있어 둘 다 수용한다(형태 불확정 → 불투명).
 */
export interface RunInputs {
  selections?: ChatSelection[];
  /** 사용자가 입력한 대화(백엔드는 `messages`(문자열 배열)로 준다. chat 도 수용). */
  messages?: unknown;
  chat?: unknown;
  [key: string]: unknown;
}

/**
 * 실행 결과 — 워크플로우에 따라 문자열이거나 `{summary, ...}` 객체다(demo-echo=문자열,
 * expense-card=객체). 표시에는 {@link resultText} 로 문자열을 뽑아 쓴다(직접 렌더 금지 —
 * 객체를 React child 로 렌더하면 크래시).
 */
export type RunResult = string | { summary?: string; [key: string]: unknown } | null;

/** 런 상세 — 요약 + 결과 본문/로그/입력(선택·대화). */
export interface RunDetail extends RunSummary {
  result: RunResult;
  logs: readonly RunLogEntry[];
  /** 대화형 실행이 누적한 선택(템플릿 저장 원천). 최상위로 노출될 때. */
  selections?: ChatSelection[];
  /** 입력 원천 컨테이너(로깅 상세: "무엇을 입력했는지"). selections 를 여기 담을 수도 있다. */
  inputs?: RunInputs;
}

/**
 * 상세 결과에서 표시용 문자열을 뽑는다 — 문자열이면 그대로, `{summary}` 객체면 summary,
 * 그 외/빈값이면 resultSummary 로 폴백. 폴리모픽 result 를 안전하게 렌더하기 위한 관문.
 */
export function resultText(detail: RunDetail): string | null {
  const r = detail.result;
  if (typeof r === 'string') return r.trim() ? r : (detail.resultSummary ?? null);
  if (r && typeof r === 'object' && typeof r.summary === 'string') return r.summary;
  return detail.resultSummary ?? null;
}

/**
 * 상세에서 템플릿 저장/표시에 쓸 selections 를 뽑는다 — 최상위 `selections` 우선,
 * 없으면 `inputs.selections`. 백엔드가 어느 쪽에 담든 동작하도록 한다.
 */
export function extractSelections(detail: RunDetail): ChatSelection[] {
  if (Array.isArray(detail.selections)) return detail.selections;
  if (Array.isArray(detail.inputs?.selections)) return detail.inputs.selections;
  return [];
}

/** 저장된 재생 템플릿. */
export interface RunTemplate {
  id: string;
  name: string;
  createdAt: string;
}

// ── 즉시 종료(cancel) ────────────────────────────────────────────────

/**
 * 세션 즉시 종료 요청 — 브라우저 큐 슬롯을 곧바로 반납한다("화면 벗어나면 큐 반납").
 *
 * 언마운트/네비게이션(그리고 pagehide) 도중에도 전송이 살아남아야 하므로 `keepalive`
 * fetch 를 쓴다. sendBeacon 은 JSON+credentials 교차출처에서 프리플라이트를 못 해
 * 조용히 유실될 수 있어 피한다. 응답은 기다리지 않는다(best-effort). 세션이 이미 없으면
 * 백엔드가 멱등(200)으로 처리한다.
 */
export function cancelRun(runId: string): void {
  if (!runId) return;
  try {
    void fetch(`${API_BASE}/runs/cancel`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      credentials: 'include',
      keepalive: true,
      body: JSON.stringify({ runId }),
    });
  } catch {
    // best-effort — 실패해도 리퍼(grace 타임아웃)가 결국 세션을 정리한다.
  }
}

// ── 실행 이력 ────────────────────────────────────────────────────────

export interface RunsQuery {
  /** 지정하면 해당 워크플로우로 스코프(에이전트 상세). 생략하면 전체(로깅 페이지). */
  agentId?: string;
  /** 지정하면 해당 실행 상태로 스코프(로깅 페이지 상태 필터). */
  status?: string;
  limit?: number;
  offset?: number;
}

/** 실행 목록 페이지 — 행 + 스코프 전체 건수(번호형 페이지네이션용). */
export interface RunsPage {
  runs: RunSummary[];
  total: number;
}

/**
 * `GET /runs` — 실행 목록(최신순) + 전체 건수. `agentId` 를 주면 그 워크플로우로 스코프한다.
 * 소유자 스코프는 백엔드가 처리(관리자=전체, 그 외=본인 것).
 *
 * 백엔드는 `{"runs": RunSummary[], "total": number}` envelope 로 반환한다. 목록 응답 키
 * 이원화에 견디도록 `items ?? runs` 관용 리더로 읽는다(반환 형태 {runs,total} 은 유지 —
 * 소비처 파급 없음).
 */
export async function fetchRuns(query: RunsQuery = {}): Promise<RunsPage> {
  const qs = new URLSearchParams();
  if (query.agentId) qs.set('agentId', query.agentId);
  if (query.status) qs.set('status', query.status);
  if (query.limit != null) qs.set('limit', String(query.limit));
  if (query.offset != null) qs.set('offset', String(query.offset));
  const suffix = qs.toString();
  const res = await api.get<{ items?: RunSummary[]; runs?: RunSummary[]; total?: number }>(
    suffix ? `/runs?${suffix}` : '/runs',
  );
  return { runs: res.items ?? res.runs ?? [], total: res.total ?? 0 };
}

/** 백엔드 저장 로그 한 줄을 {@link RunLogEntry} 로 정규화(문자열/객체 모두 수용). */
function normalizeLog(raw: unknown): RunLogEntry {
  if (typeof raw === 'string') return { message: raw, level: 'info' };
  if (raw && typeof raw === 'object') {
    const o = raw as Record<string, unknown>;
    const message =
      typeof o.message === 'string'
        ? o.message
        : typeof o.log === 'string'
          ? o.log
          : JSON.stringify(o);
    const level = typeof o.level === 'string' ? (o.level as LiveLogLevel) : 'info';
    const entry: RunLogEntry = { message, level };
    // 구조 필드는 있으면 보존(additive) — ts(epoch ms)·step·status. 과거 런엔 없다.
    if (typeof o.ts === 'number' && Number.isFinite(o.ts)) entry.ts = o.ts;
    if (typeof o.step === 'string') entry.step = o.step;
    if (typeof o.status === 'string') entry.status = o.status;
    return entry;
  }
  return { message: String(raw), level: 'info' };
}

/** 백엔드 원시 상세(로그 형태 불확정) → 정규화 전 형태. */
type RawRunDetail = Omit<RunDetail, 'logs'> & { logs?: unknown };

/** `GET /runs/{id}` — 상세(결과·로그·선택). 로그는 정규화한다. */
export async function fetchRunDetail(id: string): Promise<RunDetail> {
  const raw = await api.get<RawRunDetail>(`/runs/${encodeURIComponent(id)}`);
  const logs = Array.isArray(raw.logs) ? raw.logs.map(normalizeLog) : [];
  return { ...raw, logs };
}

// ── 템플릿 ───────────────────────────────────────────────────────────

/**
 * `GET /runs/templates?agentId` — 저장된 템플릿 목록. 백엔드는 `{"templates": [...]}`
 * envelope 로 감싸 반환하므로 언랩한다(배열 그대로 와도 견딤).
 */
export async function fetchTemplates(agentId: string): Promise<RunTemplate[]> {
  const qs = new URLSearchParams({ agentId });
  const res = await api.get<{ templates?: RunTemplate[] } | RunTemplate[]>(
    `/runs/templates?${qs.toString()}`,
  );
  return Array.isArray(res) ? res : (res?.templates ?? []);
}

export interface SaveTemplateInput {
  agentId: string;
  name: string;
  selections: ChatSelection[];
}

/** `POST /runs/templates` — 선택 묶음을 이름으로 저장. */
export function saveTemplate(input: SaveTemplateInput): Promise<RunTemplate> {
  return api.post<RunTemplate>('/runs/templates', {
    agentId: input.agentId,
    name: input.name,
    selections: input.selections,
  });
}

/** `DELETE /runs/templates/{id}` — 템플릿 삭제. */
export function deleteTemplate(id: string): Promise<void> {
  return api.delete<void>(`/runs/templates/${encodeURIComponent(id)}`);
}
