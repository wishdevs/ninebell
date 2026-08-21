/**
 * 구매발주 계획서 — 모델(타입·파생 헬퍼). BOM 을 인자로 받는다 — 정적 전역 의존 없음
 * (구 데모의 정적 픽스처 주입 구조에서 온 설계, 데모는 2026-08-21 제거).
 *
 * BOM shape 는 백/프론트 공유 계약(lib/live/types 의 PlannerBom)이다. 호출부는
 * createPlanBom() 으로 파생 컨텍스트(모듈 평탄화·맵)를 만들어 헬퍼에 넘긴다 —
 * LivePlannerCard 가 hitl.plannerBom 을 주입한다.
 *
 * 상태의 단일 소스는 units 배열이다 — 모듈→발주단위 매핑·거래처 그룹·합계는 전부 여기서
 * 파생한다(중복 배정은 파생 맵으로 강제). 파생 헬퍼는 순수 함수다 — 단 newOrderUnit 은
 * 모듈 레벨 시퀀스(unitIdSeq)를 증가시키는 예외로, 이벤트 핸들러에서만 호출해야 한다.
 */

import type {
  PlannerBom,
  PlannerBomMachine,
  PlannerBomModule,
  PlannerBomPart,
  PlanSubmit,
} from '@/lib/live/types';
import {
  PROCESSED_DUE_BASE,
  type BaseDates,
  type DueRule,
  type ExceptionDueRule,
  type PatternException,
} from '@/lib/purchase/order-patterns';
import { vendorCategoryOf } from './catalog';
import { subtractLeadDays } from './dates';

// ── BOM 타입(와이어 계약 별칭 — 단일 정의는 lib/live/types) ─────────────────

export type BomPart = PlannerBomPart;
export type BomModule = PlannerBomModule;
export type BomMachine = PlannerBomMachine;
export type PurchaseOrderBom = PlannerBom;

/** BOM 1건에서 파생한 계획서 컨텍스트 — 헬퍼·컴포넌트가 공유하는 조회 구조. */
export interface PlanBom {
  project: { code: string; name: string; wbs: string };
  machines: readonly BomMachine[];
  /** 3레벨 모듈(SET, 발주단위 선택 단위) — 전 장비 평탄화, BOM 순서 유지. */
  modules: readonly BomModule[];
  moduleMap: ReadonlyMap<string, BomModule>;
}

export function createPlanBom(raw: PurchaseOrderBom): PlanBom {
  const modules = raw.machines.flatMap((m) => m.modules);
  return {
    project: raw.project,
    machines: raw.machines,
    modules,
    moduleMap: new Map(modules.map((m) => [m.itemCode, m])),
  };
}

/**
 * 모듈 표기 = 품목명 + spec 병기 — 품목명이 '제조2팀'처럼 중복되는 행이 있어
 * spec(Assy 구분자)이 실제 식별자다.
 */
export function moduleLabel(m: BomModule): string {
  return `${m.name} · ${m.spec}`;
}

// ── 거래처 분류 ──────────────────────────────────────────────────────────────

/** 가공품 클래스 — 납기 파생(발주 납기 추종)·비고 기본 문구의 기준 그룹. */
export const PROCESSED_CLASS = '가공품';

/**
 * 의사 거래처 — 구매발주일괄입력 단계에서 실거래처로 치환해야 하는 품목거래처명.
 * 삽입 순서(가공품 → 판금품)가 거래처 그룹 표의 표시 우선순위다.
 */
export const PSEUDO_VENDOR_CLASSES: ReadonlySet<string> = new Set([PROCESSED_CLASS, '판금품']);

export function isPseudoVendor(vendorClass: string): boolean {
  return PSEUDO_VENDOR_CLASSES.has(vendorClass);
}

/**
 * 통합 거래처 지정 — 계획서 상단에서 분류마다 한 번 고른 거래처(vendorClass → 거래처).
 * 발주단위·거래처그룹 단위 오버라이드(vendorEdits)가 없을 때 접히는 기본값이다.
 * 키 집합이 곧 **교체 가능한 분류**다(catalog.ts VENDOR_CATEGORIES 가 정의) — 값이
 * undefined 여도 키는 남으므로, 통합 지정을 지우면 미지정으로 판정된다.
 */
export type UnifiedVendors = Readonly<Record<string, { code: string; name: string } | undefined>>;

