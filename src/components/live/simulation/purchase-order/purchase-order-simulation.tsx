'use client';

import { useMemo, useState } from 'react';
import { RiFolderLine, RiStackLine } from '@remixicon/react';
import { SectionCard } from '@/components/ui/section-card';
import { EmptyState } from '@/components/ui/empty-state';
import type { SimulationPanelProps } from '../index';
import {
  MODULES,
  assignedSeqMap,
  buildPlanPayload,
  defaultPurchaseReasonOf,
  newOrderUnit,
  nextUnitSeq,
  planGateOf,
  planTotalsOf,
  type OrderUnit,
  type VendorEdit,
} from './model';
import { ModulePoolTable } from './module-pool-table';
import { OrderUnitCard } from './order-unit-card';
import { ConfirmedView, PlanFooter, PlanHeader } from './plan-summary';
import { SimSectionHeader } from './ui';

/**
 * 구매발주 계획서 — 프론트 더미 시뮬레이션(백엔드 자동화 그래프 미연결).
 *
 * 옴니솔 구매발주 반복 루프(3레벨 모듈 선택 → 납기·구매사유 입력 → 저장 = 발주 1건)를
 * 계획서 한 장으로 대체한다: 모듈 풀에서 묶어 발주단위를 만들고, 발주단위별 구매사유·납기와
 * 거래처 그룹별 실거래처·납기·비고까지 확정한다. 어떤 단계에서도 서버로 나가지 않는다.
 *
 * 상태 설계 — units 배열이 단일 소스. 모듈→발주 매핑(assignedSeqMap)·거래처 그룹·합계는
 * 전부 렌더 시 파생하며, 중복 배정은 파생 맵으로 강제한다(배정된 모듈은 풀에서 체크 불가).
 * 프로젝트는 사용자 선택(초기 미선택) — 미선택이면 본문 대신 empty-state 를 그리고,
 * 변경/해제는 units 초기화를 동반한다(작성 중이면 InlineConfirm 으로 확인).
 */
