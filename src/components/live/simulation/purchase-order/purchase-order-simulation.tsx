'use client';

import { useMemo, useState } from 'react';
import { RiFolderLine, RiStackLine } from '@remixicon/react';
import { SectionCard } from '@/components/ui/section-card';
import { EmptyState } from '@/components/ui/empty-state';
import raw from '@/lib/data/purchase-order-bom.json';
import type { SimulationPanelProps } from '../index';
import { buildPlanPayload, createPlanBom } from './model';
import { ModulePoolTable } from './module-pool-table';
import { OrderUnitCard } from './order-unit-card';
import { ConfirmedView, PlanFooter, PlanHeader, PlanReviewView } from './plan-summary';
import { SimSectionHeader } from './ui';
import { usePlanState } from './use-plan-state';

/** 데모 BOM — 정적 픽스처를 계획서 컨텍스트로 1회 파생(라이브는 hitl.plannerBom 주입). */
const DEMO_BOM = createPlanBom(raw);

/**
 * 구매발주 계획서 — 프론트 더미 시뮬레이션(백엔드 자동화 그래프 미연결).
 *
 * 옴니솔 구매발주 반복 루프(3레벨 모듈 선택 → 납기·구매사유 입력 → 저장 = 발주 1건)를
 * 계획서 한 장으로 대체한다: 모듈 풀에서 묶어 발주단위를 만들고, 발주단위별 구매사유·납기와
 * 거래처 그룹별 실거래처·납기·비고까지 확정한다. 어떤 단계에서도 서버로 나가지 않는다.
 *
 * 상태 설계 — units 배열이 단일 소스(usePlanState — 라이브 개입 카드와 공유). 모듈→발주
 * 매핑(assignedSeqMap)·거래처 그룹·합계는 전부 렌더 시 파생하며, 중복 배정은 파생 맵으로
 * 강제한다(배정된 모듈은 풀에서 체크 불가). 프로젝트는 사용자 선택(초기 미선택) —
 * 미선택이면 본문 대신 empty-state 를 그리고, 변경/해제는 units 초기화를 동반한다
 * (작성 중이면 InlineConfirm 으로 확인).
 */
export function PurchaseOrderSimulation({ agent }: SimulationPanelProps) {
  const [project, setProject] = useState<{ code: string; name: string } | null>(null);
  /** 프로젝트 변경/해제 대기 — 작성 중 발주단위가 있을 때 확인 후 적용(next=null 은 해제). */
  const [pendingProject, setPendingProject] = useState<{
    next: { code: string; name: string } | null;
  } | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  // 확정 2단계(사용자 요청 2026-08-14) — [전체 계획서 검토] → [다음 단계로 진행] → 확정 뷰.
  const [reviewing, setReviewing] = useState(false);

  const plan = usePlanState(DEMO_BOM, project);
  const payload = useMemo(
    () =>
      (reviewing || confirmed) && project ? buildPlanPayload(DEMO_BOM, project, plan.units) : null,
    [reviewing, confirmed, project, plan.units],
  );

  /** 프로젝트 적용 = 계획 초기화 — units·선택·확정이 프로젝트 BOM 에 종속이라 함께 비운다. */
  const applyProject = (next: { code: string; name: string } | null) => {
    setProject(next);
    plan.reset();
    setConfirmed(false);
    setReviewing(false);
    setPendingProject(null);
  };

  const requestProject = (next: { code: string; name: string } | null) => {
    if (next && next.code === project?.code) return; // 동일 프로젝트 재선택 — 초기화 불필요.
    if (plan.units.length === 0) applyProject(next);
    else setPendingProject({ next });
  };

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
          bom={DEMO_BOM}
          project={project}
          picker={{
            onSelect: (opt) => requestProject({ code: opt.code, name: opt.name }),
            onClear: () => requestProject(null),
            resetConfirm: pendingProject
              ? {
                  question: pendingProject.next
                    ? '프로젝트를 변경하면 작성 중인 발주단위가 초기화됩니다'
                    : '프로젝트를 해제하면 작성 중인 발주단위가 초기화됩니다',
                  onConfirm: () => applyProject(pendingProject.next),
                  onCancel: () => setPendingProject(null),
                }
              : null,
          }}
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
            units={plan.units}
            totals={plan.totals}
            payload={payload}
            onEdit={() => setConfirmed(false)}
          />
        ) : reviewing && payload ? (
          <PlanReviewView
            payload={payload}
            totals={plan.totals}
            onBack={() => setReviewing(false)}
            onProceed={() => {
              setConfirmed(true);
              setReviewing(false);
            }}
          />
        ) : (
          <>
            <ModulePoolTable
              bom={DEMO_BOM}
              assigned={plan.assigned}
              selected={plan.selected}
              onToggle={plan.toggle}
              onToggleAll={plan.toggleAll}
              onGroup={plan.groupSelected}
              unitCount={plan.totals.units}
            />

            <section className="flex flex-col gap-4">
              <SimSectionHeader
                title="발주단위 — 구매사유·납기·거래처 지정"
                prompt="발주단위마다 구매사유와 납기예정일을 입력하고, 가공품·판금품 그룹에 실거래처를 지정하세요. 그룹별 납기·비고는 필요할 때만 덮어씁니다."
              />
              {plan.units.length === 0 ? (
                <EmptyState
                  icon={<RiStackLine size={18} aria-hidden />}
                  title="발주단위가 없습니다"
                  description="위 모듈 풀에서 모듈을 선택해 발주단위로 묶으세요."
                  compact
                />
              ) : (
                plan.units.map((u) => (
                  <OrderUnitCard
                    key={u.id}
                    bom={DEMO_BOM}
                    unit={u}
                    onPatch={(patch) => plan.patchUnit(u.id, patch)}
                    onVendorPatch={(vendorClass, patch) =>
                      plan.patchVendor(u.id, vendorClass, patch)
                    }
                    onRemoveModule={(code) => plan.removeModule(u.id, code)}
                    onRemove={() => plan.removeUnit(u.id)}
                  />
                ))
              )}
            </section>

            <PlanFooter
              bom={DEMO_BOM}
              totals={plan.totals}
              assignedModules={plan.assigned.size}
              gate={plan.gate}
              onConfirm={() => setReviewing(true)}
            />
          </>
        )}
      </div>
    </SectionCard>
  );
}
