/**
 * 구매발주 — 발주 패턴 v2(agents.settings.order_patterns) 프론트 미러.
 * 백엔드 단일 소스는 backend/app/services/agent_settings.py 의 동명 상수/검증기다
 * (menu_items 선례 — 정의·기본값은 코드, DB 에는 관리자 저장값만).
 *
 * v2(2026-08-21 사용자 피드백): 단위 번호(unitNo) 폐지 — **발주그룹**이 1급 개념이다.
 * 그룹 1개 = 발주단위 1건이고, 그룹이 소속 모듈(규격)·납기 규칙·구매사유·예외 규칙을 소유한다.
 * EFEM 과 PROCESS 는 같은 공장이라도 발주가 따로 묶인다. 예외는 v1 의 참고 텍스트가 아니라
 * 계획서의 거래처 그룹 납기·거래처·비고 기본값으로 **실반영**된다(개별 수정 가능).
 *
 * 기본 9그룹의 단일 소스는 `order-patterns.default.json` — FE 는 여기서 import 하고,
 * BE 는 자체 리터럴을 유지하며(배포 이미지에 src/ 없음) parity 테스트(json.load 재귀 비교)가
 * 드리프트를 감시한다.
 *
 * ⚠ 필드 방향(실측 2026-08-13): ERP 품명(ITEM_NM)이 '외주조립-F'·'제조2팀' 쪽이고,
 *   규격(ITEM_SPEC_DC)이 'Process-Frame Assy' 쪽이다. 모듈 식별 1순위는 spec(규격).
 */

import rawDefaults from './order-patterns.default.json';

/** 통합 납기예정일 기준 3종 — 계획서 상단에서 한 번 입력받아 그룹 규칙이 참조한다. */
export const BASE_DATE_KEYS = ['FRAME', '1공장', '3공장'] as const;
export type BaseDateKey = (typeof BASE_DATE_KEYS)[number];

/** 상단 기준일 입력 상태 — 미입력 키는 undefined. */
export type BaseDates = Partial<Record<BaseDateKey, string>>;

/** 구매사유 템플릿의 프로젝트 치환자 — 적용 시 프로젝트(코드 · 이름) 접두로 대체된다. */
export const PJT_PLACEHOLDER = 'PJT DESC';

/**
 * 예외 납기의 특수 기준 — 같은 발주단위 **가공품 그룹의 확정 납기**를 기준으로 삼는다
 * (BUFFER 규칙 '그 외 가공품 납품일 일주일전' 용). 그룹 자체 납기(due)에는 쓸 수 없다.
 */
export const PROCESSED_DUE_BASE = '가공품납기';

/** 그룹 납기 규칙 — base 기준일에서 offsetWeeks 주 전(영업일 환산은 subtractLeadDays 합성). */
export interface DueRule {
  base: BaseDateKey;
  offsetWeeks: number;
}

/** 예외 납기 규칙 — 3기준일 + '가공품납기'. */
export interface ExceptionDueRule {
  base: BaseDateKey | typeof PROCESSED_DUE_BASE;
  offsetWeeks: number;
}

/** 예외 대상 — 분류 일치 / 유효 거래처명 일치 / 분류 제외(그 분류만 빼고 전부). */
export type ExceptionScopeKind = 'vendorClass' | 'vendor' | 'exceptClass';

/**
 * 예외 규칙 — 매칭된 거래처 그룹의 기본값을 덮는다(개별 수정 vendorEdits 가 항상 우선).
 * due/vendor/note 중 최소 1개는 있어야 하며, 복수 예외는 배열 순서 필드별 first-wins.
 * 순환 금지 2규칙(검증기 강제): kind='vendor' 에 vendor 고정 금지,
 * (vendorClass,'가공품') 에 due.base='가공품납기' 금지.
 */
export interface PatternException {
  id: string;
  scope: { kind: ExceptionScopeKind; value: string };
  due?: ExceptionDueRule;
  /** 거래처 고정(이름) — 예: BUFFER 의 가공품 → 한국메카트로닉스. */
  vendor?: string;
  /** 비고 메시지 오버라이드 — finalNoteOf 의 [메시지] 부분(기본 '가공품 거래처(x) 직배송' 대체). */
  note?: string;
}

/** 그룹 소속 모듈 — spec(규격)이 매칭 1순위 키, name(품명)은 표시/2순위. */
export interface PatternModule {
  id: string;
  spec: string;
  name: string;
}

export interface PatternGroup {
  id: string;
  /** 발주묶음 — EFEM/PROCESS 등. 비교는 bundleKey() 정규화로 한다. */
  bundle: string;
  /** 그룹명 — FRAME·L Axis·1공장·3공장·BUFFER MODULE 등. */
  name: string;
  due: DueRule;
  /** 발주단위 구매사유 템플릿(PJT DESC 치환). */
  reason: string;
  modules: PatternModule[];
  exceptions: PatternException[];
}

/** settings 저장 shape — groups 배열 순서가 발주단위 생성 순서다. */
export interface OrderPatternsV2 {
  groups: PatternGroup[];
}

export const ORDER_PATTERNS_KEY = 'order_patterns';
export const MAX_PATTERN_GROUPS = 40;
export const MAX_GROUP_MODULES = 50;
export const MAX_GROUP_EXCEPTIONS = 20;
export const MAX_OFFSET_WEEKS = 52;