/**
 * 교체 가능한 거래처 분류인가 — 통합 지정 대상(가공품·판금품·주식회사 오텍)이면 그룹 행에
 * 콤보박스를 그리고, 확정 게이트가 유효 거래처를 요구하며, 페이로드에 유효 거래처명이 나간다.
 * 그 외 실거래처 분류는 종전대로 평문 표시 + 분류명 echo 다.
 */
export function isSwappableVendorClass(vendorClass: string, unified: UnifiedVendors): boolean {
  return vendorClass in unified;
}

/** 그룹의 유효 거래처 = 그룹 오버라이드 ?? 통합 지정. 둘 다 없으면 undefined(미지정). */
export function effectiveVendorOf(
  unit: OrderUnit,
  vendorClass: string,
  unified: UnifiedVendors,
): { code: string; name: string } | undefined {
  return unit.vendorEdits[vendorClass]?.vendor ?? unified[vendorClass];
}

// ── 모듈 단위 파생 ───────────────────────────────────────────────────────────

export function moduleAmount(m: BomModule): number {
  return m.parts.reduce((s, p) => s + p.amount, 0);
}

export interface VendorMix {
  /** 의사 거래처별 부품 수 — 픽스처 등장 순서 유지(가공품·판금품). */
  pseudoCounts: readonly { vendorClass: string; count: number }[];
  /** 실거래처 종 수(부품 수가 아니라 거래처 수). */
  realKinds: number;
}

/** 거래처 구성 미니 칩 재료 — 가공품 n · 판금품 n · 실거래처 n종. */
export function vendorMixOf(m: BomModule): VendorMix {
  const counts = new Map<string, number>();
  const reals = new Set<string>();
  for (const p of m.parts) {
    if (isPseudoVendor(p.vendorClass)) {
      counts.set(p.vendorClass, (counts.get(p.vendorClass) ?? 0) + 1);
    } else {
      reals.add(p.vendorClass);
    }
  }
  return {
    pseudoCounts: [...PSEUDO_VENDOR_CLASSES]
      .filter((v) => counts.has(v))
      .map((v) => ({ vendorClass: v, count: counts.get(v)! })),
    realKinds: reals.size,
  };
}

// ── 발주단위(units — 상태의 단일 소스) ───────────────────────────────────────

/**
 * 거래처 그룹 편집값 — **오버라이드만** 저장한다(기본값 복제 저장 금지).
 * 미지정 시 렌더·페이로드에서 파생 기본값으로 접는다 — 거래처 = effectiveVendorOf,
 * 납기 = vendorDueOf, 비고 = defaultNoteOf.
 */
export interface VendorEdit {
  /** 의사 거래처에 지정한 실거래처. 실거래처 행에는 쓰지 않는다. */
  vendor?: { code: string; name: string };
  /** 그룹별 납기 오버라이드('yyyy-mm-dd'). 없으면 vendorDueOf 파생값. */
  dueDate?: string;
  /** 비고 오버라이드. 없으면 defaultNoteOf 기본 문구('' 저장 = 지움도 오버라이드). */
  note?: string;
}

/**
 * 발주단위가 물고 있는 패턴 그룹 규칙 **스냅샷**(그룹 id 참조가 아니라 값 복사).
 * 파생 함수가 (unit, baseDates, unified) 만으로 닫히고, 수동 생성 단위(스냅샷 없음)는
 * 내장 기본 경로에 정확히 남는다.
 */
export interface UnitPatternRule {
  groupId: string;
  groupName: string;
  bundle: string;
  /** 단위 납기 규칙 — 통합 기준일이 바뀔 때 dueDate 를 다시 시드하는 근거. */
  due: DueRule;
  /** 거래처 그룹 예외 — 납기·거래처·비고 기본값을 덮는다(vendorDefaultsOf 가 해석). */
  exceptions: readonly PatternException[];
}

export interface OrderUnit {
  id: string;
  /** '발주 N' 표기 시퀀스. */
  seq: number;
  /** 배정된 모듈 itemCode — BOM 순서 유지. */
  moduleCodes: readonly string[];
  purchaseReason: string;
  /** 납기예정일 — 빈 값이면 미입력(확정 차단). 기본값을 오늘로 채우지 않는다(hydration). */
  dueDate: string;
  /** vendorClass → 오버라이드. 모듈 제거로 그룹이 사라지면 파생에서 자연히 무시된다. */
  vendorEdits: Readonly<Record<string, VendorEdit>>;
  /** 패턴 그룹 규칙 스냅샷 — 수동으로 묶은 발주단위에는 없다. */
  patternRule?: UnitPatternRule;
  /** 납기를 사람이 직접 고쳤는가 — true 면 통합 기준일을 다시 바꿔도 덮지 않는다. */
  dueTouched?: boolean;
}

