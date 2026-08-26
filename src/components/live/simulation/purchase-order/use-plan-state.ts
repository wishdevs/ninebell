'use client';

/**
 * usePlanState — 계획서 작성 상태(units 단일 소스 + 모듈 선택 + 통합 지정) 훅.
 * 라이브 개입 카드(LivePlannerCard)가 쓴다.
 *
 * 파생값(assigned/totals/gate)은 전부 units 에서 계산하며, 이벤트 핸들러는 불변
 * 업데이트만 한다(모델 주석 참조 — newOrderUnit 만 시퀀스 부작용).
 *
 * 초기 units 는 발주 패턴으로 편성한다(matchPatternUnits) — 패턴이 없거나 매칭이 하나도
 * 없으면 종전처럼 빈 배열이고, 매칭 안 된 모듈은 풀에 남아 수동 묶기로 처리한다.
 */

import { useEffect, useMemo, useState } from 'react';
import type { BaseDateKey, BaseDates, PatternGroup } from '@/lib/purchase/order-patterns';
import { defaultUnifiedVendors, type VendorCategory } from './catalog';
import {
  assignedSeqMap,
  defaultPurchaseReasonOf,
  newOrderUnit,
  nextUnitSeq,
  planGateOf,
  planTotalsOf,
  resolveDueRule,
  type OrderUnit,
  type PlanBom,
  type PlanGate,
  type PlanTotals,
  type UnifiedVendors,
  type VendorEdit,
} from './model';
import { matchPatternUnits, type UnmatchedModule } from './pattern';

export interface PlanState {
  selected: ReadonlySet<string>;
  units: readonly OrderUnit[];
  /** 모듈 itemCode → 배정된 발주 seq(파생) — 중복 배정 차단. */
  assigned: ReadonlyMap<string, number>;
  totals: PlanTotals;
  gate: PlanGate;
  /**
   * 패턴에 걸리지 않은 모듈(시드 시점 고정) — 계획서 상단 안내 배너의 재료다. 수동으로
   * 묶어도 안내는 남는다(풀의 배정 여부는 assigned 가 담당).
   */
  patternUnmatched: readonly UnmatchedModule[];
  /** 통합 납기 기준일(FRAME·1공장·3공장) — 패턴 발주단위의 납기를 최초 세팅한다. */
  baseDates: BaseDates;
  /** 통합 거래처 지정(분류별) — 그룹 오버라이드가 없을 때 접히는 기본값. */
  unifiedVendors: UnifiedVendors;
  toggle: (code: string) => void;
  toggleAll: (codes: readonly string[], on: boolean) => void;
  /** 선택 모듈 → 발주단위 카드 생성(BOM 순서 유지) + 생성 즉시 선택 해제. */
  groupSelected: () => void;
  /** 선택 모듈을 **기존** 발주단위에 추가(BOM 순서 병합) + 선택 해제 — 패턴 미매칭 모듈을
   *  새 발주로만 묶을 수 있던 갭 해소(사용자 요청 2026-08-26). 구매사유는 건드리지 않는다
   *  (생성 시 1회 시드 규칙과 동일 — 이후 모듈 증감이 문구를 덮지 않는다). */
  addSelectedToUnit: (unitId: string) => void;
  patchUnit: (id: string, patch: Partial<Pick<OrderUnit, 'purchaseReason' | 'dueDate'>>) => void;
  patchVendor: (id: string, vendorClass: string, patch: VendorEdit) => void;
  /** 모듈을 풀로 복귀 — 마지막 모듈 제거면 카드 자체를 지운다. */
  removeModule: (id: string, code: string) => void;
  removeUnit: (id: string) => void;
  /** 기준일 변경 — 손대지 않은 패턴 발주단위의 납기만 다시 시드한다. */
  setBaseDate: (key: BaseDateKey, date: string) => void;
  setUnifiedVendor: (
    vendorClass: string,
    vendor: { code: string; name: string } | undefined,
  ) => void;
  /** 계획 초기화(프로젝트 변경 등) — units·선택을 함께 비운다. */
  reset: () => void;
}

/**
 * 기준일이 바뀌었을 때의 발주단위 납기 재시드 — 규칙이 없거나 사람이 직접 고친 단위는
 * 건드리지 않고, 규칙을 해석할 수 없으면(기준일 미입력 등) 기존 값을 그대로 둔다.
 */
function reseedDue(unit: OrderUnit, baseDates: BaseDates): OrderUnit {
  const rule = unit.patternRule?.due;
  if (!rule || unit.dueTouched) return unit;
  const due = resolveDueRule(rule, baseDates);
  return due && due !== unit.dueDate ? { ...unit, dueDate: due } : unit;
}

