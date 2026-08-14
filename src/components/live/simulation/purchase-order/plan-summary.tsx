'use client';

import { useMemo, useState } from 'react';
import {
  RiArrowDownSLine,
  RiArrowLeftLine,
  RiArrowRightSLine,
  RiCheckboxCircleLine,
  RiFileList3Line,
  RiPencilLine,
} from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { InlineConfirm } from '@/components/ui/inline-confirm';
import { Spinner } from '@/components/ui/spinner';
import { StatusPill } from '@/components/ui/status-pill';
import { CatalogCombobox, type ComboOption } from '@/components/live/pre-run/catalog-combobox';
import { cn } from '@/lib/utils';
import { formatInteger } from '@/lib/data/format';
import type { PlanSubmit } from '@/lib/live/types';
import { projectFavoritesOf, searchProjects } from './catalog';
import type { OrderUnit, PlanBom, PlanGate, PlanTotals } from './model';
import { Td, Th } from './ui';

/**
 * A(헤더 컨텍스트·자동 단계)와 D(하단 요약·확정)를 한 파일에 둔다 — 둘 다 계획 상태를
 * 둘러싼 요약 표면이라 재료가 같다.
 *
 * ⚠ 종전 헤더의 요약 스탯 5개(모듈·부품·총 요청금액·발주단위·미배정)는 2026-08-14 사용자
 *   요청으로 **모듈 풀 하단 선택 바**(module-pool-table)로 옮겼다 — 선택 요약 옆에서 같은
 *   글자 크기로 읽는 편이 시선 이동이 짧다.
 */

// ── A. 헤더 — 프로젝트 컨텍스트 + 자동 실행 단계 ─────────────────────────────

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

interface PlanHeaderProps {
  /** 주입된 BOM 컨텍스트(데모 픽스처 또는 hitl.plannerBom) — 칩·전체 합계의 원천. */
  bom: PlanBom;
  /** 선택된 프로젝트 — null 이면 미선택(호출부가 본문 대신 empty-state 를 그린다). */
  project: { code: string; name: string } | null;
  /**
   * 프로젝트 선택 UI(데모 전용) — 있으면 콤보박스+초기화 확인 바를 그린다. 라이브 개입은
   * 개입 1(search)이 프로젝트를 이미 확정했으므로 미전달 — 프로젝트명을 표시만 한다.
   */
  picker?: {
    onSelect: (opt: ComboOption) => void;
    onClear: () => void;
    /** 프로젝트 변경/해제 확인 바 — 작성 중 발주단위가 있을 때만 값이 온다(초기화 경고). */
    resetConfirm: { question: string; onConfirm: () => void; onCancel: () => void } | null;
  };
  /**
   * 자동 실행 단계 스트립·고정 설정 칩 표시(기본 true — 데모). 라이브 개입에선 워크플로우
   * 탭·실행 파라미터가 같은 정보를 대신하므로 끈다.
   */
  showFlowSteps?: boolean;
}