let unitIdSeq = 0;
export function newOrderUnit(
  seq: number,
  moduleCodes: readonly string[],
  purchaseReason = '',
): OrderUnit {
  unitIdSeq += 1;
  return {
    id: `pu${unitIdSeq}`,
    seq,
    moduleCodes,
    purchaseReason,
    dueDate: '',
    vendorEdits: {},
  };
}

/** 다음 '발주 N' — 현존 최대 +1(삭제로 빈 번호는 재사용될 수 있다 — 데모 허용). */
export function nextUnitSeq(units: readonly OrderUnit[]): number {
  return units.reduce((mx, u) => Math.max(mx, u.seq), 0) + 1;
}

export function modulesOf(bom: PlanBom, unit: OrderUnit): BomModule[] {
  return unit.moduleCodes.map((c) => bom.moduleMap.get(c)).filter((m): m is BomModule => m != null);
}

/** 모듈 → 배정된 발주 seq. 중복 배정 불가를 이 파생 맵으로 강제한다(풀 체크박스 비활성). */
export function assignedSeqMap(units: readonly OrderUnit[]): ReadonlyMap<string, number> {
  const map = new Map<string, number>();
  for (const u of units) for (const c of u.moduleCodes) map.set(c, u.seq);
  return map;
}

/** 외주조립 모듈 접두사 — 구매사유 기본 문구의 부품명 추출 기준. */
const OUTSOURCED_PREFIX = '외주조립-';

/**
 * 구매사유 기본값 — 발주단위의 **외주조립 모듈명만**(예: 'BUFFER·ELECTRIC PANNEL'),
 * 여러 개면 '·' 로 잇는다. 외주조립 모듈이 없으면 빈 값(직접 입력). 발주단위 생성 시 1회
 * 채우는 초기값이라 이후 모듈을 빼도 문구는 남는다 — 사용자가 자유 수정 가능.
 *
 * ⚠ 여기엔 프로젝트명이 들어가지 않는다 — 입력란은 **모듈명만** 받고, 프로젝트와의 결합은
 *   최종 계획서(finalPurchaseReasonOf → buildPlanPayload)에서 한다(사용자 확정 2026-08-14).
 */
export function defaultPurchaseReasonOf(bom: PlanBom, moduleCodes: readonly string[]): string {
  return moduleCodes
    .map((c) => bom.moduleMap.get(c)?.name ?? '')
    .filter((n) => n.startsWith(OUTSOURCED_PREFIX))
    .map((n) => n.slice(OUTSOURCED_PREFIX.length))
    .join('·');
}

/**
 * 구매사유·비고에 붙는 프로젝트 접두 — **프로젝트명만**(코드 제외, 사용자 확정 2026-08-21
 * — 'PJT DESC'는 프로젝트명 치환자다). 이름이 비면 코드로 폴백.
 */
function projectPrefixOf(project: { code: string; name: string }): string {
  return project.name.trim() || project.code.trim();
}

/**
 * 최종 구매사유 = **[프로젝트명] + [입력한 모듈명]**(2026-08-14 규칙, 2026-08-21 코드 제외).
 * 입력란은 모듈명만 받고, ERP 로 나가는 완성 문자열은 여기서 만든다 — 프로젝트를 바꾸면
 * 접두가 자동으로 따라온다. 최종 계획서 표기와 제출 페이로드가 이 함수를 공유한다.
 */
export function finalPurchaseReasonOf(
  project: { code: string; name: string },
  unit: OrderUnit,
): string {
  return [projectPrefixOf(project), unit.purchaseReason.trim()].filter(Boolean).join(' ');
}

/** 카드 헤더 모듈 요약 — '외주조립-BUFFER 외 2'. */
export function unitModuleSummary(bom: PlanBom, unit: OrderUnit): string {
  const mods = modulesOf(bom, unit);
  if (mods.length === 0) return '';
  const first = mods[0].name;
  return mods.length === 1 ? first : `${first} 외 ${mods.length - 1}`;
}

