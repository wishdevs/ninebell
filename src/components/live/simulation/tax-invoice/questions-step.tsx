'use client';

import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react';
import {
  RiArrowLeftLine,
  RiArrowRightLine,
  RiCheckboxCircleLine,
  RiPencilLine,
} from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { DatePicker } from '@/components/ui/date-picker';
import { cn } from '@/lib/utils';
import { ChoiceOption, SimStepHeader } from './ui';
import {
  answerText,
  answersComplete,
  emptyAnswers,
  initialStep,
  isAnswered,
  questionPath,
  QUESTION_SHORT,
  QUESTION_TITLE,
  stepAfter,
  stepBefore,
  type QuestionAnswers,
  type QuestionKey,
  type WizardStep,
} from './question-flow';
import {
  defaultInvoiceRange,
  evidenceFor,
  RANGE_PRESETS,
  INVOICE_DATE_MAX,
  INVOICE_DATE_MIN,
  ISSUE_LABEL,
  NONDEDUCT_LABEL,
  SPLIT_LABEL,
  TAX_LABEL,
  type IssueState,
  type NondeductReason,
  type SplitChoice,
  type TaxKind,
} from './model';

// 답 타입·완료 판정은 question-flow.ts 로 옮겼지만 뒤 단계들이 이 경로로 import 하므로 그대로 내보낸다.
export { emptyAnswers, answersComplete };
export type { QuestionAnswers };

interface QuestionsStepProps {
  value: QuestionAnswers;
  onChange: (next: QuestionAnswers) => void;
  onNext: () => void;
}

/**
 * 1단계 — "한 번에 한 질문" 위저드.
 *
 * 예전에는 답할수록 질문 블록이 아래로 쌓여(점진적 노출) 좁은 패널에 스크롤이 생겼다.
 * 지금은 **현재 질문 하나만** 오른쪽에 띄우고, 이미 고른 답은 왼쪽 요약 레일에 접어 둔다.
 * 이 패널은 라이브 화면이 없어 가로는 넓고(≈900px) 세로는 짧다(≈390px) — 그래서 세로를
 * 한 줄도 쓰지 않는 **왼쪽 레일**을 골랐다(위쪽 요약은 질문 자리를 그만큼 빼앗는다).
 *
 * 진행: 선택지를 고르면 곧바로 다음 질문으로 넘어간다(클릭 한 번 절약). 대신 되돌아가기를
 * 두 갈래로 열어 둔다 — 레일의 '수정'(그 질문으로 바로 점프) + 하단 '이전'(한 칸 뒤로).
 *
 * 무효화 규칙은 예전과 같다: 발행 전/후를 바꾸면 뒤 답 전부 초기화, 분할을 켜면 불공 해제.
 */
