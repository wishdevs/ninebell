'use client';

import { useState } from 'react';
import {
  RiArrowDownSLine,
  RiArrowRightSLine,
  RiCheckboxCircleLine,
  RiPencilLine,
} from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { InlineConfirm } from '@/components/ui/inline-confirm';
import { CatalogCombobox, type ComboOption } from '@/components/live/pre-run/catalog-combobox';
import { cn } from '@/lib/utils';
import { formatInteger } from '@/lib/data/format';
import { PROJECT_FAVORITES, searchProjects } from './catalog';
import { BOM, MACHINE, MODULES, type OrderUnit, type PlanGate, type PlanTotals } from './model';
import { StatTile } from './ui';

/**
 * A(헤더 컨텍스트·자동 단계·스탯)와 D(하단 요약·확정)를 한 파일에 둔다 — 둘 다
 * 파생 합계(PlanTotals)를 그리는 요약 표면이라 재료가 같다.
 */

// ── A. 헤더 — 프로젝트 컨텍스트 + 자동 실행 단계 + 요약 스탯 ─────────────────

/**
 * 옴니솔 구매발주 4단계 — ①③ 은 에이전트가 자동 고정으로 처리하고, ②④ 의 입력을
 * 이 계획서가 대체한다. planner=true 단계를 accent 로 구분한다.
 */
const FLOW_STEPS: readonly { label: string; planner: boolean }[] = [
  { label: 'BOM 조회·이동요청 일괄 저장', planner: false },
  { label: '발주단위별 구매요청 저장', planner: true },
  { label: '구매요청처리 셀프결재', planner: false },
  { label: '구매발주일괄입력 거래처·납기·비고 적용', planner: true },
];

const STEP_MARKS = ['①', '②', '③', '④'] as const;

/** 고정 설정 칩 — 에이전트가 자동으로 채우는 값이라 계획서에선 읽기 전용이다. */
const FIXED_CHIPS: readonly string[] = [
  '구매그룹/구매조직 나인벨',
  '이동출고 공용자재 → 이동입고 프로젝트',
];

// 픽스처 전체 합계 — 정적이라 렌더마다 다시 계산하지 않는다.
const TOTAL_PARTS = MODULES.reduce((s, m) => s + m.parts.length, 0);
const TOTAL_AMOUNT = MODULES.reduce((s, m) => s + m.parts.reduce((a, p) => a + p.amount, 0), 0);

interface PlanHeaderProps {
  /** 선택된 프로젝트 — null 이면 미선택(호출부가 본문 대신 empty-state 를 그린다). */
  project: { code: string; name: string } | null;
  onProjectSelect: (opt: ComboOption) => void;
  onProjectClear: () => void;
  /** 프로젝트 변경/해제 확인 바 — 작성 중 발주단위가 있을 때만 값이 온다(초기화 경고). */
  resetConfirm: { question: string; onConfirm: () => void; onCancel: () => void } | null;
  totals: PlanTotals;
  /** 발주단위에 배정된 모듈 수(파생) — 미배정 스탯 계산용. */
  assignedModules: number;
}

export function PlanHeader({
  project,
  onProjectSelect,
  onProjectClear,
  resetConfirm,
  totals,
  assignedModules,
}: PlanHeaderProps) {
  const unassignedModules = MODULES.length - assignedModules;
  return (
    <div className="flex flex-col gap-3">
      {/* 프로젝트 선택(사용자 지정) + 컨텍스트 칩 — 데모 카탈로그는 픽스처 프로젝트 1건. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="w-72 max-w-full min-w-0">
          <CatalogCombobox
            value={project ?? { code: '', name: '' }}
            placeholder="프로젝트 선택"
            favorites={[...PROJECT_FAVORITES]}
            search={(q) => Promise.resolve(searchProjects(q))}
            onSelect={onProjectSelect}
            onClear={onProjectClear}
          />
        </span>
        {resetConfirm ? (
          <InlineConfirm
            question={resetConfirm.question}
            confirmLabel="초기화"
            onConfirm={resetConfirm.onConfirm}
            onCancel={resetConfirm.onCancel}
          />
        ) : project ? (
          <>
            <ContextChip>{project.code}</ContextChip>
            {/* WBS 는 데모 픽스처가 프로젝트 1건뿐이라 BOM 값을 그대로 보인다. */}
            <ContextChip>WBS {BOM.project.wbs}</ContextChip>
            <ContextChip>장비 {MACHINE.name}</ContextChip>
            {FIXED_CHIPS.map((c) => (
              <ContextChip key={c}>{c}</ContextChip>
            ))}
          </>
        ) : null}
      </div>

      {project ? (
        <>
          {/* 자동 실행 단계 스트립(읽기 전용) — '이 계획서' 단계만 accent. */}
          <ol className="flex flex-wrap items-center gap-1.5 text-[11px]">
            {FLOW_STEPS.map((s, i) => (
              <li key={s.label} className="flex items-center gap-1.5">
                {i > 0 ? (
                  <span aria-hidden className="text-foreground-tertiary">
                    →
                  </span>
                ) : null}
                <span
                  className={cn(
                    'rounded-full px-2 py-0.5 whitespace-nowrap',
                    s.planner
                      ? 'bg-accent/10 text-accent font-semibold'
                      : 'bg-muted/60 text-foreground-secondary',
                  )}
                >
                  {STEP_MARKS[i]} {s.label}
                  <span className={s.planner ? undefined : 'text-foreground-tertiary'}>
                    {s.planner ? ' · 이 계획서' : ' · 자동'}
                  </span>
                </span>
              </li>
            ))}
          </ol>

          {/* 요약 스탯 — 발주단위·미배정은 계획 진행에 따라 라이브 갱신. */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            <StatTile label="모듈" value={`${MODULES.length}`} />
            <StatTile label="부품" value={`${TOTAL_PARTS}`} />
            <StatTile label="총 요청금액" value={`${formatInteger(TOTAL_AMOUNT)}원`} />
            <StatTile label="발주단위" value={`${totals.units}`} />
            <StatTile
              label="미배정 모듈"
              value={`${unassignedModules}`}
              tone={unassignedModules > 0 ? 'warning' : 'success'}
            />
          </div>
        </>
      ) : null}
    </div>
  );
}