// ── 거래처 그룹(렌더 시 파생 — 저장하지 않는다) ─────────────────────────────

export interface VendorGroup {
  vendorClass: string;
  isPseudo: boolean;
  parts: readonly BomPart[];
  amount: number;
}

/** 의사 거래처 정렬 우선순위 — PSEUDO_VENDOR_CLASSES 삽입 순서(가공품 → 판금품). */
const PSEUDO_ORDER: readonly string[] = [...PSEUDO_VENDOR_CLASSES];

/** 모듈들의 부품을 vendorClass 로 그룹핑 — 가공품 → 판금품 → 실거래처(금액 내림차순). */
export function vendorGroupsOf(modules: readonly BomModule[]): VendorGroup[] {
  const byClass = new Map<string, BomPart[]>();
  for (const m of modules) {
    for (const p of m.parts) {
      const list = byClass.get(p.vendorClass);
      if (list) list.push(p);
      else byClass.set(p.vendorClass, [p]);
    }
  }
  const groups = [...byClass.entries()].map(([vendorClass, parts]) => ({
    vendorClass,
    isPseudo: isPseudoVendor(vendorClass),
    parts,
    amount: parts.reduce((s, p) => s + p.amount, 0),
  }));
  return groups.sort((a, b) => {
    if (a.isPseudo !== b.isPseudo) return a.isPseudo ? -1 : 1;
    // 가공품이 항상 첫 행 — 납기·비고 기본값 파생의 기준 그룹이라 순서를 고정한다.
    if (a.isPseudo)
      return PSEUDO_ORDER.indexOf(a.vendorClass) - PSEUDO_ORDER.indexOf(b.vendorClass);
    return b.amount - a.amount;
  });
}

// ── 그룹 파생 기본값(납기·비고) — 오버라이드 없을 때 렌더·페이로드가 접는 값 ─

/**
 * 그룹 기본 납기 — 가공품은 발주단위 납기(unitDue) 그대로, 그 외(판금품·실거래처)는
 * 1주일 전 영업일(공휴일 보정 — subtractLeadDays 참조). unitDue 미입력이면 빈 값.
 */
export function vendorDueOf(unitDue: string, vendorClass: string): string {
  if (!unitDue) return '';
  return vendorClass === PROCESSED_CLASS ? unitDue : subtractLeadDays(unitDue);
}

/**
 * 패턴 납기 규칙 → 날짜('yyyy-mm-dd'). base 가 3기준일이면 상단 입력값, '가공품납기'면 인자
 * procDue(같은 발주단위 가공품 그룹의 확정 납기)를 출발점으로 삼고, offsetWeeks 회만큼
 * subtractLeadDays(1주 = 영업일 5일 — 공휴일·주말을 건너뛰며 보존)를 합성한다.
 *
 * 출발점이 비어 있으면(기준일 미입력·단위에 가공품 그룹 없음) 빈 문자열 — 호출부가 다음
 * 우선순위(내장 기본값)로 폴백한다.
 */
export function resolveDueRule(
  rule: DueRule | ExceptionDueRule,
  baseDates: BaseDates,
  procDue?: string,
): string {
  let date = rule.base === PROCESSED_DUE_BASE ? (procDue ?? '') : (baseDates[rule.base] ?? '');
  for (let i = rule.offsetWeeks; i > 0 && date; i -= 1) date = subtractLeadDays(date);
  return date;
}

/**
 * 그룹 기본 **비고 메시지** — '가공품 거래처(해룡엔지니어링) 직배송'. 괄호 안은 그 발주단위 가공품
 * 그룹의 유효 거래처명 동적 표기. 사유: 가공품 외 거래처가 제작품을 가공품 제작처로
 * 직배송하고, 거기서 조립해 모듈 단위로 받는다.
 *
 * 빈 값이 되는 경우 둘 — ① 가공품 그룹 자신, ② **발주단위에 가공품이 없을 때**(직배송할
 * 대상이 없으므로 아무것도 쓰지 않는다).
 *
 * ⚠ 여기엔 구매사유가 들어가지 않는다 — 입력란은 **메시지만** 받고, 구매사유와의 결합은
 *   최종 계획서(finalNoteOf → buildPlanPayload)에서 한다(사용자 확정 2026-08-14).
 */