export function QuestionsStep({ value, onChange, onNext }: QuestionsStepProps) {
  const [step, setStep] = useState<WizardStep>(() => initialStep(value));

  // 스텝이 바뀌면 새 질문 제목으로 포커스를 옮긴다 — 자동 진행으로 방금 누른 버튼이 사라지면
  // 포커스가 body 로 떨어져 키보드/스크린리더 사용자가 위치를 잃는다.
  const titleRef = useRef<HTMLParagraphElement>(null);
  const mountedRef = useRef(false);
  useEffect(() => {
    if (!mountedRef.current) {
      mountedRef.current = true; // 최초 렌더에서는 포커스를 뺏지 않는다.
      return;
    }
    titleRef.current?.focus();
  }, [step]);

  const set = (patch: Partial<QuestionAnswers>) => onChange({ ...value, ...patch });

  /** 답을 반영하고 그 질문의 **다음** 스텝으로 넘어간다(경로는 갱신된 답 기준). */
  const advance = (from: QuestionKey, next: QuestionAnswers) => {
    onChange(next);
    setStep(stepAfter(next, from));
  };

  const pickIssue = (issue: IssueState) => {
    // 같은 답을 다시 고르면 초기화 없이 진행만 한다(수정하러 왔다가 그대로 두는 경우).
    if (value.issue === issue) {
      setStep(stepAfter(value, 'issue'));
      return;
    }
    // 경로가 바뀌면 뒤 질문은 무효 — 전부 비운다(발행 전은 기간 자체가 없다).
    // 발행 전은 **비용분할이 불가**(사용자 확정 2026-08-03)라 split 을 'single' 로 고정한다
    // — 질문을 숨기기만 하고 null 로 두면 뒤 단계가 '미답' 으로 막힌다.
    // 발행 후는 기간을 **한 달 전~오늘**로 미리 채운다 — 필요하면 달력이나 빠른 선택으로 바꾼다.
    const range = issue === 'after' ? defaultInvoiceRange() : { from: '', to: '' };
    advance('issue', {
      ...emptyAnswers(),
      issue,
      split: issue === 'before' ? 'single' : null,
      invoiceFrom: range.from,
      invoiceTo: range.to,
    });
  };

  const pickSplit = (split: SplitChoice) => {
    // 분할을 켜면 불공 조합은 성립하지 않는다 → 과세여부를 해제해 다시 고르게 한다.
    const invalidates = split === 'split' && value.tax === 'nondeduct';
    advance('split', { ...value, split, ...(invalidates ? { tax: null, nondeduct: null } : {}) });
  };

  const pickTax = (tax: TaxKind) => {
    advance('tax', { ...value, tax, nondeduct: tax === 'nondeduct' ? value.nondeduct : null });
  };

  const pickNondeduct = (nondeduct: NondeductReason) => {
    advance('nondeduct', { ...value, nondeduct });
  };

  // 과세여부 선택지 — 분할이면 불공을 목록에서 제외한다(불공은 분할할 수 없다 — 미노출).
  const taxOptions: TaxKind[] =
    value.split === 'split' ? ['taxable', 'exempt'] : ['taxable', 'exempt', 'nondeduct'];

  const path = questionPath(value);
  const prevKey = stepBefore(value, step);
  const stepAnswered = step !== 'done' && isAnswered(value, step);
  const rangeInvalid =
    !!value.invoiceFrom && !!value.invoiceTo && value.invoiceFrom > value.invoiceTo;
  const complete = answersComplete(value);
  const ctaLabel = value.issue === 'after' ? '리스트 보기' : '입력항목 채우기';

  // 요약 레일에 세울 줄 — **답이 있는** 질문만. 아직 안 고른 질문은 '—' 로 자리만 차지하므로
  // 넣지 않는다(경로 전체는 상단 안내가 이미 보여준다).
  const railKeys = path.filter((k) => isAnswered(value, k));

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {/* 상단 — 이 에이전트가 무엇을 묻고 어디로 가는지 + 지금 몇 번째 질문인지. */}
      <SimStepHeader
        title="세금계산서 결의서 — 어떤 건인가요?"
        prompt={
          <>
            <span className="block">
              한 번에 한 질문씩 묻습니다. 답이 모이면 증빙유형이 정해지고{' '}
              {value.issue === 'before' ? '입력항목' : '리스트'} 화면으로 넘어갑니다.
            </span>
            <PathStrip answers={value} step={step} path={path} />
          </>
        }
      />

      <div className="flex min-h-0 flex-1 flex-col gap-3 md:flex-row md:gap-4">
        {/* 왼쪽 — 지금까지 고른 답. 각 줄의 '수정'은 그 질문으로 바로 되돌아간다. */}
        <aside
          aria-label="지금까지 고른 답"
          className="border-border-subtle flex shrink-0 flex-col gap-1 overflow-y-auto border-b pb-2 md:w-[212px] md:border-r md:border-b-0 md:pr-3 md:pb-0"
        >
          <p className="text-foreground-tertiary text-[10px] font-semibold tracking-wider uppercase">
            고른 답
          </p>
          {railKeys.length === 0 ? (
            <p className="text-foreground-tertiary text-[11px] leading-relaxed">
              아직 없습니다 — 오른쪽 질문에 답하면 여기에 쌓입니다.
            </p>
          ) : (
            <ul className="flex flex-col gap-0.5">
              {railKeys.map((k) => (
                <AnswerRow
                  key={k}
                  answers={value}
                  question={k}
                  current={step === k}
                  onEdit={() => setStep(k)}
                />
              ))}
            </ul>
          )}
        </aside>

        {/* 오른쪽 — 현재 질문 하나. 나머지 질문은 렌더하지 않는다(스크롤의 원인이었다). */}
        <section
          aria-labelledby="tax-q-title"
          className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-0.5"
        >
          <p
            id="tax-q-title"
            ref={titleRef}
            tabIndex={-1}
            className="text-foreground text-[length:var(--text-body-sm)] font-semibold outline-none"
          >
            {step === 'done' ? '질문이 모두 끝났습니다' : QUESTION_TITLE[step]}
          </p>

          {step === 'issue' ? (
            <OptionGrid>
              <ChoiceOption
                label={ISSUE_LABEL.before}
                description="아직 발행되지 않아 리스트가 없습니다 — 바로 입력항목을 채웁니다."
                active={value.issue === 'before'}
                onClick={() => pickIssue('before')}
              />
              <ChoiceOption
                label={ISSUE_LABEL.after}
                description="이미 발행되어 조회됩니다 — 리스트에서 처리할 항목을 고릅니다."
                active={value.issue === 'after'}
                onClick={() => pickIssue('after')}
              />
            </OptionGrid>
          ) : null}

          {step === 'period' ? (
            <>
              <p className="text-foreground-tertiary text-[11px] leading-relaxed">
                기본값은 한 달 전부터 오늘까지입니다. 선택한 기간의 (세금)계산서만 리스트에
                나타납니다 — 더미 데이터는 {INVOICE_DATE_MIN} ~ {INVOICE_DATE_MAX} 범위입니다.
              </p>
              <div className="flex flex-wrap items-center gap-2">
                {/* 날짜 칸은 폭을 묶어 둔다 — 질문 열이 넓어(≈860px) w-full 로 두면 한 줄에
                    하나씩 눕고 '~' 가 따로 떨어져 기간처럼 안 보인다. */}
                <DatePicker
                  ariaLabel="세금계산서일 시작"
                  value={value.invoiceFrom}
                  onChange={(v) => set({ invoiceFrom: v })}
                  className="w-40"
                />
                <span className="text-foreground-tertiary text-xs">~</span>
                <DatePicker
                  ariaLabel="세금계산서일 종료"
                  value={value.invoiceTo}
                  onChange={(v) => set({ invoiceTo: v })}
                  className="w-40"
                />
              </div>
              {/* 빠른 선택 — 달력을 열지 않고 흔히 쓰는 기간을 한 번에 넣는다.
                  이번 달만 1일 기준이고 나머지는 오늘 기준 롤링(사용자 확정 2026-08-04). */}
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-foreground-tertiary text-[11px]">빠른 선택</span>
                {RANGE_PRESETS.map((p) => {
                  const r = p.range();
                  const active = value.invoiceFrom === r.from && value.invoiceTo === r.to;
                  return (
                    <button
                      key={p.id}
                      type="button"
                      aria-pressed={active}
                      onClick={() => set({ invoiceFrom: r.from, invoiceTo: r.to })}
                      className={
                        active
                          ? 'border-accent bg-accent/10 text-accent rounded-[var(--radius-sm)] border px-2 py-1 text-[11px] font-semibold'
                          : 'border-border text-foreground-secondary hover:border-accent hover:text-foreground rounded-[var(--radius-sm)] border px-2 py-1 text-[11px] transition-colors'
                      }
                    >
                      {p.label}
                    </button>
                  );
                })}
              </div>
              {rangeInvalid ? (
                <p role="alert" className="text-danger text-[11px]">
                  시작일이 종료일보다 늦을 수 없습니다.
                </p>
              ) : null}
            </>
          ) : null}

          {step === 'split' ? (
            <OptionGrid>
              <ChoiceOption
                label={SPLIT_LABEL.single}
                description="한 건으로 전액 처리합니다."
                active={value.split === 'single'}
                onClick={() => pickSplit('single')}
              />
              <ChoiceOption
                label={SPLIT_LABEL.split}
                description="예산단위·프로젝트·비용센터별로 금액을 나눠 담습니다."
                active={value.split === 'split'}
                onClick={() => pickSplit('split')}
              />
            </OptionGrid>
          ) : null}

          {step === 'tax' ? (
            <OptionGrid>
              {taxOptions.map((t) => (
                <ChoiceOption
                  key={t}
                  label={TAX_LABEL[t]}
                  active={value.tax === t}
                  onClick={() => pickTax(t)}
                />
              ))}
            </OptionGrid>
          ) : null}

          {step === 'nondeduct' ? (
            <OptionGrid>
              {(Object.keys(NONDEDUCT_LABEL) as NondeductReason[]).map((r) => (
                <ChoiceOption
                  key={r}
                  label={NONDEDUCT_LABEL[r]}
                  active={value.nondeduct === r}
                  onClick={() => pickNondeduct(r)}
                />
              ))}
            </OptionGrid>
          ) : null}

          {step === 'done' ? (
            <div className="border-accent/30 bg-accent/5 flex items-start gap-2.5 rounded-[var(--radius-md)] border px-3 py-2.5">
              <RiCheckboxCircleLine size={16} aria-hidden className="text-accent mt-0.5 shrink-0" />
              <p className="text-foreground-secondary text-[11px] leading-relaxed">
                왼쪽 답과 아래 증빙유형을 확인한 뒤 <b className="text-foreground">{ctaLabel}</b>를
                누르세요. 고칠 답이 있으면 그 줄의 <b className="text-foreground">수정</b>을 누르면
                해당 질문으로 돌아갑니다.
              </p>
            </div>
          ) : null}
        </section>
      </div>

      {/* 선택되는 증빙유형 — 요약까지 가지 않아도 지금 답이 어떤 코드가 되는지 바로 보인다
          (문서 시뮬레이터 docs/tax-invoice-flow.html 과 같은 규칙). */}
      <EvidenceBar answers={value} />

      <div className="flex shrink-0 items-center justify-between gap-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => prevKey && setStep(prevKey)}
          disabled={!prevKey}
        >
          <RiArrowLeftLine size={14} aria-hidden />
          이전
        </Button>
        {step === 'done' ? (
          <Button size="sm" onClick={onNext} disabled={!complete}>
            {ctaLabel}
            <RiArrowRightLine size={14} aria-hidden />
          </Button>
        ) : (
          <Button
            size="sm"
            onClick={() => setStep(stepAfter(value, step))}
            disabled={!stepAnswered}
            title={stepAnswered ? undefined : '이 질문에 답하면 다음으로 넘어갑니다.'}
          >
            다음
            <RiArrowRightLine size={14} aria-hidden />
          </Button>
        )}
      </div>
    </div>
  );
}

