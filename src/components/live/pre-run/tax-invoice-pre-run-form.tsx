'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { RiInformationLine, RiPlayLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { DatePicker } from '@/components/ui/date-picker';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { SectionCard } from '@/components/ui/section-card';
import { fetchCatalog, fetchFavorites } from '@/lib/api/me-codes';
import { CatalogCombobox, projectCodeLabel, type ComboOption } from './catalog-combobox';
import type { PreRunFormProps } from './index';
import {
  API_ISSUE,
  API_NONDEDUCT,
  formatWon,
  issueFromApi,
  nondeductFromApi,
  parseAmount,
  taxFromApi,
} from './tax-invoice/model';
import { answersComplete, defaultAnswers, type QuestionAnswers } from './tax-invoice/question-flow';
import { QuestionsSection } from './tax-invoice/questions-section';
import { AmountInput } from './tax-invoice/ui';

/**
 * 세금계산서 실행 전 폼 — 증빙유형을 정하는 질문과, 발행 전 건의 입력항목을 받는다.
 *
 * 백엔드 계약: `params["tax_invoice"]` — 증빙유형 코드는 서버가
 * evidence_for(issue, split, tax, nondeduct_reason) 로 도출한다(프론트 evidenceFor 와 동일 매핑).
 *
 * **발행 전/후로 폼이 받는 범위가 다르다**(사용자 재확정 2026-08-20, PROCESS.md D1):
 * - 발행 **전**(22/23/24): 단건이라 실행 전에 전량 확정할 수 있다 — 거래처·공급가액·예산단위·
 *   프로젝트·적요·회계일까지 여기서 받고 무개입 완주한다.
 * - 발행 **후**(03~07·11/13): 조회 결과가 복수일 수 있어 **행 선택과 행별 입력을 실행 전에
 *   정할 수 없다**. 여기서는 질문(증빙유형)+조회기간까지만 받고, 계산서 행 선택·행별
 *   예산단위·프로젝트·적요와 비용분할 계획은 라이브 개입 그리드(InvoiceGridCard)가 받는다.
 *
 * 시뮬레이션 대비 입력항목 변화(ERP 실측 2026-08-19, PROCESS.md):
 * - 자금과목·결제조건·자금예정일 **제거** — 저장 비필수 + 결제방법은 ERP 자동 기본값이고,
 *   시뮬레이션의 '당월결제' 기본값은 이 환경에 없는 값이었다.
 * - 회계일은 발행 전만 입력(발행 후는 선택 행 마지막 계산서일 자동).
 */

/** 카탈로그 검색 요청 건수(프로젝트는 WBS 행 단위라 넉넉히). */
const SEARCH_LIMIT = 40;

/** 프로젝트 카탈로그 code('PJT_NO|WBS_NO' 합성) → 제출용 WBS. 합성이 아니면 그대로. */
function wbsOf(code: string): string {
  const parts = code.split('|');
  return parts.length > 1 && parts[1] ? parts[1] : code;
}

function asString(v: unknown): string {
  return typeof v === 'string' ? v : '';
}

function asIsoDate(v: unknown): string {
  return typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : '';
}

/** 로컬 오늘(yyyy-mm-dd) — 발행 전 회계일 기본값. */
function todayLocal(): string {
  const d = new Date();
  const off = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - off).toISOString().slice(0, 10);
}

interface Seed {
  answers: QuestionAnswers;
  partner: string;
  supplyAmount: string;
  budgetUnit: { code: string; name: string };
  project: { code: string; name: string };
  note: string;
  acctDate: string;
  exemptReason: string;
}