export function defaultNoteOf(
  unit: OrderUnit,
  vendorClass: string,
  groups: readonly VendorGroup[],
  unified: UnifiedVendors,
  /** 가공품 그룹의 유효 거래처명 — 예외로 고정된 거래처(BUFFER 의 한국메카트로닉스 등)까지
   *  반영하려면 리졸버가 해석한 이름을 넘긴다. 미전달이면 오버라이드/통합 지정 기준. */
  processedVendorName = effectiveVendorOf(unit, PROCESSED_CLASS, unified)?.name,
): string {
  if (vendorClass === PROCESSED_CLASS) return '';
  // 발주단위에 가공품 그룹이 없으면 직배송할 대상이 없다 — 아무것도 쓰지 않는다
  // (사용자 확정 2026-08-14: 종전엔 거래처명 없이 '가공품 거래처 직배송'을 남겨,
  //  가공품이 한 건도 없는 발주에도 무의미한 문구가 붙었다).
  if (!groups.some((g) => g.vendorClass === PROCESSED_CLASS)) return '';
  return processedVendorName ? `가공품 거래처(${processedVendorName}) 직배송` : '';
}

// ── 예외 규칙 리졸버(파생 단일 권위) ────────────────────────────────────────

/** 거래처 그룹 1개의 확정 파생값 — 오버라이드 > 예외 규칙 > 내장 기본을 이미 접은 결과다. */
export interface VendorDefaults {
  /** 유효 거래처 — 미지정이면 undefined(확정 게이트가 막는다). */
  vendor?: { code: string; name: string };
  dueDate: string;
  /** 비고 **메시지**(finalNoteOf 의 [메시지] 부분) — 최종 문자열이 아니다. */
  noteMessage: string;
  /** 예외 규칙이 값을 준 필드 — 카드 마이크로 캡션 표시용(오버라이드가 이겼으면 비어 있다). */
  appliedRule?: { due?: string; vendor?: boolean; note?: boolean };
}

/** 거래처명 비교 정규화 — 공백 제거 + 소문자화('(주)와이엔에스테크닉스' vs '와이엔에스'). */
function normVendorName(name: string): string {
  return name.replace(/\s+/g, '').toLowerCase();
}

/**
 * 예외 대상 판정 — 분류 정확 일치 / 유효 거래처명 **부분 일치(포함)** / 그 분류만 제외한 전부.
 * vendor 는 부분 일치다 — 패턴 표의 표기('와이엔에스')가 ERP 정식명('(주)와이엔에스테크닉스')의
 * 축약이라 정확 일치로는 발화하지 않는다(실측 2026-08-21). 값이 유효 거래처명에 포함되면 매칭.
 */
function scopeMatches(
  exception: PatternException,
  vendorClass: string,
  vendorName: string,
): boolean {
  const value = exception.scope.value.trim();
  switch (exception.scope.kind) {
    case 'vendorClass':
      return vendorClass === value;
    case 'vendor':
      return value.length > 0 && normVendorName(vendorName).includes(normVendorName(value));
    case 'exceptClass':
      return vendorClass !== value;
  }
}

/** 필드별 first-wins — 매칭 예외를 배열 순서로 훑어 그 필드를 **가진** 첫 예외가 이긴다. */
function firstException<T>(
  exceptions: readonly PatternException[],
  vendorClass: string,
  vendorName: string,
  pick: (exception: PatternException) => T | undefined,
): T | undefined {
  for (const exception of exceptions) {
    if (!scopeMatches(exception, vendorClass, vendorName)) continue;
    const value = pick(exception);
    if (value !== undefined) return value;
  }
  return undefined;
}

/** 예외가 고정한 거래처명 → 카탈로그 코드. 목록에 없는 이름이면 코드 없이 이름만 쓴다. */
function pinnedVendorOf(vendorClass: string, name: string): { code: string; name: string } {
  const option = vendorCategoryOf(vendorClass)?.options.find((o) => o.name === name);
  return { code: option?.code ?? '', name };
}

/** 납기 예외 캡션 — 'FRAME −3주'(0주면 기준일 이름만). */
function dueRuleLabel(rule: ExceptionDueRule): string {
  return rule.offsetWeeks > 0 ? `${rule.base} −${rule.offsetWeeks}주` : rule.base;
}