export function usePlanState(
  bom: PlanBom,
  project: { code: string; name: string } | null,
  patterns: readonly PatternGroup[],
  vendorCategories: readonly VendorCategory[],
): PlanState {
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set<string>());
  // 시드는 1회 — units 는 이후 편집되지만, 미매칭 안내는 시드 시점 그대로 고정한다.
  const [seed] = useState(() => matchPatternUnits(bom, patterns));
  const [units, setUnits] = useState<readonly OrderUnit[]>(seed.units);
  const [baseDates, setBaseDates] = useState<BaseDates>({});
  // 통합 지정 초기값도 시드 1회 — 후보 목록 갱신이 작성 중 상태를 덮지 않는다.
  const [unifiedVendors, setUnifiedVendors] = useState<UnifiedVendors>(() =>
    defaultUnifiedVendors(vendorCategories),
  );

  const assigned = useMemo(() => assignedSeqMap(units), [units]);
  // 거래처 그룹 파생값이 기준일을 타므로(예외 납기) 합계·게이트도 baseDates 에 의존한다.
  const totals = useMemo(
    () => planTotalsOf(bom, units, unifiedVendors, baseDates),
    [bom, units, unifiedVendors, baseDates],
  );
  const gate = useMemo(
    () => planGateOf(bom, units, unifiedVendors, baseDates),
    [bom, units, unifiedVendors, baseDates],
  );

  const toggle = (code: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });

  const toggleAll = (codes: readonly string[], on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      for (const c of codes) {
        if (on) next.add(c);
        else next.delete(c);
      }
      return next;
    });

  const groupSelected = () => {
    const codes = bom.modules.filter((m) => selected.has(m.itemCode)).map((m) => m.itemCode);
    if (codes.length === 0 || project == null) return;
    setUnits((prev) => [
      ...prev,
      newOrderUnit(nextUnitSeq(prev), codes, defaultPurchaseReasonOf(bom, codes)),
    ]);
    setSelected(new Set<string>());
  };

  const addSelectedToUnit = (id: string) => {
    if (selected.size === 0) return;
    setUnits((prev) =>
      prev.map((u) => {
        if (u.id !== id) return u;
        // BOM 순서로 병합 — 기존 코드와 선택 코드의 합집합을 bom.modules 순서로 다시 깐다.
        const member = new Set([...u.moduleCodes, ...selected]);
        return {
          ...u,
          moduleCodes: bom.modules.filter((m) => member.has(m.itemCode)).map((m) => m.itemCode),
        };
      }),
    );
    setSelected(new Set<string>());
  };

  const patchUnit = (id: string, patch: Partial<Pick<OrderUnit, 'purchaseReason' | 'dueDate'>>) =>
    setUnits((prev) =>
      prev.map((u) =>
        u.id === id
          ? // 납기를 직접 고치면 그 단위는 통합 기준일 재시드 대상에서 빠진다.
            { ...u, ...patch, ...(patch.dueDate === undefined ? null : { dueTouched: true }) }
          : u,
      ),
    );

  const patchVendor = (id: string, vendorClass: string, patch: VendorEdit) =>
    setUnits((prev) =>
      prev.map((u) =>
        u.id === id
          ? {
              ...u,
              vendorEdits: {
                ...u.vendorEdits,
                [vendorClass]: { ...u.vendorEdits[vendorClass], ...patch },
              },
            }
          : u,
      ),
    );

  const removeModule = (id: string, code: string) =>
    setUnits((prev) =>
      prev.flatMap((u) => {
        if (u.id !== id) return [u];
        const rest = u.moduleCodes.filter((c) => c !== code);
        return rest.length === 0 ? [] : [{ ...u, moduleCodes: rest }];
      }),
    );

  const removeUnit = (id: string) => setUnits((prev) => prev.filter((u) => u.id !== id));

  const setBaseDate = (key: BaseDateKey, date: string) =>
    setBaseDates((prev) => ({ ...prev, [key]: date }));

  // 기준일 변경 → 재시드는 상태 확정 후 이펙트로. setBaseDate 안에서 클로저의 baseDates 를
  // 읽으면 같은 틱의 연속 변경이 배치되며 앞선 변경이 유실될 수 있다(리뷰 지적 2026-08-21).
  useEffect(() => {
    setUnits((prev) => prev.map((u) => reseedDue(u, baseDates)));
  }, [baseDates]);

  const setUnifiedVendor = (
    vendorClass: string,
    vendor: { code: string; name: string } | undefined,
  ) => setUnifiedVendors((prev) => ({ ...prev, [vendorClass]: vendor }));

  const reset = () => {
    setUnits([]);
    setSelected(new Set<string>());
  };

  return {
    selected,
    units,
    assigned,
    totals,
    gate,
    patternUnmatched: seed.unmatched,
    baseDates,
    unifiedVendors,
    toggle,
    toggleAll,
    groupSelected,
    addSelectedToUnit,
    patchUnit,
    patchVendor,
    removeModule,
    removeUnit,
    setBaseDate,
    setUnifiedVendor,
    reset,
  };
}
