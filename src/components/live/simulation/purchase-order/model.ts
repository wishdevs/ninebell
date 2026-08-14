/**
 * 구매발주 계획서 — 모델(타입·파생 헬퍼). 데모(정적 픽스처)와 라이브 개입(kind=planner,
 * hitl.plannerBom)이 **같은 조각**을 쓰도록 BOM 을 인자로 받는다 — 정적 전역 의존 없음.
 *
 * BOM shape 는 백/프론트 공유 계약(lib/live/types 의 PlannerBom = 데모 픽스처
 * purchase-order-bom.json 과 동일)이다. 호출부는 createPlanBom() 으로 파생 컨텍스트
 * (모듈 평탄화·맵)를 만들어 헬퍼에 넘긴다 — 데모 루트는 정적 JSON 을, LivePlannerCard 는
 * hitl.plannerBom 을 주입한다.
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
 * 의사 거래처 그룹의 기본 거래처 — 가공품 → 해룡, 판금품 → 알파테크.
 * 파생 기본값이다 — state(vendorEdits)에 복제 저장하지 않고 렌더·페이로드에서 접는다.
 * 코드는 catalog.ts VENDOR_FAVORITES 와 같은 V-xxxx 체계다.
 */
const DEFAULT_VENDOR_BY_CLASS: Readonly<Record<string, { code: string; name: string }>> = {
  [PROCESSED_CLASS]: { code: 'V-1003', name: '해룡' },
  판금품: { code: 'V-1002', name: '알파테크' },
};