/**
 * 발주단위 1건의 거래처 그룹별 확정값 — **저장하지 않고** 렌더·페이로드 시점에 즉석 파생한다.
 * 따라서 통합 기준일·통합 거래처를 바꾸면 자동으로 따라오고, 개별 수정(vendorEdits)은
 * 구조적으로 보존된다.
 *
 * 우선순위는 필드마다 독립이다: **vendorEdits(개별 수정) > 예외 규칙(배열 순서 first-wins)
 * > 내장 기본**(통합 지정 / vendorDueOf / defaultNoteOf).
 *
 * 해석 순서 — ① 거래처(납기·비고의 'vendor' scope 판정이 유효 거래처명을 쓰므로 먼저 확정,
 * 이 단계의 scope 는 vendorClass/exceptClass 만 본다) → ② 가공품 그룹 납기 1패스('가공품납기'
 * 기준 예외는 자기 그룹에서 해석 불가라 스킵) → ③ 나머지 그룹 납기 2패스(procDue 전달) →
 * ④ 비고. 이 2패스 구조가 '가공품납기' 기준의 순환을 원천 차단한다.
 */
export function vendorDefaultsOf(
  unit: OrderUnit,
  groups: readonly VendorGroup[],
  baseDates: BaseDates,
  unified: UnifiedVendors,
): ReadonlyMap<string, VendorDefaults> {
  const exceptions = unit.patternRule?.exceptions ?? [];

  // ① 거래처 — 오버라이드 ?? 예외 고정 ?? 통합 지정.
  const vendors = new Map<string, { vendor?: { code: string; name: string }; pinned: boolean }>();
  for (const g of groups) {
    const override = unit.vendorEdits[g.vendorClass]?.vendor;
    // 'vendor' scope 에는 거래처 고정을 둘 수 없다(자기참조 — 검증기가 거부).
    const pinned = override
      ? undefined
      : firstException(exceptions, g.vendorClass, '', (x) =>
          x.scope.kind === 'vendor' ? undefined : x.vendor,
        );
    vendors.set(g.vendorClass, {
      vendor: override ?? (pinned ? pinnedVendorOf(g.vendorClass, pinned) : unified[g.vendorClass]),
      pinned: pinned != null,
    });
  }

  /** scope 판정용 유효 거래처명 — 실거래처 그룹은 분류명 자체가 거래처명이다. */
  const nameOf = (vendorClass: string): string =>
    isSwappableVendorClass(vendorClass, unified)
      ? (vendors.get(vendorClass)?.vendor?.name ?? '')
      : vendorClass;

  /** procDue=undefined 는 가공품 그룹 자신을 해석하는 1패스 — '가공품납기' 예외를 건너뛴다. */
  const dueOf = (vendorClass: string, procDue: string | undefined) => {
    const override = unit.vendorEdits[vendorClass]?.dueDate;
    if (override) return { dueDate: override };
    const rule = firstException(exceptions, vendorClass, nameOf(vendorClass), (x) =>
      x.due && !(procDue === undefined && x.due.base === PROCESSED_DUE_BASE) ? x.due : undefined,
    );
    const resolved = rule ? resolveDueRule(rule, baseDates, procDue) : '';
    // 기준일 미입력 등으로 해석값이 비면 내장 기본으로 폴백한다(빈 납기를 만들지 않는다).
    if (rule && resolved) return { dueDate: resolved, applied: dueRuleLabel(rule) };
    return { dueDate: vendorDueOf(unit.dueDate, vendorClass) };
  };

  // ② 가공품 그룹 납기 1패스 — 이 값이 '가공품납기' 기준 예외의 출발점(procDue)이다.
  const hasProcessed = groups.some((g) => g.vendorClass === PROCESSED_CLASS);
  const processedDue = hasProcessed ? dueOf(PROCESSED_CLASS, undefined) : undefined;
  const processedName = hasProcessed ? nameOf(PROCESSED_CLASS) : undefined;

  const out = new Map<string, VendorDefaults>();
  for (const g of groups) {
    // ③ 납기 2패스 — 가공품 그룹은 1패스 결과를 그대로 재사용한다(재해석 없음).
    const due =
      g.vendorClass === PROCESSED_CLASS && processedDue
        ? processedDue
        : dueOf(g.vendorClass, processedDue?.dueDate ?? '');
    // ④ 비고 — '' 저장도 오버라이드(문구를 지운 상태)라 ?? 로 가른다.
    const noteOverride = unit.vendorEdits[g.vendorClass]?.note;
    const noteException =
      noteOverride === undefined
        ? firstException(exceptions, g.vendorClass, nameOf(g.vendorClass), (x) => x.note)
        : undefined;
    const noteMessage =
      noteOverride ??
      noteException ??
      defaultNoteOf(unit, g.vendorClass, groups, unified, processedName);

    const vendor = vendors.get(g.vendorClass);
    const applied = {
      ...(due.applied ? { due: due.applied } : null),
      ...(vendor?.pinned ? { vendor: true } : null),
      ...(noteException !== undefined ? { note: true } : null),
    };
    out.set(g.vendorClass, {
      vendor: vendor?.vendor,
      dueDate: due.dueDate,
      noteMessage,
      ...(Object.keys(applied).length > 0 ? { appliedRule: applied } : null),
    });
  }
  return out;
}