/** 발주묶음 비교 정규화 — 매칭 인덱스·에디터·장비명 판별이 전부 이 키 하나로 비교한다. */
export function bundleKey(bundle: string): string {
  return bundle.trim().toUpperCase();
}

let patternIdSeq = 0;

/** 에디터 신규 행 id — 그룹/모듈/예외 공용(접두로 구분). */
export function newPatternId(prefix: 'g' | 'm' | 'x'): string {
  patternIdSeq += 1;
  return `${prefix}${Date.now().toString(36)}${patternIdSeq}`;
}

// ── 관대 파서(읽기 경로) — 쓰기 경로의 엄격 검증은 백엔드 PATCH 가 담당 ────────────

function asTrimmed(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function isIntIn(value: unknown, min: number, max: number): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max;
}

function normalizeDue(raw: unknown, allowProcessed: boolean): DueRule | ExceptionDueRule | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const r = raw as Record<string, unknown>;
  const base = asTrimmed(r.base);
  const isBase = (BASE_DATE_KEYS as readonly string[]).includes(base);
  const ok = isBase || (allowProcessed && base === PROCESSED_DUE_BASE);
  if (!ok || !isIntIn(r.offsetWeeks, 0, MAX_OFFSET_WEEKS)) return null;
  return { base, offsetWeeks: r.offsetWeeks } as DueRule | ExceptionDueRule;
}

function normalizeModule(raw: unknown): PatternModule | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const r = raw as Record<string, unknown>;
  const spec = asTrimmed(r.spec);
  if (!spec) return null;
  return { id: asTrimmed(r.id) || newPatternId('m'), spec, name: asTrimmed(r.name) };
}

function normalizeException(raw: unknown): PatternException | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const r = raw as Record<string, unknown>;
  const scope = r.scope as Record<string, unknown> | undefined;
  const kind = asTrimmed(scope?.kind) as ExceptionScopeKind;
  const value = asTrimmed(scope?.value);
  if (!value || !['vendorClass', 'vendor', 'exceptClass'].includes(kind)) return null;
  const due = normalizeDue(r.due, true) as ExceptionDueRule | null;
  const vendor = asTrimmed(r.vendor);
  const note = typeof r.note === 'string' ? r.note.trim() : '';
  // 효과 없는 예외·순환 규칙 위반은 행 단위 드랍.
  if (!due && !vendor && !note) return null;
  if (kind === 'vendor' && vendor) return null;
  if (kind === 'vendorClass' && value === '가공품' && due?.base === PROCESSED_DUE_BASE) return null;
  return {
    id: asTrimmed(r.id) || newPatternId('x'),
    scope: { kind, value },
    ...(due ? { due } : null),
    ...(vendor ? { vendor } : null),
    ...(note ? { note } : null),
  };
}

function normalizeGroup(raw: unknown): PatternGroup | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const r = raw as Record<string, unknown>;
  const bundle = asTrimmed(r.bundle);
  const name = asTrimmed(r.name);
  const due = normalizeDue(r.due, false) as DueRule | null;
  if (!bundle || !name || !due) return null;
  const modules = Array.isArray(r.modules)
    ? r.modules
        .slice(0, MAX_GROUP_MODULES)
        .map(normalizeModule)
        .filter((m): m is PatternModule => m != null)
    : [];
  if (modules.length === 0) return null;
  const exceptions = Array.isArray(r.exceptions)
    ? r.exceptions
        .slice(0, MAX_GROUP_EXCEPTIONS)
        .map(normalizeException)
        .filter((x): x is PatternException => x != null)
    : [];
  return {
    id: asTrimmed(r.id) || newPatternId('g'),
    bundle,
    name,
    due,
    reason: typeof r.reason === 'string' ? r.reason.trim() : '',
    modules,
    exceptions,
  };
}

function normalizeGroups(raw: unknown): PatternGroup[] {
  if (typeof raw !== 'object' || raw === null) return [];
  const groups = (raw as Record<string, unknown>).groups;
  if (!Array.isArray(groups)) return [];
  const seen = new Set<string>();
  const out: PatternGroup[] = [];
  for (const item of groups.slice(0, MAX_PATTERN_GROUPS)) {
    const g = normalizeGroup(item);
    if (!g || seen.has(g.id)) continue;
    seen.add(g.id);
    out.push(g);
  }
  return out;
}

/**
 * 기본 9그룹 — order-patterns.default.json 이 단일 소스. JSON import 는 리터럴 유니온을
 * 잃으므로 관대 파서로 정규화해 타입을 복원한다(기본값이 파서를 통과하지 못하면 그 자체가
 * 버그 — parity 테스트와 아래 length 단언이 조기 검출).
 */
export const DEFAULT_ORDER_PATTERN_GROUPS: readonly PatternGroup[] = normalizeGroups(rawDefaults);

/**
 * settings 에서 발주 패턴을 읽는다 — 그룹 단위 관대(파손 그룹·모듈행·예외행만 드랍,
 * 유효 모듈 0 그룹 드랍). v1 배열 등 비정형이거나 남는 그룹이 없으면 기본 9그룹 폴백.
 */
export function orderPatternsFromSettings(
  settings: Record<string, unknown> | undefined | null,
): PatternGroup[] {
  const groups = normalizeGroups(settings?.[ORDER_PATTERNS_KEY]);
  return groups.length > 0 ? groups : [...DEFAULT_ORDER_PATTERN_GROUPS];
}