/** 마지막 제출 params → 폼 초기값 복원(종료 후 값 수정 재실행). 부모가 key 로 remount 한다. */
function seedFromParams(initial: Record<string, unknown> | undefined): Seed {
  const empty: Seed = {
    answers: defaultAnswers(),
    partner: '',
    supplyAmount: '',
    budgetUnit: { code: '', name: '' },
    project: { code: '', name: '' },
    note: '',
    acctDate: todayLocal(),
    exemptReason: '일반면세',
  };
  const p = initial?.tax_invoice as Record<string, unknown> | undefined;
  if (!p || typeof p !== 'object') return empty;

  const issue = issueFromApi(p.issue);
  const tax = taxFromApi(p.tax);
  if (!issue || !tax) return empty;
  const fallbackRange = defaultAnswers();
  const answers: QuestionAnswers = {
    issue,
    tax,
    nondeduct: nondeductFromApi(p.nondeduct_reason),
    split: issue === 'after' && p.split === true ? 'split' : 'single',
    invoiceFrom: issue === 'after' ? asIsoDate(p.period_from) || fallbackRange.invoiceFrom : '',
    invoiceTo: issue === 'after' ? asIsoDate(p.period_to) || fallbackRange.invoiceTo : '',
  };

  const budgetName = asString(p.budget_unit_name);
  const projectWbs = asString(p.project_wbs);

  return {
    answers,
    partner: asString(p.partner_name),
    supplyAmount: typeof p.supply_amount === 'number' ? String(p.supply_amount) : '',
    // 복원은 이름만 남는다(카탈로그 code 미보존) — code 에 같은 값을 넣어 표시를 살린다.
    budgetUnit: budgetName ? { code: budgetName, name: budgetName } : empty.budgetUnit,
    project: projectWbs ? { code: projectWbs, name: '' } : empty.project,
    note: asString(p.note),
    acctDate: asIsoDate(p.actg_date) || empty.acctDate,
    exemptReason: asString(p.exempt_reason) || empty.exemptReason,
  };
}