/**
 * 최종 비고 = **최종 구매사유 + [비고 메시지]**(사용자 규칙 2026-08-14) — ERP 발주 리스트의
 * 비고에는 기본적으로 구매사유가 포함되고, 뒤에 메시지가 대괄호로 묶여 붙거나 안 붙는다.
 *   예) 'CX85-137 · 12CH PROCESS BUFFER [가공품 거래처(해룡엔지니어링) 직배송]'
 *
 * 앞부분은 **구매사유 필드에 들어가는 것과 같은 완성 문자열**(finalPurchaseReasonOf)이다 —
 * 두 필드가 어긋나지 않게 한 함수를 공유한다. 메시지는 리졸버가 이미 접은 값
 * (vendorDefaultsOf 의 noteMessage — 오버라이드 > 예외 note > defaultNoteOf)을 받는다.
 * 빈 값은 빠지므로 가공품 그룹(메시지 없음)과 메시지를 지운 그룹은 구매사유만 남는다
 * (대괄호도 함께 사라진다 — 빈 '[]' 를 남기지 않는다).
 * 최종 계획서 표기와 제출 페이로드가 이 함수 하나를 공유한다(표기 = 전달값).
 */
export function finalNoteOf(
  project: { code: string; name: string },
  unit: OrderUnit,
  noteMessage: string,
): string {
  const message = noteMessage.trim();
  return [finalPurchaseReasonOf(project, unit), message && `[${message}]`]
    .filter(Boolean)
    .join(' ');
}

// ── 합계 ─────────────────────────────────────────────────────────────────────

export interface CountAmount {
  parts: number;
  amount: number;
}

export function unitTotals(bom: PlanBom, unit: OrderUnit): CountAmount {
  const mods = modulesOf(bom, unit);
  return {
    parts: mods.reduce((s, m) => s + m.parts.length, 0),
    amount: mods.reduce((s, m) => s + moduleAmount(m), 0),
  };
}

/** 풀 선택 툴바 요약 — '모듈 N개 · 부품 M개 · 금액 X원 선택'. */
export function selectionTotals(
  bom: PlanBom,
  codes: ReadonlySet<string>,
): CountAmount & { modules: number } {
  const mods = bom.modules.filter((m) => codes.has(m.itemCode));
  return {
    modules: mods.length,
    parts: mods.reduce((s, m) => s + m.parts.length, 0),
    amount: mods.reduce((s, m) => s + moduleAmount(m), 0),
  };
}

export interface PlanTotals extends CountAmount {
  units: number;
  vendorGroups: number;
  /** 거래처 미지정 그룹 수(교체 가능한 분류 기준). */
  unassignedVendors: number;
}

export function planTotalsOf(
  bom: PlanBom,
  units: readonly OrderUnit[],
  unified: UnifiedVendors,
  baseDates: BaseDates,
): PlanTotals {
  let vendorGroups = 0;
  let unassignedVendors = 0;
  let parts = 0;
  let amount = 0;
  for (const u of units) {
    const groups = vendorGroupsOf(modulesOf(bom, u));
    vendorGroups += groups.length;
    // 미지정 판정은 리졸버 산출값 기준 — 통합 지정이나 예외 고정이 살아 있으면 지정으로 본다
    // (확정 게이트 planGateOf 와 같은 판정이어야 하단 요약의 '미지정 n' 이 어긋나지 않는다).
    const defaults = vendorDefaultsOf(u, groups, baseDates, unified);
    unassignedVendors += groups.filter(
      (g) => isSwappableVendorClass(g.vendorClass, unified) && !defaults.get(g.vendorClass)?.vendor,
    ).length;
    const t = unitTotals(bom, u);
    parts += t.parts;
    amount += t.amount;
  }
  return { units: units.length, vendorGroups, unassignedVendors, parts, amount };
}

