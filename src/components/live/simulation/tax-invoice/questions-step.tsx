'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  RiArrowLeftLine,
  RiArrowRightLine,
  RiErrorWarningLine,
  RiInformationLine,
  RiPencilLine,
} from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { DatePicker } from '@/components/ui/date-picker';
import { HelpTip } from '@/components/ui/help-tip';
import { cn } from '@/lib/utils';
import { ChoiceOption, QUESTION_TEXT_CLASS } from './ui';
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
 * 두 갈래로 열어 둔다 — 레일 줄 전체 클릭(그 질문으로 바로 점프) + 하단 '이전'(한 칸 뒤로).
 *
 * 무효화 규칙은 예전과 같다: 발행 전/후를 바꾸면 뒤 답 전부 초기화, 분할을 켜면 불공 해제.
 *
 * **2026-08-04 가독성 개편** — 실측(1280×720)에서 고유 문구 103개 중 77개가 11px 이하였고
 * 정작 질문 문구가 13px 라 보조 설명과 구분되지 않았다. 세 가지를 바꾼다:
 *  1. 질문 문구를 20px/700 로 올려 **화면에서 가장 큰 글자**로 만든다(한 화면 한 결정).
 *  2. 상단 경고톤 배너의 가짜 질문("어떤 건인가요?")과 10px 질문 체인을 걷어내고,
 *     "질문 n / N + 진행 막대"만 남긴다 — 진짜 질문과 경쟁하던 문구를 없앤다.
 *  3. 프로세스 설명처럼 **답하는 데 필요 없는** 문장은 HelpTip(클릭으로 여는 토글팁)으로
 *     옮긴다. 반대로 더미 데이터 범위처럼 모르면 막히는 것은 오히려 크게 세운다.
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
      {/* 상단 — 지금 몇 번째 질문인지만. 예전의 경고톤 배너(가짜 질문 + 프로세스 설명 +
          10px 질문 체인)는 진짜 질문과 경쟁하기만 해서 걷어냈다. 프로세스 설명은 [?] 안으로. */}
      <WizardProgress answers={value} step={step} path={path} />

      <div className="flex min-h-0 flex-1 flex-col gap-3 md:flex-row md:gap-4">
        {/* 왼쪽 — 지금까지 고른 답. 줄 전체가 그 질문으로 되돌아가는 버튼이다
            (예전엔 39×17px '수정' 버튼 하나뿐이라 최소 타깃 24×24 에 미달했다). */}
        <aside
          aria-label="지금까지 고른 답"
          className="border-border-subtle flex shrink-0 flex-col gap-1 overflow-y-auto border-b pb-2 md:w-[224px] md:border-r md:border-b-0 md:pr-3 md:pb-0"
        >
          <p className="text-foreground-secondary text-[11px] font-semibold tracking-wide">
            고른 답
          </p>
          {railKeys.length === 0 ? (
            <p className="text-foreground-tertiary text-[length:var(--text-body-sm)] leading-relaxed">
              아직 없습니다 — 오른쪽 질문에 답하면 여기에 쌓입니다.
            </p>
          ) : (
            <ul className="flex flex-col gap-1">
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
          className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-0.5"
        >
          {/* 도움말 [?]는 질문 문구 **바로 뒤**에 붙인다 — 오른쪽 끝으로 밀면 위 진행줄의
              [?]와 세로로 겹쳐 보여 둘이 같은 버튼처럼 읽힌다. */}
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <p
              id="tax-q-title"
              ref={titleRef}
              tabIndex={-1}
              className={cn(
                'text-foreground min-w-0 outline-none',
                'focus-visible:ring-accent focus-visible:rounded-[var(--radius-sm)] focus-visible:ring-2',
                QUESTION_TEXT_CLASS,
              )}
            >
              {step === 'done' ? '질문이 모두 끝났습니다' : QUESTION_TITLE[step]}
            </p>
            {/* 용어 풀이 — 답하는 데 꼭 필요한 정보가 아니라 토글팁으로 둔다. */}
            {step === 'tax' ? (
              <HelpTip label="과세 · 비과세 · 불공 용어 설명">
                <b className="text-foreground">과세</b>는 부가세가 붙는 일반 거래,{' '}
                <b className="text-foreground">비과세</b>는 부가세가 없는 거래입니다.{' '}
                <b className="text-foreground">불공</b>은 불공제 — 세금계산서는 받았지만 매입세액을
                공제받지 못하는 거래입니다.
              </HelpTip>
            ) : null}
            {step === 'split' ? (
              <HelpTip label="비용분할 설명">
                한 장의 세금계산서를 예산단위·프로젝트·비용센터별로 나눠 다는 것입니다. 분할하면
                증빙유형이 원증빙 계열(과세 11 · 비과세 13)로 바뀝니다.
              </HelpTip>
            ) : null}
            {step === 'period' ? (
              <HelpTip label="세금계산서일 기간 설명">
                여기서 고른 기간에 발행된 (세금)계산서만 다음 리스트 화면에 나타납니다. 기본값은 한
                달 전부터 오늘까지입니다.
              </HelpTip>
            ) : null}
          </div>

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
              <div className="flex flex-wrap items-center gap-2">
                {/* 날짜 칸은 폭을 묶어 둔다 — 질문 열이 넓어(≈860px) w-full 로 두면 한 줄에
                    하나씩 눕고 '~' 가 따로 떨어져 기간처럼 안 보인다. */}
                <DatePicker
                  ariaLabel="세금계산서일 시작"
                  value={value.invoiceFrom}
                  onChange={(v) => set({ invoiceFrom: v })}
                  className="w-40"
                />
                <span className="text-foreground-secondary text-[length:var(--text-body)]">~</span>
                <DatePicker
                  ariaLabel="세금계산서일 종료"
                  value={value.invoiceTo}
                  onChange={(v) => set({ invoiceTo: v })}
                  className="w-40"
                />
              </div>
              {/* 오류는 원인이 되는 입력 **바로 아래**에 둔다 — 위나 화면 끝으로 보내면
                  고칠 칸과 메시지가 떨어져 무엇을 고쳐야 할지 다시 찾아야 한다. */}
              {rangeInvalid ? (
                <p
                  role="alert"
                  className="text-danger flex items-center gap-1.5 text-[length:var(--text-body-sm)] font-semibold"
                >
                  <RiErrorWarningLine size={16} aria-hidden className="shrink-0" />
                  시작일이 종료일보다 늦을 수 없습니다.
                </p>
              ) : null}
              {/* 빠른 선택 — 달력을 열지 않고 흔히 쓰는 기간을 한 번에 넣는다.
                  이번 달만 1일 기준이고 나머지는 오늘 기준 롤링(사용자 확정 2026-08-04). */}
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-foreground-secondary text-[length:var(--text-body-sm)]">
                  빠른 선택
                </span>
                {RANGE_PRESETS.map((p) => {
                  const r = p.range();
                  const active = value.invoiceFrom === r.from && value.invoiceTo === r.to;
                  return (
                    <button
                      key={p.id}
                      type="button"
                      aria-pressed={active}
                      onClick={() => set({ invoiceFrom: r.from, invoiceTo: r.to })}
                      className={cn(
                        'h-9 cursor-pointer rounded-[var(--radius-sm)] border px-3',
                        'text-[length:var(--text-body-sm)] transition-colors',
                        'focus-visible:ring-accent focus-visible:ring-2 focus-visible:outline-none',
                        active
                          ? 'border-accent bg-accent/10 text-foreground font-semibold'
                          : 'border-border text-foreground-secondary hover:border-accent hover:text-foreground',
                      )}
                    >
                      {p.label}
                    </button>
                  );
                })}
              </div>
              {/* 더미 데이터 범위 — 이건 토글팁으로 숨기면 안 된다. 모르면 리스트가 비어
                  "고장났나?" 로 이어지는, 이 화면에서 유일하게 '몰라서 막히는' 정보다. */}
              <p className="border-info/30 bg-info/10 text-foreground-secondary flex items-start gap-2 rounded-[var(--radius-md)] border px-3 py-2 text-[length:var(--text-body-sm)] leading-relaxed">
                <RiInformationLine size={16} aria-hidden className="text-info mt-0.5 shrink-0" />
                <span>
                  이 시뮬레이션의 더미 세금계산서는{' '}
                  <b className="text-foreground tabular-nums">
                    {INVOICE_DATE_MIN} ~ {INVOICE_DATE_MAX}
                  </b>{' '}
                  에만 있습니다. 이 범위를 벗어나면 리스트가 비어 보입니다.
                </span>
              </p>
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

          {/* 마지막 화면은 오른쪽이 통째로 비어 있었다. 질문들이 결국 무엇을 정했는지 —
              증빙유형 코드 — 를 그 자리에 크게 세운다(하단 바는 중복이라 이때만 숨긴다). */}
          {step === 'done' ? <EvidenceResult answers={value} ctaLabel={ctaLabel} /> : null}
        </section>
      </div>

      {/* 선택되는 증빙유형 — 요약까지 가지 않아도 지금 답이 어떤 코드가 되는지 바로 보인다
          (문서 시뮬레이터 docs/tax-invoice-flow.html 과 같은 규칙). */}
      {step === 'done' ? null : <EvidenceBar answers={value} />}

      <div className="flex shrink-0 items-center justify-between gap-2">
        <Button variant="ghost" onClick={() => prevKey && setStep(prevKey)} disabled={!prevKey}>
          <RiArrowLeftLine size={16} aria-hidden />
          이전
        </Button>
        {step === 'done' ? (
          <Button onClick={onNext} disabled={!complete}>
            {ctaLabel}
            <RiArrowRightLine size={16} aria-hidden />
          </Button>
        ) : (
          // 답이 없으면 비활성 — 이유는 기간 역전 오류 문구가 바로 위에서 이미 말해 준다.
          // (예전 title 속성은 호버로만 뜨고 터치·스크린리더가 못 읽어 걷어냈다.)
          <Button onClick={() => setStep(stepAfter(value, step))} disabled={!stepAnswered}>
            다음
            <RiArrowRightLine size={16} aria-hidden />
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
 * 상단 진행 표시 — "질문 n / N" + 칸 막대.
 *
 * 예전에는 질문 이름 5개를 10px 로 늘어놓았다(`1. 발행 여부 › 2. 계산서일 › …`). 읽히지도
 * 않고(대비 2.98:1) 바로 아래 진짜 질문과 경쟁하기만 해서, 위치 정보만 남기고 이름은 뺐다
 * — 지나온 질문의 이름과 답은 왼쪽 레일이 이미 더 크게 보여준다.
 *
 * 경로에 따라 질문 수가 달라지므로 발행 여부를 고르기 전에는 총 개수를 단정하지 않는다.
 */
function WizardProgress({
  answers,
  step,
  path,
}: {
  answers: QuestionAnswers;
  step: WizardStep;
  path: readonly QuestionKey[];
}) {
  const done = step === 'done';
  const position = done ? path.length : path.indexOf(step) + 1;
  const known = !!answers.issue;

  return (
    <div className="flex shrink-0 items-center gap-3">
      <p className="text-foreground text-[length:var(--text-body)] font-semibold whitespace-nowrap">
        {done ? (
          <>질문 완료</>
        ) : (
          <>
            질문 <span className="tabular-nums">{position}</span>
            <span className="text-foreground-secondary font-normal">
              {' / '}
              <span className="tabular-nums">{known ? path.length : '?'}</span>
            </span>
          </>
        )}
      </p>

      {/* 칸 막대 — 질문 수가 2~5개라 칸으로 나눠 그리는 편이 위치를 더 정확히 보여준다.
          화면에는 질문 이름을 적지 않지만(진짜 질문과 경쟁한다) 스크린리더에는 경로 전체를
          읽어 준다 — 위저드는 어디까지 왔고 무엇이 남았는지 알려야 한다는 권고를 지키되,
          그 부담을 시각 레이아웃이 아니라 접근성 트리로 옮긴 것이다. */}
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={known ? path.length : undefined}
        aria-valuenow={known ? position : undefined}
        aria-valuetext={
          // `done` 대신 step 을 직접 비교해야 타입이 좁혀져 QUESTION_SHORT 색인이 성립한다.
          step === 'done'
            ? `질문 ${path.length}개 모두 완료`
            : `${path.length}개 중 ${position}번째 — ${QUESTION_SHORT[step]}. 전체 순서: ${path
                .map((k, i) => `${i + 1}. ${QUESTION_SHORT[k]}`)
                .join(', ')}`
        }
        aria-label="질문 진행"
        className="flex w-full max-w-[260px] min-w-0 items-center gap-1"
      >
        {path.map((k, i) => (
          <span
            key={k}
            aria-hidden
            className={cn(
              'h-1.5 flex-1 rounded-full transition-colors',
              done || i < position - 1
                ? 'bg-accent'
                : i === position - 1
                  ? 'bg-accent/50'
                  : 'bg-border',
            )}
          />
        ))}
        {!known ? <span aria-hidden className="bg-border h-1.5 flex-1 rounded-full" /> : null}
      </div>

      {/* 이 화면이 어떻게 굴러가는지 — 답하는 데 필요 없는 설명이라 토글팁 안으로. */}
      <HelpTip label="이 화면 사용법" side="bottom">
        한 번에 한 질문씩 묻습니다. 선택지를 고르면 곧바로 다음 질문으로 넘어가고, 고른 답은 왼쪽에
        쌓입니다. 왼쪽 답을 누르면 그 질문으로 돌아가 고칠 수 있습니다.
        {!known ? ' 발행 전이면 질문 2개, 발행 후면 4~5개입니다.' : null}
      </HelpTip>
    </div>
  );
}

/**
 * 요약 레일 한 줄 — 질문 이름 + 고른 값. **줄 전체가 그 질문으로 돌아가는 버튼**이다.
 *
 * 예전에는 오른쪽 끝 '수정' 버튼만 눌렸는데 실측 39.3×16.5px 로 최소 타깃(24×24)에
 * 한참 못 미쳤다. 줄 전체를 타깃으로 만들면 224×44px 가 되어 여유롭게 통과한다.
 * '수정' 표기는 그대로 남긴다 — 타깃만 넓히고 누를 수 있다는 신호는 유지한다.
 */
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

  const label = (
    <>
      <span className="flex items-center justify-between gap-1">
        <span className="text-foreground-secondary truncate text-[11px] font-semibold tracking-wide">
          {QUESTION_SHORT[question]}
          {/* 작은 글자에 accent 를 쓰지 않는다 — accent/10 배경 위에서 4.14:1 로 4.5:1 에
              못 미친다. '지금'은 줄 전체의 accent 테두리·배경이 이미 표시하고 있다. */}
          {current ? <span className="text-foreground font-bold"> · 지금</span> : null}
        </span>
        {!current && answered ? (
          <span
            aria-hidden
            className="text-foreground-secondary group-hover:text-accent inline-flex shrink-0 items-center gap-0.5 text-[11px]"
          >
            <RiPencilLine size={12} />
            수정
          </span>
        ) : null}
      </span>
      <span
        className={cn(
          'line-clamp-2 block text-left text-[length:var(--text-body-sm)] leading-snug font-semibold',
          answered ? 'text-foreground' : 'text-foreground-tertiary',
        )}
      >
        {text}
      </span>
    </>
  );

  // 지금 보고 있는 질문은 버튼이 아니다 — 이미 그 질문 화면이라 누를 곳이 없다.
  if (current || !answered) {
    return (
      <li
        className={cn(
          'flex min-h-11 flex-col justify-center rounded-[var(--radius-sm)] px-2 py-1',
          current && 'bg-accent/10 ring-accent/30 ring-1',
        )}
      >
        {label}
      </li>
    );
  }

  return (
    <li>
      <button
        type="button"
        onClick={onEdit}
        aria-label={`${QUESTION_SHORT[question]} 수정 — 현재 답: ${text}`}
        className={cn(
          'group flex min-h-11 w-full cursor-pointer flex-col justify-center gap-0.5',
          'hover:bg-muted focus-visible:ring-accent rounded-[var(--radius-sm)] px-2 py-1',
          'text-left transition-colors focus-visible:ring-2 focus-visible:outline-none',
        )}
      >
        {label}
      </button>
    </li>
  );
}

/** 하단 증빙유형 — 아직 못 정하면 무엇을 더 골라야 하는지 알린다(자리를 비우지 않는다). */
function EvidenceBar({ answers }: { answers: QuestionAnswers }) {
  const ev = evidenceFor(answers.issue, answers.split, answers.tax, answers.nondeduct);
  const pending = !answers.issue ? '발행 여부' : !answers.tax ? '과세여부' : '불공 사유';
  return (
    <div className="border-border-subtle bg-muted/40 flex shrink-0 flex-wrap items-baseline gap-x-3 gap-y-1 rounded-[var(--radius-md)] border px-3 py-2">
      <span className="text-foreground-secondary text-[11px] font-semibold tracking-wide">
        증빙유형
      </span>
      {ev ? (
        <>
          <span className="text-accent font-mono text-[22px] leading-none font-bold tabular-nums">
            {ev.code}
          </span>
          <span className="text-foreground text-[length:var(--text-body-sm)] font-semibold">
            {ev.label}
          </span>
          {ev.note ? (
            <span className="text-foreground-secondary w-full text-[length:var(--text-body-sm)]">
              {ev.note}
            </span>
          ) : null}
        </>
      ) : (
        <span className="text-foreground-secondary text-[length:var(--text-body-sm)]">
          {pending}를 고르면 증빙유형이 정해집니다.
        </span>
      )}
    </div>
  );
}

/**
 * 마지막 화면의 결과 카드 — 질문들이 결국 정한 것은 **증빙유형 코드 하나**다.
 * 오른쪽 열이 통째로 비어 있던 자리를 이 결과가 채운다(하단 EvidenceBar 는 이때 숨긴다).
 */
function EvidenceResult({ answers, ctaLabel }: { answers: QuestionAnswers; ctaLabel: string }) {
  const ev = evidenceFor(answers.issue, answers.split, answers.tax, answers.nondeduct);
  return (
    <div className="border-accent/30 bg-accent/5 flex flex-col gap-1 rounded-[var(--radius-md)] border px-4 py-3">
      <span className="text-foreground-secondary text-[11px] font-semibold tracking-wide">
        이 답으로 정해진 증빙유형
      </span>
      {ev ? (
        <>
          <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-accent font-mono text-[34px] leading-none font-bold tabular-nums">
              {ev.code}
            </span>
            <span className="text-foreground text-[length:var(--text-body-lg)] font-semibold">
              {ev.label}
            </span>
          </span>
          {ev.note ? (
            <span className="text-foreground-secondary mt-1 text-[length:var(--text-body-sm)] leading-relaxed">
              {ev.note}
            </span>
          ) : null}
        </>
      ) : null}
      <span className="text-foreground-secondary mt-1 text-[length:var(--text-body-sm)] leading-relaxed">
        확인했으면 <b className="text-foreground">{ctaLabel}</b>로 넘어가세요. 고칠 답은 왼쪽에서 그
        줄을 누르면 됩니다.
      </span>
    </div>
  );
}