function ContextChip({ children }: { children: React.ReactNode }) {
  return (
    <span className="border-border bg-muted/40 text-foreground-secondary rounded-full border px-2 py-0.5 text-[11px] whitespace-nowrap">
      {children}
    </span>
  );
}

// ── D. 하단 요약 + 확정 ──────────────────────────────────────────────────────

interface PlanFooterProps {
  totals: PlanTotals;
  assignedModules: number;
  gate: PlanGate;
  onConfirm: () => void;
}

export function PlanFooter({ totals, assignedModules, gate, onConfirm }: PlanFooterProps) {
  const unassigned = MODULES.length - assignedModules;
  return (
    <div className="border-border flex flex-col gap-2 border-t pt-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-foreground-secondary text-[length:var(--text-body-sm)]">
          발주단위 <b className="text-foreground tabular-nums">{totals.units}</b> · 거래처 그룹{' '}
          <b className="text-foreground tabular-nums">{totals.vendorGroups}</b>
          {totals.unassignedVendors > 0 ? (
            <span className="text-warning"> (미지정 {totals.unassignedVendors})</span>
          ) : null}{' '}
          · 부품 <b className="text-foreground tabular-nums">{totals.parts}</b> · 총{' '}
          <b className="text-foreground tabular-nums">{formatInteger(totals.amount)}</b>원
          {unassigned > 0 ? (
            <span className="text-foreground-tertiary">
              {' '}
              · 미배정 모듈 {unassigned}개 남음(확정 가능)
            </span>
          ) : null}
        </p>
        <Button size="sm" onClick={onConfirm} disabled={!gate.ready}>
          <RiCheckboxCircleLine size={14} aria-hidden />
          계획 확정
        </Button>
      </div>
      {/* 미충족 항목 힌트 — 버튼이 왜 비활성인지 그 자리에서 알려준다. */}
      {!gate.ready ? (
        <ul className="text-warning flex flex-col gap-0.5 text-[11px]">
          {gate.hints.map((h) => (
            <li key={h}>· {h}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

// ── 확정 뷰 — 배너 + 발주단위 요약 + 실행 페이로드 미리보기 ──────────────────

interface ConfirmedViewProps {
  units: readonly OrderUnit[];
  totals: PlanTotals;
  payload: object;
  onEdit: () => void;
}

export function ConfirmedView({ units, totals, payload, onEdit }: ConfirmedViewProps) {
  const [openPayload, setOpenPayload] = useState(false);
  return (
    <div className="flex flex-col gap-3">
      <div className="border-success/30 bg-success/10 flex items-start gap-2.5 rounded-[var(--radius-md)] border px-4 py-3">
        <RiCheckboxCircleLine size={18} aria-hidden className="text-success mt-0.5 shrink-0" />
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <p className="text-success text-[length:var(--text-body-sm)] font-semibold">
            발주 계획이 확정되었습니다 — 발주단위 {totals.units}건 · 총{' '}
            {formatInteger(totals.amount)}원
          </p>
          <p className="text-foreground-secondary text-[length:var(--text-body-sm)] leading-relaxed">
            백엔드 연동 예정 — 확정된 계획은 에이전트 실행 파라미터로 전달됩니다. 지금은 저장·실행
            없이 계획서만 확정합니다.
          </p>
        </div>
        <Button size="sm" variant="secondary" className="shrink-0" onClick={onEdit}>
          <RiPencilLine size={14} aria-hidden />
          계획 수정
        </Button>
      </div>

      {/* 발주단위 한 줄 요약 — 페이로드를 펼치지 않아도 결과를 훑을 수 있게. */}
      <ul className="flex flex-col gap-1">
        {units.map((u) => (
          <li key={u.id} className="text-foreground-secondary text-[length:var(--text-body-sm)]">
            <b className="text-foreground">발주 {u.seq}</b> — {u.purchaseReason} · 납기 {u.dueDate}{' '}
            · 모듈 {u.moduleCodes.length}개
          </li>
        ))}
      </ul>

      {/* 실행 페이로드 미리보기(접이식) — 백엔드 연동 시 이 JSON 이 그래프 params 가 된다. */}
      <div className="border-border rounded-[var(--radius-md)] border">
        <button
          type="button"
          aria-expanded={openPayload}
          onClick={() => setOpenPayload((v) => !v)}
          className="text-foreground-secondary hover:text-foreground flex w-full items-center gap-1.5 px-3 py-2 text-left text-[length:var(--text-body-sm)] font-medium"
        >
          {openPayload ? (
            <RiArrowDownSLine size={15} aria-hidden />
          ) : (
            <RiArrowRightSLine size={15} aria-hidden />
          )}
          에이전트 실행 페이로드 미리보기
        </button>
        {openPayload ? (
          <pre className="border-border bg-muted/30 text-foreground-secondary max-h-80 overflow-auto border-t p-3 font-mono text-[11px] leading-relaxed">
            {JSON.stringify(payload, null, 2)}
          </pre>
        ) : null}
      </div>
    </div>
  );
}