export function TaxInvoicePreRunForm({ agent, disabled, initialParams, onStart }: PreRunFormProps) {
  const seed = useMemo(() => seedFromParams(initialParams), [initialParams]);
  const [answers, setAnswers] = useState<QuestionAnswers>(seed.answers);
  const [partner, setPartner] = useState(seed.partner);
  const [supplyAmount, setSupplyAmount] = useState(seed.supplyAmount);
  const [budgetUnit, setBudgetUnit] = useState(seed.budgetUnit);
  const [project, setProject] = useState(seed.project);
  const [note, setNote] = useState(seed.note);
  const [acctDate, setAcctDate] = useState(seed.acctDate);
  const [exemptReason, setExemptReason] = useState(seed.exemptReason);

  const isBefore = answers.issue === 'before';
  const isAfter = answers.issue === 'after';
  const isSplit = isAfter && answers.split === 'split';

  // ── 카탈로그(예산단위·프로젝트) — 자주쓰는 1회 로드 + ERP 검색 ────────────
  const [budgetFavs, setBudgetFavs] = useState<ComboOption[]>([]);
  const [projectFavs, setProjectFavs] = useState<ComboOption[]>([]);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const favs = await fetchFavorites('budget_unit');
        if (alive) {
          setBudgetFavs(
            favs.map((f) => ({
              code: f.code,
              name: f.name,
              sub: f.extra?.bgacctNm ?? f.extra?.deptNm ?? undefined,
              isDefault: f.isDefault,
            })),
          );
        }
      } catch {
        /* 백엔드 미배포 — 검색만 사용 */
      }
      try {
        const favs = await fetchFavorites('project');
        if (alive) {
          setProjectFavs(
            favs.map((f) => ({
              code: f.code,
              name: f.name,
              codeLabel: projectCodeLabel(f.code, f.extra?.pjtNo ?? undefined),
              sub: f.extra?.wbsNm ?? f.extra?.wbsNo ?? undefined,
              isDefault: f.isDefault,
            })),
          );
        }
      } catch {
        /* 무시 */
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const searchBudget = useCallback(async (q: string): Promise<ComboOption[]> => {
    const page = await fetchCatalog({ kind: 'budget_unit', q, dept: 'all', limit: SEARCH_LIMIT });
    return page.items.map((c) => ({
      code: c.code,
      name: c.name,
      sub: c.extra?.bgacctNm ?? c.extra?.deptNm ?? undefined,
    }));
  }, []);

  const searchProjects = useCallback(async (q: string): Promise<ComboOption[]> => {
    const page = await fetchCatalog({ kind: 'project', q, dept: 'all', limit: SEARCH_LIMIT });
    return page.items.map((c) => ({
      code: c.code,
      name: c.name,
      codeLabel: projectCodeLabel(c.code, c.extra?.pjtNo ?? undefined),
      sub: c.extra?.wbsNm ?? c.extra?.wbsNo ?? undefined,
    }));
  }, []);

  // ── 검증 — 비활성 사유는 인라인 텍스트로(모바일 컨트랙트: title 금지) ──────
  const parsedSupply = parseAmount(supplyAmount);
  const questionsOk = answersComplete(answers);
  // 입력항목은 **발행 전 경로에만** 있다 — 발행 후는 행마다 값이 달라 개입 그리드가 받는다.
  const beforeOk =
    !isBefore ||
    (!!partner.trim() &&
      parsedSupply !== null &&
      parsedSupply !== 0 &&
      !!acctDate &&
      !!budgetUnit.name &&
      !!project.code &&
      !!note.trim());
  const exemptOk = answers.tax !== 'exempt' || !!exemptReason.trim();
  const canSubmit = !disabled && questionsOk && beforeOk && exemptOk;

  const disabledReason = !questionsOk
    ? '증빙유형 질문에 모두 답하면 실행할 수 있습니다.'
    : !beforeOk
      ? '발행 전 건은 거래처명·공급가액·회계일·예산단위·프로젝트·적요를 입력해야 합니다.'
      : !exemptOk
        ? '비과세 사유구분을 입력해야 합니다.'
        : null;

  const submit = () => {
    if (!canSubmit || !answers.issue || !answers.tax) return;
    // 백엔드 계약 params["tax_invoice"] — 증빙유형 코드는 서버가 도출, 불변식은 서버가 재검증.
    onStart({
      tax_invoice: {
        issue: API_ISSUE[answers.issue],
        tax: answers.tax,
        // 발행 전 불공은 사유를 나누지 않는다(코드 24) → null 허용.
        nondeduct_reason:
          isAfter && answers.tax === 'nondeduct' && answers.nondeduct
            ? API_NONDEDUCT[answers.nondeduct]
            : null,
        split: isSplit,
        period_from: isAfter ? answers.invoiceFrom : null,
        period_to: isAfter ? answers.invoiceTo : null,
        partner_name: isBefore ? partner.trim() : null,
        supply_amount: isBefore ? parsedSupply : null,
        // 발행 후 항목은 행별로 달라 개입 그리드가 받는다(HITL rows) — 폼에서는 비운다.
        budget_unit_name: isBefore ? budgetUnit.name : null,
        project_wbs: isBefore ? wbsOf(project.code) : null,
        note: isBefore ? note.trim() : null,
        actg_date: isBefore ? acctDate : null,
        exempt_reason: answers.tax === 'exempt' ? exemptReason.trim() : null,
        // 분할 계획도 개입에서 받는다(HITL splitPlan) — 여기서는 분할 여부(split)만 넘긴다.
        split_rows: null,
      },
    });
  };

  return (
    <SectionCard
      caption="실행 전 입력"
      title={`${agent.name} 결의서`}
      description="발행 전/후·비용분할·과세여부를 답하면 증빙유형이 정해집니다. 입력항목을 채워 실행하면 옴니솔에서 결의서를 만들어 저장합니다."
      density="comfortable"
    >
      <div className="border-border/60 bg-muted/30 flex gap-2 rounded-[var(--radius-md)] border p-3">
        <RiInformationLine
          size={16}
          aria-hidden
          className="text-foreground-tertiary mt-0.5 shrink-0"
        />
        <p className="text-foreground-tertiary text-xs leading-relaxed">
          실행하면 결의서가 <b>실제로 저장(F7)</b>됩니다. 상신은 자동화하지 않습니다 — 저장 후
          옴니솔에서 직접 상신하세요.
          {isAfter ? (
            <>
              {' '}
              발행 후 건은 <b>계산서 행 선택과 행별 예산단위·프로젝트·적요를 실행 중 개입 화면</b>
              에서 받습니다{isSplit ? '(비용분할 계획도 개입에서 세웁니다)' : ''} — 조회 결과가 여러
              건일 수 있어 실행 전에 미리 정할 수 없기 때문입니다. 이 폼에서는 증빙유형 질문과
              조회기간까지만 지정합니다.
            </>
          ) : null}
        </p>
      </div>

      {/* 1. 증빙유형 질문 — 포털 카드 or 질문 행(무효화 규칙 포함) */}
      <QuestionsSection value={answers} onChange={setAnswers} disabled={disabled} />

      {/* 2. 입력항목 */}
      <div className="grid gap-4 sm:grid-cols-2">
        {isBefore ? (
          <>
            <FormField
              id="tax-invoice-partner"
              label="거래처명"
              required
              hint="ERP 등록 이름과 정확히 일치해야 합니다 — '(주)' 포함 여부까지 그대로."
            >
              <Input
                id="tax-invoice-partner"
                value={partner}
                disabled={disabled}
                placeholder="예: 코웨이(주)"
                onChange={(e) => setPartner(e.target.value)}
              />
            </FormField>

            <FormField
              id="tax-invoice-supply"
              label="공급가액"
              required
              hint={
                parsedSupply !== null && parsedSupply !== 0
                  ? `${formatWon(parsedSupply)}원 (세액은 ERP 가 자동 계산)`
                  : '원 단위 정수 — 취소분은 음수로 입력합니다.'
              }
            >
              <AmountInput
                ariaLabel="공급가액"
                value={supplyAmount}
                onChange={setSupplyAmount}
                disabled={disabled}
                placeholder="예: 400000"
                invalid={!!supplyAmount && (parsedSupply === null || parsedSupply === 0)}
              />
            </FormField>

            <FormField id="tax-invoice-budget" label="예산단위" required>
              <CatalogCombobox
                value={budgetUnit}
                placeholder="예산단위 선택"
                favorites={budgetFavs}
                disabled={disabled}
                search={searchBudget}
                onSelect={(o) => setBudgetUnit({ code: o.code, name: o.name })}
                onClear={() => setBudgetUnit({ code: '', name: '' })}
              />
            </FormField>

            <FormField
              id="tax-invoice-project"
              label="프로젝트"
              required
              hint="500 / 800 또는 개별 프로젝트(WBS)를 고릅니다."
            >
              <CatalogCombobox
                value={project}
                placeholder="프로젝트 선택"
                favorites={projectFavs}
                disabled={disabled}
                search={searchProjects}
                onSelect={(o) => setProject({ code: o.code, name: o.name })}
                onClear={() => setProject({ code: '', name: '' })}
              />
            </FormField>

            <FormField id="tax-invoice-note" label="적요" required>
              <Input
                id="tax-invoice-note"
                value={note}
                maxLength={200}
                disabled={disabled}
                placeholder="예: 7월 노무자문 수수료"
                onChange={(e) => setNote(e.target.value)}
              />
            </FormField>

            <FormField
              id="tax-invoice-acct-date"
              label="회계일"
              required
              hint="(세금)계산서일과 동일하게 지정하세요."
            >
              <DatePicker
                ariaLabel="회계일"
                value={acctDate}
                disabled={disabled}
                onChange={setAcctDate}
              />
            </FormField>
          </>
        ) : (
          <FormField
            id="tax-invoice-acct-date-auto"
            label="회계일"
            hint="선택한 행의 마지막 (세금)계산서일로 자동 지정됩니다."
          >
            <p className="border-border bg-muted/40 text-foreground-secondary flex h-10 items-center rounded-sm border px-3 text-sm">
              자동 — 선택 행 마지막 계산서일
            </p>
          </FormField>
        )}

        {answers.tax === 'exempt' ? (
          <FormField
            id="tax-invoice-exempt-reason"
            label="사유구분"
            required
            hint="비과세 사유구분 — 기본값 일반면세."
          >
            <Input
              id="tax-invoice-exempt-reason"
              value={exemptReason}
              disabled={disabled}
              placeholder="예: 일반면세"
              onChange={(e) => setExemptReason(e.target.value)}
            />
          </FormField>
        ) : null}
      </div>

      {/* 3. 발행 후 — 개입에서 받을 것을 미리 알린다(폼에 빈칸이 없는 이유). */}
      {isAfter ? (
        <div className="border-border/60 bg-muted/20 rounded-[var(--radius-md)] border px-3 py-2.5">
          <p className="text-foreground text-[length:var(--text-body-sm)] font-semibold">
            실행 중 개입 화면에서 받는 것
          </p>
          <ul className="text-foreground-secondary mt-1 list-disc space-y-0.5 pl-4 text-xs leading-relaxed">
            <li>조회기간의 계산서 목록에서 결의서에 넣을 행 선택(복수 가능)</li>
            <li>선택한 행마다 예산단위 · 프로젝트 · 적요(일괄 지정 가능)</li>
            {isSplit ? <li>선택한 계산서 1건의 비용분할 계획(행별 금액·비용센터·적요)</li> : null}
          </ul>
        </div>
      ) : null}

      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-end md:gap-3">
        {/* 비활성 사유 — disabled:pointer-events-none 라 title 툴팁은 안 뜨므로 인라인으로 안내. */}
        {disabledReason && !disabled ? (
          <p className="text-foreground-tertiary text-xs md:text-right">{disabledReason}</p>
        ) : null}
        <Button
          type="button"
          onClick={submit}
          disabled={!canSubmit}
          className="max-md:h-11 max-md:w-full"
        >
          <RiPlayLine size={15} aria-hidden />
          실행
        </Button>
      </div>
    </SectionCard>
  );
}