export function PurchaseOrderSimulation({ agent }: SimulationPanelProps) {
  const [project, setProject] = useState<{ code: string; name: string } | null>(null);
  /** 프로젝트 변경/해제 대기 — 작성 중 발주단위가 있을 때 확인 후 적용(next=null 은 해제). */
  const [pendingProject, setPendingProject] = useState<{
    next: { code: string; name: string } | null;
  } | null>(null);
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set<string>());
  const [units, setUnits] = useState<readonly OrderUnit[]>([]);
  const [confirmed, setConfirmed] = useState(false);

  const assigned = useMemo(() => assignedSeqMap(units), [units]);
  const totals = useMemo(() => planTotalsOf(units), [units]);
  const gate = useMemo(() => planGateOf(units), [units]);
  const payload = useMemo(
    () => (confirmed && project ? buildPlanPayload(project, units) : null),
    [confirmed, project, units],
  );

  /** 프로젝트 적용 = 계획 초기화 — units·선택·확정이 프로젝트 BOM 에 종속이라 함께 비운다. */
  const applyProject = (next: { code: string; name: string } | null) => {
    setProject(next);
    setUnits([]);
    setSelected(new Set<string>());
    setConfirmed(false);
    setPendingProject(null);
  };

  const requestProject = (next: { code: string; name: string } | null) => {
    if (next && next.code === project?.code) return; // 동일 프로젝트 재선택 — 초기화 불필요.
    if (units.length === 0) applyProject(next);
    else setPendingProject({ next });
  };

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

  /** 선택 모듈 → 발주단위 카드 생성(BOM 순서 유지) + 생성 즉시 선택 해제. */
  const groupSelected = () => {
    const codes = MODULES.filter((m) => selected.has(m.itemCode)).map((m) => m.itemCode);
    if (codes.length === 0 || project == null) return;
    setUnits((prev) => [
      ...prev,
      newOrderUnit(nextUnitSeq(prev), codes, defaultPurchaseReasonOf(project, codes)),
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

  /** 모듈을 풀로 복귀 — 마지막 모듈 제거면 카드 자체를 지운다. */
  const removeModule = (id: string, code: string) =>
    setUnits((prev) =>
      prev.flatMap((u) => {
        if (u.id !== id) return [u];
        const rest = u.moduleCodes.filter((c) => c !== code);
        return rest.length === 0 ? [] : [{ ...u, moduleCodes: rest }];
      }),
    );

  const removeUnit = (id: string) => setUnits((prev) => prev.filter((u) => u.id !== id));

  return (
    // 헤더는 실행 전 입력 폼(pre-run)과 같은 문법 — 시뮬레이션 배지·더미 언급은 UI 에
    // 노출하지 않는다(2026-08-05 사용자 확정, tax-invoice 와 동일).
    // 카드를 뷰포트에 고정하지 않는다(lg:h-full·overflow 금지) — 내부스크롤 중첩이 생겨
    // 전체 컨텐츠는 페이지 스크롤로 흐르게 한다(2026-08-13 사용자 지적). 자체 스크롤은
    // 목록성 영역(모듈 풀 max-h·페이로드 pre)만 갖는다.
    <SectionCard
      caption="실행 전 입력"
      title={`${agent.name} 계획서`}
      description="프로젝트 BOM 조회와 이동요청 저장은 에이전트가 자동 처리합니다. 이 계획서에서는 반복 루프 입력 — 발주단위(모듈 묶음)·구매사유·납기예정일과 거래처 지정 — 을 한 번에 작성합니다."
      density="comfortable"
      className="lg:self-start"
    >
      <div className="flex flex-col gap-5">
        <PlanHeader
          project={project}
          onProjectSelect={(opt) => requestProject({ code: opt.code, name: opt.name })}
          onProjectClear={() => requestProject(null)}
          resetConfirm={
            pendingProject
              ? {
                  question: pendingProject.next
                    ? '프로젝트를 변경하면 작성 중인 발주단위가 초기화됩니다'
                    : '프로젝트를 해제하면 작성 중인 발주단위가 초기화됩니다',
                  onConfirm: () => applyProject(pendingProject.next),
                  onCancel: () => setPendingProject(null),
                }
              : null
          }
          totals={totals}
          assignedModules={assigned.size}
        />

        {project == null ? (
          <EmptyState
            icon={<RiFolderLine size={18} aria-hidden />}
            title="프로젝트를 선택하세요"
            description="위 프로젝트 선택에서 계획서를 작성할 프로젝트를 고르면 BOM 모듈 풀이 표시됩니다."
            compact
          />
        ) : confirmed && payload ? (
          <ConfirmedView
            units={units}
            totals={totals}
            payload={payload}
            onEdit={() => setConfirmed(false)}
          />
        ) : (
          <>
            <ModulePoolTable
              assigned={assigned}
              selected={selected}
              onToggle={toggle}
              onToggleAll={toggleAll}
              onGroup={groupSelected}
            />

            <section className="flex flex-col gap-3">
              <SimSectionHeader
                title="발주단위 — 구매사유·납기·거래처 지정"
                prompt="발주단위마다 구매사유와 납기예정일을 입력하고, 가공품·판금품 그룹에 실거래처를 지정하세요. 그룹별 납기·비고는 필요할 때만 덮어씁니다."
              />
              {units.length === 0 ? (
                <EmptyState
                  icon={<RiStackLine size={18} aria-hidden />}
                  title="발주단위가 없습니다"
                  description="위 모듈 풀에서 모듈을 선택해 발주단위로 묶으세요."
                  compact
                />
              ) : (
                units.map((u) => (
                  <OrderUnitCard
                    key={u.id}
                    unit={u}
                    onPatch={(patch) => patchUnit(u.id, patch)}
                    onVendorPatch={(vendorClass, patch) => patchVendor(u.id, vendorClass, patch)}
                    onRemoveModule={(code) => removeModule(u.id, code)}
                    onRemove={() => removeUnit(u.id)}
                  />
                ))
              )}
            </section>

            <PlanFooter
              totals={totals}
              assignedModules={assigned.size}
              gate={gate}
              onConfirm={() => setConfirmed(true)}
            />
          </>
        )}
      </div>
    </SectionCard>
  );
}
