'use client';

/**
 * usePlanState — 계획서 작성 상태(units 단일 소스 + 모듈 선택) 훅.
 * 데모 루트(purchase-order-simulation)와 라이브 개입 카드(LivePlannerCard)가 공유한다.
 *
 * 파생값(assigned/totals/gate)은 전부 units 에서 계산하며, 이벤트 핸들러는 불변
 * 업데이트만 한다(모델 주석 참조 — newOrderUnit 만 시퀀스 부작용).
 */

import { useMemo, useState } from 'react';
import {
  assignedSeqMap,
  defaultPurchaseReasonOf,
  newOrderUnit,
  nextUnitSeq,
  planGateOf,
  planTotalsOf,
  type OrderUnit,
  type PlanBom,
  type PlanGate,
  type PlanTotals,
  type VendorEdit,
} from './model';

export interface PlanState {
  selected: ReadonlySet<string>;
  units: readonly OrderUnit[];
  /** 모듈 itemCode → 배정된 발주 seq(파생) — 중복 배정 차단. */
  assigned: ReadonlyMap<string, number>;
  totals: PlanTotals;
  gate: PlanGate;
  toggle: (code: string) => void;
  toggleAll: (codes: readonly string[], on: boolean) => void;
  /** 선택 모듈 → 발주단위 카드 생성(BOM 순서 유지) + 생성 즉시 선택 해제. */
  groupSelected: () => void;
  patchUnit: (id: string, patch: Partial<Pick<OrderUnit, 'purchaseReason' | 'dueDate'>>) => void;
  patchVendor: (id: string, vendorClass: string, patch: VendorEdit) => void;
  /** 모듈을 풀로 복귀 — 마지막 모듈 제거면 카드 자체를 지운다. */
  removeModule: (id: string, code: string) => void;
  removeUnit: (id: string) => void;
  /** 계획 초기화(프로젝트 변경 등) — units·선택을 함께 비운다. */
  reset: () => void;
}

export function usePlanState(
  bom: PlanBom,
  project: { code: string; name: string } | null,
): PlanState {
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set<string>());
  const [units, setUnits] = useState<readonly OrderUnit[]>([]);

  const assigned = useMemo(() => assignedSeqMap(units), [units]);
  const totals = useMemo(() => planTotalsOf(bom, units), [bom, units]);
  const gate = useMemo(() => planGateOf(bom, units), [bom, units]);

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

  const patchUnit = (id: string, patch: Partial<Pick<OrderUnit, 'purchaseReason' | 'dueDate'>>) =>
    setUnits((prev) => prev.map((u) => (u.id === id ? { ...u, ...patch } : u)));

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
    toggle,
    toggleAll,
    groupSelected,
    patchUnit,
    patchVendor,
    removeModule,
    removeUnit,
    reset,
  };
}