/** 그룹의 유효 거래처 = 오버라이드 ?? 기본값. 기본값 없는 의사 그룹만 undefined(미지정). */
export function effectiveVendorOf(
  unit: OrderUnit,
  vendorClass: string,
): { code: string; name: string } | undefined {
  return unit.vendorEdits[vendorClass]?.vendor ?? DEFAULT_VENDOR_BY_CLASS[vendorClass];
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
export function defaultPurchaseReasonOf(
  bom: PlanBom,
  moduleCodes: readonly string[],
): string {
  return moduleCodes
    .map((c) => bom.moduleMap.get(c)?.name ?? '')
    .filter((n) => n.startsWith(OUTSOURCED_PREFIX))
    .map((n) => n.slice(OUTSOURCED_PREFIX.length))
    .join('·');
}

/** 구매사유·비고에 붙는 프로젝트 접두 — '코드 · 프로젝트명'. */
function projectPrefixOf(project: { code: string; name: string }): string {
  return [project.code.trim(), project.name.trim()].filter(Boolean).join(' · ');
}

/**
 * 최종 구매사유 = **[프로젝트 코드 · 명] + [입력한 모듈명]**(사용자 규칙 2026-08-14).
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
 * 그룹 기본 **비고 메시지** — 가공품 외 그룹은 '가공품 거래처(해룡) 직배송'. 괄호 안은 그
 * 발주단위 가공품 그룹의 유효 거래처명 동적 표기(가공품 그룹이 없으면 괄호 생략). 사유:
 * 가공품 외 거래처가 제작품을 가공품 제작처로 직배송하고, 거기서 조립해 모듈 단위로 받는다.
 *
 * ⚠ 여기엔 구매사유가 들어가지 않는다 — 입력란은 **메시지만** 받고, 구매사유와의 결합은
 *   최종 계획서(finalNoteOf → buildPlanPayload)에서 한다(사용자 확정 2026-08-14).
 */
export function defaultNoteOf(
  unit: OrderUnit,
  vendorClass: string,
  groups: readonly VendorGroup[],
): string {
  if (vendorClass === PROCESSED_CLASS) return '';
  const hasProcessed = groups.some((g) => g.vendorClass === PROCESSED_CLASS);
  const name = hasProcessed ? effectiveVendorOf(unit, PROCESSED_CLASS)?.name : undefined;
  return name ? `가공품 거래처(${name}) 직배송` : '가공품 거래처 직배송';
}

/**
 * 최종 비고 = **최종 구매사유 + [비고 메시지]**(사용자 규칙 2026-08-14) — ERP 발주 리스트의
 * 비고에는 기본적으로 구매사유가 포함되고, 뒤에 메시지가 대괄호로 묶여 붙거나 안 붙는다.
 *   예) 'CX85-137 · 12CH PROCESS BUFFER [가공품 거래처(해룡) 직배송]'
 *
 * 앞부분은 **구매사유 필드에 들어가는 것과 같은 완성 문자열**(finalPurchaseReasonOf)이다 —
 * 두 필드가 어긋나지 않게 한 함수를 공유한다. 메시지는 오버라이드(사용자 입력) 우선, 없으면
 * defaultNoteOf 파생. 빈 값은 빠지므로 가공품 그룹(메시지 없음)과 메시지를 지운 그룹은
 * 구매사유만 남는다(대괄호도 함께 사라진다 — 빈 '[]' 를 남기지 않는다).
 * 최종 계획서 표기와 제출 페이로드가 이 함수 하나를 공유한다(표기 = 전달값).
 */
export function finalNoteOf(
  project: { code: string; name: string },
  unit: OrderUnit,
  vendorClass: string,
  groups: readonly VendorGroup[],
): string {
  const message = (
    unit.vendorEdits[vendorClass]?.note ?? defaultNoteOf(unit, vendorClass, groups)
  ).trim();
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
  /** 실거래처 미지정 의사 그룹 수. */
  unassignedVendors: number;
}

export function planTotalsOf(bom: PlanBom, units: readonly OrderUnit[]): PlanTotals {
  let vendorGroups = 0;
  let unassignedVendors = 0;
  let parts = 0;
  let amount = 0;
  for (const u of units) {
    const groups = vendorGroupsOf(modulesOf(bom, u));
    vendorGroups += groups.length;
    // 미지정 판정은 기본값 적용 후(effective) 기준 — 기본 거래처가 있으면 지정으로 본다.
    unassignedVendors += groups.filter(
      (g) => g.isPseudo && !effectiveVendorOf(u, g.vendorClass),
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
 * 계획 확정 조건 — 발주단위 1개 이상 + 모든 발주단위에 구매사유·납기 입력 + 의사 거래처
 * 전부 지정(기본값 적용 후 기준 — 가공품·판금품은 기본 거래처가 있어 통과).
 * 미배정 모듈은 허용(확정을 막지 않는다 — 남은 모듈은 다음 발주로 돌린다).
 */
export function planGateOf(bom: PlanBom, units: readonly OrderUnit[]): PlanGate {
  const hints: string[] = [];
  if (units.length === 0) hints.push('발주단위를 1개 이상 만드세요.');
  const noReason = units.filter((u) => !u.purchaseReason.trim()).map((u) => u.seq);
  if (noReason.length > 0) hints.push(`구매사유 미입력 — 발주 ${noReason.join('·')}`);
  const noDue = units.filter((u) => !u.dueDate).map((u) => u.seq);
  if (noDue.length > 0) hints.push(`납기예정일 미입력 — 발주 ${noDue.join('·')}`);
  const unassigned = units.flatMap((u) =>
    vendorGroupsOf(modulesOf(bom, u))
      .filter((g) => g.isPseudo && !effectiveVendorOf(u, g.vendorClass))
      .map((g) => `발주 ${u.seq} ${g.vendorClass}`),
  );
  if (unassigned.length > 0) hints.push(`거래처 미지정 — ${unassigned.join(', ')}`);
  return { ready: hints.length === 0, hints };
}

// ── 실행 페이로드(확정 제출) ─────────────────────────────────────────────────

/**
 * 에이전트 실행 파라미터(PlanSubmit) — 데모는 확정 미리보기 pre 로, 라이브는
 * POST /runs/hitl 의 plan 으로 제출한다. project 는 사용자가 선택한 값이며, 거래처
 * 그룹의 vendor/dueDate 는 오버라이드가 없으면 파생 기본값(effectiveVendorOf·
 * vendorDueOf)으로 접어 넣는다. wbs 는 BOM 값을 그대로 쓴다.
 *
 * ⚠ note 는 **최종 비고**(finalNoteOf = 구매사유 + 비고 메시지)다 — 입력란이 받은
 *   메시지가 아니라 ERP 에 들어갈 완성 문자열이며, 최종 계획서 표기와 같은 값이다.
 */
export function buildPlanPayload(
  bom: PlanBom,
  project: { code: string; name: string },
  units: readonly OrderUnit[],
): PlanSubmit {
  return {
    project: { code: project.code, name: project.name },
    wbs: bom.project.wbs,
    units: units.map((u) => {
      const groups = vendorGroupsOf(modulesOf(bom, u));
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
          const edit = u.vendorEdits[g.vendorClass];
          return {
            vendorClass: g.vendorClass,
            vendor: g.isPseudo
              ? (effectiveVendorOf(u, g.vendorClass)?.name ?? null)
              : g.vendorClass,
            parts: g.parts.length,
            amount: g.amount,
            dueDate: edit?.dueDate || vendorDueOf(u.dueDate, g.vendorClass),
            note: finalNoteOf(project, u, g.vendorClass, groups),
          };
        }),
      };
    }),
  };
}