/** 선택지 격자 — 패널이 가로로 넓어 2열로 접으면 세로가 절반이 된다(스크롤 억제). */
function OptionGrid({ children }: { children: ReactNode }) {
  return <div className="grid gap-2 sm:grid-cols-2">{children}</div>;
}

/**
 * 상단 진행 안내 — 이 경로의 질문 전체와 현재 위치. 경로에 따라 질문 수가 달라지므로
 * 발행 여부를 고르기 전에는 개수를 단정하지 않고 갈림을 그대로 적는다.
 * SimStepHeader 의 prompt 는 <p> 안에 들어가므로 여기서는 phrasing 요소(span)만 쓴다.
 */
function PathStrip({
  answers,
  step,
  path,
}: {
  answers: QuestionAnswers;
  step: WizardStep;
  path: readonly QuestionKey[];
}) {
  const position = step === 'done' ? path.length : path.indexOf(step) + 1;
  // 발행 여부를 고르기 전에는 총 질문 수가 정해지지 않는다 — 1/1 로 단정하면 거짓말이 된다.
  const total = answers.issue ? String(path.length) : '?';
  return (
    <span className="mt-1 flex flex-wrap items-center gap-x-1 gap-y-0.5">
      <span className="text-foreground-tertiary font-mono text-[10px] tabular-nums">
        {step === 'done' ? `${path.length}/${path.length} 완료` : `${position}/${total}`}
      </span>
      {path.map((k, i) => (
        <Fragment key={k}>
          <span aria-hidden className="text-foreground-tertiary/50 text-[10px]">
            ›
          </span>
          <span
            aria-current={step === k ? 'step' : undefined}
            className={cn(
              'rounded-full px-1.5 py-0.5 text-[10px] leading-tight',
              step === k
                ? 'bg-accent/15 text-accent font-bold'
                : isAnswered(answers, k)
                  ? 'text-foreground-secondary'
                  : 'text-foreground-tertiary/70',
            )}
          >
            {i + 1}. {QUESTION_SHORT[k]}
          </span>
        </Fragment>
      ))}
      {!answers.issue ? (
        <span className="text-foreground-tertiary/70 text-[10px]">
          … 발행 전이면 질문 2개, 발행 후면 4~5개입니다.
        </span>
      ) : null}
    </span>
  );
}

