'use client';

import { useMemo, useState } from 'react';
import { RiErrorWarningLine, RiHand, RiStackLine } from '@remixicon/react';
import { EmptyNote } from '@/components/ui/empty-note';
import { EmptyState } from '@/components/ui/empty-state';
import type { LiveHitl, PlanSubmit } from '@/lib/live/types';
import { buildPlanPayload, createPlanBom, type PlanBom } from './simulation/purchase-order/model';
import { ModulePoolTable } from './simulation/purchase-order/module-pool-table';
import { OrderUnitCard } from './simulation/purchase-order/order-unit-card';
import { PlanFooter, PlanHeader, PlanReviewView } from './simulation/purchase-order/plan-summary';
import { SimSectionHeader } from './simulation/purchase-order/ui';
import { usePlanState } from './simulation/purchase-order/use-plan-state';

interface LivePlannerCardProps {
  hitl: LiveHitl;
  /** 계획 확정 제출 — 부모가 sendPlan(hitl.id, plan) 로 바인딩(낙관적 clearHitl 로 카드가 접힌다). */
  onSubmit: (plan: PlanSubmit) => Promise<boolean>;
  busy?: boolean;
}

/**
 * 계획서 개입(kind=planner) — 실행 중 HITL 로 도착한 BOM(hitl.plannerBom)으로 발주
 * 계획서를 작성한다. 데모(purchase-order-demo)와 **같은 조각**(모듈 풀·발주단위 카드·
 * 헤더/푸터·usePlanState)을 쓰며, 차이는 둘뿐이다 — 프로젝트는 개입 1(search)이 이미
 * 확정했으므로 헤더에 표시만 하고, [계획 확정]이 확정 뷰 대신 sendPlan 제출이다
 * (제출 후 런 로그/결과가 미리보기를 대신한다).
 *
 * 내부스크롤 금지(2026-08-13 규칙) — 전체는 페이지 스크롤로 흐르고, 자체 스크롤은
 * 목록성 영역(모듈 풀 max-h)만 갖는다. 패널 높이 해제는 live-side-panel 이 담당.
 */
export function LivePlannerCard({ hitl, onSubmit, busy = false }: LivePlannerCardProps) {
  const plannerBom = hitl.plannerBom;
  const bom = useMemo(() => (plannerBom ? createPlanBom(plannerBom) : null), [plannerBom]);

  if (!bom) {
    // 계약상 plannerBom 은 항상 실리지만, 타입상 옵셔널이라 빈 프레임에도 무너지지 않게 한다.
    return (
      <div className="flex flex-col gap-3">
        <PlannerHeader title={hitl.title} prompt={hitl.prompt} />
        <EmptyNote>계획서 BOM 데이터가 없습니다.</EmptyNote>
      </div>
    );
  }
  // key=hitl.id — 같은 개입의 프레임 재방출에는 작성 상태를 유지하고, 새 개입에만 초기화한다
  // (LiveGridCard 의 hitl.id 기준 초기화와 동일한 의도).
  return <PlannerBody key={hitl.id} bom={bom} hitl={hitl} onSubmit={onSubmit} busy={busy} />;
}

function PlannerBody({
  bom,
  hitl,
  onSubmit,
  busy,
}: {
  bom: PlanBom;
  hitl: LiveHitl;
  onSubmit: (plan: PlanSubmit) => Promise<boolean>;
  busy: boolean;
}) {
  const project = bom.project;
  const plan = usePlanState(bom, project);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 확정 2단계(사용자 요청 2026-08-14) — [전체 계획서 검토]가 이 뷰를 열고, 검토 화면의
  // [다음 단계로 진행]이 실제 제출이다. 뒤로 가면 작성 상태는 그대로다(usePlanState 유지).
  const [reviewing, setReviewing] = useState(false);

  async function submit() {
    if (sending || busy) return;
    setSending(true);
    setError(null);
    const ok = await onSubmit(buildPlanPayload(bom, project, plan.units));
    // 성공 시 낙관적 clearHitl 로 카드가 접히고 스트림(런 로그/결과)이 이어받는다.
    if (!ok) {
      setError('계획을 전달하지 못했습니다(흐름이 종료됐을 수 있음).');
      setSending(false);
    }
  }

  if (reviewing) {
    return (
      <div className="flex flex-col gap-4">
        {hitl.notice ? <PlannerNotice notice={hitl.notice} /> : null}
        <PlanReviewView
          payload={buildPlanPayload(bom, project, plan.units)}
          totals={plan.totals}
          onBack={() => setReviewing(false)}
          onProceed={() => void submit()}
          busy={sending || busy}
        />
        {error ? <span className="text-danger text-[12px]">{error}</span> : null}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* 재개입 공지 — 서버 검증이 계획을 거부한 사유(hitl.notice, LiveGridCard 와 동일 계약). */}
      {hitl.notice ? <PlannerNotice notice={hitl.notice} /> : null}

      <PlanHeader bom={bom} project={project} showFlowSteps={false} />

      <ModulePoolTable
        bom={bom}
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
              bom={bom}
              unit={u}
              onPatch={(patch) => plan.patchUnit(u.id, patch)}
              onVendorPatch={(vendorClass, patch) => plan.patchVendor(u.id, vendorClass, patch)}
              onRemoveModule={(code) => plan.removeModule(u.id, code)}
              onRemove={() => plan.removeUnit(u.id)}
            />
          ))
        )}
      </section>

      <PlanFooter
        bom={bom}
        totals={plan.totals}
        assignedModules={plan.assigned.size}
        gate={plan.gate}
        onConfirm={() => setReviewing(true)}
        busy={sending || busy}
      />

      {error ? <span className="text-danger text-[12px]">{error}</span> : null}
    </div>
  );
}

/** 재개입 공지 배너 — 검토/작성 두 화면이 공유(서버 검증 거부 사유). */
function PlannerNotice({ notice }: { notice: string }) {
  return (
    <div className="border-danger/30 bg-danger/10 text-danger flex items-start gap-2.5 rounded-[var(--radius-md)] border px-3 py-2.5">
      <RiErrorWarningLine size={16} aria-hidden className="mt-0.5 shrink-0" />
      <p className="text-[length:var(--text-body-sm)] leading-relaxed whitespace-pre-line">
        {notice}
      </p>
    </div>
  );
}

/** 개입 배너 — LiveGridCard 의 GridHeader 와 같은 warning 톤 헤더. */
function PlannerHeader({ title, prompt }: { title: string; prompt?: string }) {
  return (
    <div className="border-warning/30 bg-warning/10 flex items-start gap-2.5 rounded-[var(--radius-md)] border px-3 py-2.5">
      <RiHand size={16} aria-hidden className="text-warning mt-0.5 shrink-0" />
      <div className="min-w-0">
        <p className="text-foreground text-[length:var(--text-body-sm)] font-semibold">{title}</p>
        {prompt ? (
          <p className="text-foreground-secondary mt-0.5 text-[11px] leading-relaxed">{prompt}</p>
        ) : null}
      </div>
    </div>
  );
}