// ── 확정 게이트 ──────────────────────────────────────────────────────────────

export interface PlanGate {
  ready: boolean;
  /** 미충족 항목 힌트(확정 버튼 옆 안내). 충족 시 빈 배열. */
  hints: string[];
}

/**
 * 계획 확정 조건 — 발주단위 1개 이상 + 모든 발주단위에 구매사유·납기 입력 + 교체 가능한
 * 거래처 분류 전부 지정(기본값 적용 후 기준 — 통합 지정이 살아 있으면 통과).
 * 미배정 모듈은 허용(확정을 막지 않는다 — 남은 모듈은 다음 발주로 돌린다).
 */
export function planGateOf(
  bom: PlanBom,
  units: readonly OrderUnit[],
  unified: UnifiedVendors,
  baseDates: BaseDates,
): PlanGate {
  const hints: string[] = [];
  if (units.length === 0) hints.push('발주단위를 1개 이상 만드세요.');
  const noReason = units.filter((u) => !u.purchaseReason.trim()).map((u) => u.seq);
  if (noReason.length > 0) hints.push(`구매사유 미입력 — 발주 ${noReason.join('·')}`);
  const noDue = units.filter((u) => !u.dueDate).map((u) => u.seq);
  if (noDue.length > 0) hints.push(`납기예정일 미입력 — 발주 ${noDue.join('·')}`);
  const unassigned = units.flatMap((u) => {
    const groups = vendorGroupsOf(modulesOf(bom, u));
    const defaults = vendorDefaultsOf(u, groups, baseDates, unified);
    return groups
      .filter(
        (g) =>
          isSwappableVendorClass(g.vendorClass, unified) && !defaults.get(g.vendorClass)?.vendor,
      )
      .map((g) => `발주 ${u.seq} ${g.vendorClass}`);
  });
  if (unassigned.length > 0) hints.push(`거래처 미지정 — ${unassigned.join(', ')}`);
  return { ready: hints.length === 0, hints };
}

// ── 실행 페이로드(확정 제출) ─────────────────────────────────────────────────

/**
 * 에이전트 실행 파라미터(PlanSubmit) — 라이브는 POST /runs/hitl 의 plan 으로 제출한다.
 * project 는 사용자가 선택한 값이며, 거래처 그룹의 vendor/dueDate/note 는 리졸버
 * (vendorDefaultsOf — 오버라이드 > 패턴 예외 > 내장 기본)가 접은 확정값이다.
 * wbs 는 BOM 값을 그대로 쓴다.
 *
 * ⚠ note 는 **최종 비고**(finalNoteOf = 구매사유 + 비고 메시지)다 — 입력란이 받은
 *   메시지가 아니라 ERP 에 들어갈 완성 문자열이며, 최종 계획서 표기와 같은 값이다.
 */
export function buildPlanPayload(
  bom: PlanBom,
  project: { code: string; name: string },
  units: readonly OrderUnit[],
  unified: UnifiedVendors,
  baseDates: BaseDates,
): PlanSubmit {
  return {
    project: { code: project.code, name: project.name },
    wbs: bom.project.wbs,
    units: units.map((u) => {
      const groups = vendorGroupsOf(modulesOf(bom, u));
      const defaults = vendorDefaultsOf(u, groups, baseDates, unified);
      return {
        seq: u.seq,
        purchaseReason: finalPurchaseReasonOf(project, u),
        dueDate: u.dueDate,
        modules: modulesOf(bom, u).map((m) => ({
          itemCode: m.itemCode,
          name: m.name,
          spec: m.spec,
        })),
        vendorGroups: groups.map((g) => {
          const d = defaults.get(g.vendorClass);
          return {
            vendorClass: g.vendorClass,
            vendor: isSwappableVendorClass(g.vendorClass, unified)
              ? (d?.vendor?.name ?? null)
              : g.vendorClass,
            parts: g.parts.length,
            amount: g.amount,
            dueDate: d?.dueDate ?? '',
            note: finalNoteOf(project, u, d?.noteMessage ?? ''),
          };
        }),
      };
    }),
  };
}