/** 요약 레일 한 줄 — 질문 이름 + 고른 값 + 그 질문으로 돌아가는 '수정'. */
function AnswerRow({
  answers,
  question,
  current,
  onEdit,
}: {
  answers: QuestionAnswers;
  question: QuestionKey;
  current: boolean;
  onEdit: () => void;
}) {
  const text = answerText(answers, question);
  const answered = isAnswered(answers, question);
  return (
    // 라벨과 '수정'을 윗줄에 나란히 두고 값은 그 아래 전폭으로 — 값이 레일 폭을 다 쓰면
    // '2026-07-04 ~ 2026-08-04' 같은 답이 두 줄로 접히지 않아 5줄이어도 세로가 남는다.
    <li
      className={cn(
        'flex flex-col rounded-[var(--radius-sm)] px-1.5 py-0.5',
        current && 'bg-accent/10 ring-accent/30 ring-1',
      )}
    >
      <span className="flex items-center justify-between gap-1">
        <span className="text-foreground-tertiary truncate text-[10px] font-semibold tracking-wider uppercase">
          {QUESTION_SHORT[question]}
          {current ? <span className="text-accent normal-case"> · 지금</span> : null}
        </span>
        {/* 지금 보고 있는 질문에는 '수정'을 두지 않는다 — 이미 그 질문 화면이다. */}
        {!current && answered ? (
          <button
            type="button"
            onClick={onEdit}
            aria-label={`${QUESTION_SHORT[question]} 수정 — 현재 답: ${text}`}
            className="text-foreground-tertiary hover:border-accent hover:text-accent focus-visible:ring-accent/40 border-border inline-flex shrink-0 items-center gap-0.5 rounded-[var(--radius-sm)] border px-1 text-[10px] transition-colors focus-visible:ring-2 focus-visible:outline-none"
          >
            <RiPencilLine size={10} aria-hidden />
            수정
          </button>
        ) : null}
      </span>
      <span
        title={text}
        className={cn(
          'line-clamp-2 block text-[11px] leading-snug font-medium',
          answered ? 'text-foreground' : 'text-foreground-tertiary',
        )}
      >
        {text}
      </span>
    </li>
  );
}