export function PlanHeader({ bom, project, picker, showFlowSteps = true }: PlanHeaderProps) {
  const projectFavorites = useMemo(() => projectFavoritesOf(bom), [bom]);
  const machine = bom.machines[0];
  return (
    <div className="flex flex-col gap-3">
      {/* 프로젝트 선택(데모) 또는 확정 프로젝트 표시(라이브) + 컨텍스트 칩. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        {picker ? (
          <span className="w-72 max-w-full min-w-0">
            <CatalogCombobox
              value={project ?? { code: '', name: '' }}
              placeholder="프로젝트 선택"
              favorites={projectFavorites}
              search={(q) => Promise.resolve(searchProjects(projectFavorites, q))}
              onSelect={picker.onSelect}
              onClear={picker.onClear}
            />
          </span>
        ) : project ? (
          <span className="text-foreground text-[length:var(--text-body)] font-semibold">
            {project.name}
          </span>
        ) : null}
        {picker?.resetConfirm ? (
          <InlineConfirm
            question={picker.resetConfirm.question}
            confirmLabel="초기화"
            onConfirm={picker.resetConfirm.onConfirm}
            onCancel={picker.resetConfirm.onCancel}
          />
        ) : project ? (
          <>
            <ContextChip>{project.code}</ContextChip>
            {/* WBS 는 주입 BOM 이 프로젝트 1건 단위라 BOM 값을 그대로 보인다. */}
            <ContextChip>WBS {bom.project.wbs}</ContextChip>
            {machine ? (
              <ContextChip>
                장비 {machine.name}
                {bom.machines.length > 1 ? ` 외 ${bom.machines.length - 1}` : ''}
              </ContextChip>
            ) : null}
            {showFlowSteps ? FIXED_CHIPS.map((c) => <ContextChip key={c}>{c}</ContextChip>) : null}
          </>
        ) : null}
      </div>

      {project ? (
        <>
          {/* 자동 실행 단계 스트립(읽기 전용) — '이 계획서' 단계만 accent. */}
          {showFlowSteps ? (
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
          ) : null}
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
  bom: PlanBom;
  totals: PlanTotals;
  assignedModules: number;
  gate: PlanGate;
  onConfirm: () => void;
  /** 제출 전송 중(라이브) — 버튼 비활성 + 스피너. 데모는 미전달(즉시 확정). */
  busy?: boolean;
}

export function PlanFooter({
  bom,
  totals,
  assignedModules,
  gate,
  onConfirm,
  busy = false,
}: PlanFooterProps) {
  const unassigned = bom.modules.length - assignedModules;
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
        {/* 확정은 2단계다(사용자 요청 2026-08-14) — 여기서 바로 제출하지 않고 전체 계획서
            검토 화면으로 넘어가, 거기서 '다음 단계로 진행'을 눌러야 제출된다. */}
        <Button size="sm" onClick={onConfirm} disabled={!gate.ready || busy}>
          {busy ? (
            <>
              <Spinner size={14} />
              전송 중…
            </>
          ) : (
            <>
              <RiFileList3Line size={14} aria-hidden />
              전체 계획서 검토
            </>
          )}
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

// ── 검토 뷰 — 전체 계획서(제출 페이로드 그대로) + 다음 단계 진행 ─────────────

interface PlanReviewViewProps {
  /** 제출될 페이로드 자체를 그린다 — '보이는 것 = 전달되는 것' 보장(buildPlanPayload 산출). */
  payload: PlanSubmit;
  totals: PlanTotals;
  onBack: () => void;
  onProceed: () => void;
  /** 제출 전송 중(라이브) — 진행 버튼 비활성 + 스피너. */
  busy?: boolean;
}

/**
 * 전체 계획서 검토(사용자 요청 2026-08-14) — 확정 직전에 작성 내용 전체를 한 번 더 보여주고,
 * [다음 단계로 진행]을 눌러야 제출된다. 편집 상태는 호출부가 들고 있으므로 [수정으로
 * 돌아가기]는 작성 내용을 그대로 보존한다. 라이브·데모가 공유한다.
 */
export function PlanReviewView({
  payload,
  totals,
  onBack,
  onProceed,
  busy = false,
}: PlanReviewViewProps) {
  return (
    <div className="flex flex-col gap-4">
      <div className="border-accent/30 bg-accent/5 flex items-start gap-2.5 rounded-[var(--radius-md)] border px-4 py-3">
        <RiFileList3Line size={17} aria-hidden className="text-accent mt-0.5 shrink-0" />
        <div className="min-w-0">
          <p className="text-foreground text-[length:var(--text-body-sm)] font-semibold">
            전체 계획서 검토 — {payload.project.name}
          </p>
          <p className="text-foreground-secondary mt-0.5 text-[11px] leading-relaxed">
            아래 내용이 그대로 다음 단계로 전달됩니다. 수정하려면 돌아가세요.
            {payload.wbs ? ` · WBS ${payload.wbs}` : ''}
          </p>
        </div>
      </div>

      {payload.units.map((u) => (
        <section
          key={u.seq}
          className="border-border bg-surface overflow-hidden rounded-[var(--radius-md)] border shadow-[var(--shadow-card)]"
        >
          {/* 발주단위 카드와 같은 밴드 문법 — 검토에서도 '한 발주 = 한 덩어리'로 읽힌다. */}
          <div className="bg-muted/50 border-border/70 flex flex-wrap items-center gap-2 border-b px-4 py-2.5">
            <StatusPill label={`발주 ${u.seq}`} variant="info" />
            <span className="text-foreground text-[length:var(--text-body)] font-semibold">
              {u.purchaseReason}
            </span>
            <span className="text-foreground-tertiary text-[11px] tabular-nums">
              납기예정일 {u.dueDate}
            </span>
          </div>
          <div className="flex flex-col gap-3 p-4">
            <ul className="flex flex-wrap gap-1.5">
              {u.modules.map((m) => (
                <li
                  key={m.itemCode}
                  className="border-border bg-muted/40 text-foreground-secondary inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px]"
                >
                  {m.name}
                  {m.spec ? <span className="text-foreground-tertiary">&nbsp;· {m.spec}</span> : null}
                </li>
              ))}
            </ul>
            <div className="border-border overflow-x-auto rounded-[var(--radius-md)] border">
              <table className="w-full min-w-[640px] border-collapse text-[11px]">
                <thead className="bg-muted/70 text-foreground-tertiary">
                  <tr>
                    <Th>거래처</Th>
                    <Th className="text-right">부품 수</Th>
                    <Th className="text-right">금액</Th>
                    <Th className="w-28">납기예정일</Th>
                    <Th>비고</Th>
                  </tr>
                </thead>
                <tbody>
                  {u.vendorGroups.map((g) => (
                    <tr key={g.vendorClass} className="border-border/50 border-t align-middle">
                      <Td>
                        {g.vendor && g.vendor !== g.vendorClass ? (
                          <span className="text-foreground-secondary whitespace-nowrap">
                            {g.vendorClass} <span aria-hidden>→</span>{' '}
                            <b className="text-foreground">{g.vendor}</b>
                          </span>
                        ) : (
                          <span className="text-foreground-secondary whitespace-nowrap">
                            {g.vendor ?? g.vendorClass}
                          </span>
                        )}
                      </Td>
                      <Td className="text-foreground-secondary text-right tabular-nums">
                        {g.parts}
                      </Td>
                      <Td className="text-foreground-secondary text-right whitespace-nowrap tabular-nums">
                        {formatInteger(g.amount)}
                      </Td>
                      <Td className="text-foreground-secondary whitespace-nowrap tabular-nums">
                        {g.dueDate}
                      </Td>
                      <Td className="text-foreground-secondary">{g.note || '—'}</Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      ))}

      <div className="border-border flex flex-wrap items-center justify-between gap-3 border-t pt-3">
        <p className="text-foreground-secondary text-[length:var(--text-body-sm)]">
          발주단위 <b className="text-foreground tabular-nums">{totals.units}</b> · 거래처 그룹{' '}
          <b className="text-foreground tabular-nums">{totals.vendorGroups}</b> · 부품{' '}
          <b className="text-foreground tabular-nums">{totals.parts}</b> · 총{' '}
          <b className="text-foreground tabular-nums">{formatInteger(totals.amount)}</b>원
        </p>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="secondary" onClick={onBack} disabled={busy}>
            <RiArrowLeftLine size={14} aria-hidden />
            수정으로 돌아가기
          </Button>
          <Button size="sm" onClick={onProceed} disabled={busy}>
            {busy ? (
              <>
                <Spinner size={14} />
                전송 중…
              </>
            ) : (
              <>
                <RiCheckboxCircleLine size={14} aria-hidden />
                다음 단계로 진행
              </>
            )}
          </Button>
        </div>
      </div>
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