/** 하단 증빙유형 — 아직 못 정하면 무엇을 더 골라야 하는지 알린다(자리를 비우지 않는다). */
function EvidenceBar({ answers }: { answers: QuestionAnswers }) {
  const ev = evidenceFor(answers.issue, answers.split, answers.tax, answers.nondeduct);
  const pending = !answers.issue ? '발행 여부' : !answers.tax ? '과세여부' : '불공 사유';
  return (
    <div className="border-border-subtle bg-muted/40 flex shrink-0 flex-wrap items-baseline gap-x-2.5 gap-y-1 rounded-[var(--radius-md)] border px-3 py-2">
      <span className="text-foreground-tertiary text-[10px] font-semibold tracking-wider uppercase">
        증빙유형
      </span>
      {ev ? (
        <>
          <span className="text-accent font-mono text-lg leading-none font-bold tabular-nums">
            {ev.code}
          </span>
          <span className="text-foreground text-[11px] font-semibold">{ev.label}</span>
          {ev.note ? (
            <span className="text-foreground-tertiary w-full text-[11px]">{ev.note}</span>
          ) : null}
        </>
      ) : (
        <span className="text-foreground-tertiary text-[11px]">
          {pending}를 고르면 증빙유형이 정해집니다.
        </span>
      )}
    </div>
  );
}
