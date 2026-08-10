'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { RiArrowRightLine, RiErrorWarningLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { DatePicker } from '@/components/ui/date-picker';
import { HelpTip } from '@/components/ui/help-tip';
import { cn } from '@/lib/utils';
import {
  answersComplete,
  emptyAnswers,
  questionPath,
  QUESTION_SHORT,
  type QuestionAnswers,
  type QuestionKey,
} from './question-flow';
import {
  defaultInvoiceRange,
  evidenceFor,
  QUICK_PICK_GROUPS,
  RANGE_PRESETS,
  INVOICE_DATE_MAX,
  INVOICE_DATE_MIN,
  ISSUE_LABEL,
  NONDEDUCT_LABEL,
  SPLIT_LABEL,
  TAX_LABEL,
  type IssueState,
  type NondeductReason,
  type QuickPick,
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
 * 1단계 — 질문 전부를 한 화면에 행으로 눕힌 폼.
 *
 * 위저드("한 번에 한 질문" + 왼쪽 답 레일 + 이전/다음)를 걷어냈다(2026-08-04 사용자 피드백).
 * 질문이 2~5개고 전부 클릭 한 번짜리라, 답을 왼쪽 레일에 접어 두고 '수정' 버튼으로 되돌아가는
 * 것보다 **그 자리에서 다른 선택지를 누르는** 쪽이 이동 비용이 없다. 화면 전환·진행 표시·
 * 되돌아가기가 전부 사라지고, 지금까지의 답과 남은 질문이 항상 한눈에 보인다.
 *
 * 포커스 관리(스텝 전환 시 제목 focus)와 focus-visible 링도 함께 걷어냈다 — 화면 전환이
 * 없으니 옮길 포커스 자체가 없고, 링 박스가 질문 위에 상시 노출되는 문제가 있었다.
 * 활성 표시는 바깥으로 그려지는 ring(box-shadow) 대신 **테두리+배경**만 쓴다 — 스크롤
 * 컨테이너 경계에서 잘려 나가던 원인이 ring 이었다.
 *
 * 무효화 규칙은 그대로: 발행 전/후를 바꾸면 뒤 답 전부 초기화, 분할을 켜면 불공 해제.
 */
export function QuestionsStep({ value, onChange, onNext }: QuestionsStepProps) {
  const set = (patch: Partial<QuestionAnswers>) => onChange({ ...value, ...patch });

  const pickIssue = (issue: IssueState) => {
    if (value.issue === issue) return;
    // 경로가 바뀌면 뒤 질문은 무효 — 전부 비운다(발행 전은 기간 자체가 없다).
    // 발행 전은 **비용분할이 불가**(사용자 확정 2026-08-03)라 split 을 'single' 로 고정한다.
    // 발행 후는 기간을 **한 달 전~오늘**로 미리 채운다 — 필요하면 달력이나 빠른 선택으로 바꾼다.
    const range = issue === 'after' ? defaultInvoiceRange() : { from: '', to: '' };
    onChange({
      ...emptyAnswers(),
      issue,
      split: issue === 'before' ? 'single' : null,
      invoiceFrom: range.from,
      invoiceTo: range.to,
    });
  };

  const pickSplit = (split: SplitChoice) => {
    if (value.split === split) return;
    // 분할을 켜면 불공 조합은 성립하지 않는다 → 과세여부를 해제해 다시 고르게 한다.
    const invalidates = split === 'split' && value.tax === 'nondeduct';
    onChange({ ...value, split, ...(invalidates ? { tax: null, nondeduct: null } : {}) });
  };

  const pickTax = (tax: TaxKind) =>
    set({ tax, nondeduct: tax === 'nondeduct' ? value.nondeduct : null });

  // 과세여부 선택지 — 분할이면 불공을 목록에서 제외한다(불공은 분할할 수 없다 — 미노출).
  const taxOptions: TaxKind[] =
    value.split === 'split' ? ['taxable', 'exempt'] : ['taxable', 'exempt', 'nondeduct'];

  const path = questionPath(value);
  const show = (k: QuestionKey) => path.includes(k);

  const rangeInvalid =
    !!value.invoiceFrom && !!value.invoiceTo && value.invoiceFrom > value.invoiceTo;
  // 기간은 유효한데 더미 데이터와 겹치지 않으면 리스트가 비어 나온다 — 미리 알려 "고장났나?"를 막는다.
  const rangeMissesData =
    !rangeInvalid &&
    !!value.invoiceFrom &&
    !!value.invoiceTo &&
    (value.invoiceTo < INVOICE_DATE_MIN || value.invoiceFrom > INVOICE_DATE_MAX);

  const complete = answersComplete(value);
  const ev = evidenceFor(value.issue, value.split, value.tax, value.nondeduct);
  const pending = !value.issue ? '발행 여부' : !value.tax ? '과세여부' : '불공 사유';
  const ctaLabel = value.issue === 'after' ? '리스트 보기' : '입력항목 채우기';

  // ── 포털 ↔ 질문 폼 (사용자 확정 2026-08-06: 포털형) ──────────────────────
  // 첫 화면은 증빙유형 카드 포털 — 숙련자는 카드 1클릭, 모르면 '질문으로 찾기'로 폼 진입.
  // 뒤 단계에서 답을 들고 되돌아오면(리스트→이전) 폼으로 바로 연다.
  const [entryMode, setEntryMode] = useState<'portal' | 'form'>(() =>
    value.issue === null ? 'portal' : 'form',
  );

  /** 코드 → 답 역방향 채움. 발행 여부가 같으면 이미 고른 기간은 존중한다(코드만 갈아타기). */
  const applyQuick = (p: QuickPick) => {
    const keepPeriod = value.issue === p.issue && !!value.invoiceFrom && !!value.invoiceTo;
    const range =
      p.issue === 'after'
        ? keepPeriod
          ? { from: value.invoiceFrom, to: value.invoiceTo }
          : defaultInvoiceRange()
        : { from: '', to: '' };
    onChange({
      issue: p.issue,
      split: p.split,
      tax: p.tax,
      nondeduct: p.nondeduct,
      invoiceFrom: range.from,
      invoiceTo: range.to,
    });
  };

  // 새 질문 행은 항상 아래에 붙는다 — 패널이 낮아 행 영역이 스크롤되면 방금 생긴 질문
  // (예: 불공 사유)이 접힌 채 안 보일 수 있어, 행이 늘어날 때만 맨 아래로 스크롤한다.
  const rowsRef = useRef<HTMLDivElement>(null);
  const rowCountRef = useRef(path.length);
  useEffect(() => {
    if (path.length > rowCountRef.current) {
      rowsRef.current?.scrollTo({ top: rowsRef.current.scrollHeight, behavior: 'smooth' });
    }
    rowCountRef.current = path.length;
  }, [path.length]);

  // ── 포털 — 첫 화면: 증빙유형 카드로 바로 시작(숙련자), 모르면 질문으로(초심자) ──
  if (entryMode === 'portal') {
    return (
      <div className="flex h-full min-h-0 flex-col gap-4">
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="flex flex-col gap-4">
            <div>
              <p className="text-foreground text-[length:var(--text-body-lg)] font-semibold">
                어떤 증빙으로 처리하나요?
              </p>
              <p className="text-foreground-secondary mt-0.5 text-[length:var(--text-body-sm)]">
                증빙유형을 이미 알면 코드를 바로 고르세요 — 질문 답이 자동으로 채워집니다.
              </p>
            </div>
            {QUICK_PICK_GROUPS.map((g) => (
              <div key={g.name} className="flex flex-col gap-1.5">
                <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-semibold tracking-wide">
                  {g.name}
                </p>
                <div className="flex flex-wrap gap-2">
                  {g.picks.map((p) => (
                    <PortalCard
                      key={p.code}
                      pick={p}
                      active={ev?.code === p.code}
                      onClick={() => {
                        applyQuick(p);
                        setEntryMode('form');
                      }}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="shrink-0">
          <Button variant="secondary" onClick={() => setEntryMode('form')}>
            잘 모르겠어요 — 질문으로 찾기
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {/* 포털 복귀 — 코드를 갈아타고 싶을 때. 답은 유지되어 현재 코드 카드가 켜진 채 열린다. */}
      <button
        type="button"
        onClick={() => setEntryMode('portal')}
        className="text-foreground-tertiary hover:text-foreground self-start text-[length:var(--text-caption)] transition-colors outline-none"
      >
        ‹ 증빙유형 바로 선택
      </button>

      <div ref={rowsRef} className="flex min-h-0 flex-1 flex-col gap-3.5 overflow-y-auto">
        <QuestionRow label={QUESTION_SHORT.issue}>
          <div className="flex flex-wrap gap-2">
            <ChoicePill
              label={ISSUE_LABEL.before}
              active={value.issue === 'before'}
              onClick={() => pickIssue('before')}
            />
            <ChoicePill
              label={ISSUE_LABEL.after}
              active={value.issue === 'after'}
              onClick={() => pickIssue('after')}
            />
          </div>
          {/* 고른 갈래가 다음에 무엇으로 이어지는지 — 답한 뒤에만 한 줄로. */}
          {value.issue ? (
            <p className="text-foreground-tertiary text-[length:var(--text-body-sm)] leading-snug">
              {value.issue === 'before'
                ? '아직 발행되지 않아 리스트 없이 바로 입력항목을 채웁니다. 발행 전은 비용분할이 불가합니다.'
                : '이미 발행되어 조회됩니다 — 아래 기간의 리스트에서 처리할 항목을 고릅니다.'}
            </p>
          ) : null}
        </QuestionRow>

        {show('period') ? (
          <QuestionRow
            label={QUESTION_SHORT.period}
            help={
              <HelpTip label="세금계산서일 기간 설명">
                여기서 고른 기간에 발행된 (세금)계산서만 다음 리스트 화면에 나타납니다. 기본값은 한
                달 전부터 오늘까지입니다.
              </HelpTip>
            }
          >
            <div className="flex flex-wrap items-center gap-2">
              {/* 날짜 칸은 폭을 묶어 둔다 — w-full 로 두면 한 줄에 하나씩 눕고
                  '~' 가 따로 떨어져 기간처럼 안 보인다. */}
              <DatePicker
                ariaLabel="세금계산서일 시작"
                value={value.invoiceFrom}
                onChange={(v) => set({ invoiceFrom: v })}
                className="w-36"
              />
              <span className="text-foreground-secondary text-[length:var(--text-body)]">~</span>
              <DatePicker
                ariaLabel="세금계산서일 종료"
                value={value.invoiceTo}
                onChange={(v) => set({ invoiceTo: v })}
                className="w-36"
              />
              <span aria-hidden className="bg-border mx-1 h-5 w-px" />
              {/* 빠른 선택 — 달력을 열지 않고 흔히 쓰는 기간을 한 번에 넣는다.
                  이번 달만 1일 기준이고 나머지는 오늘 기준 롤링(사용자 확정 2026-08-04). */}
              {RANGE_PRESETS.map((p) => {
                const r = p.range();
                const active = value.invoiceFrom === r.from && value.invoiceTo === r.to;
                return (
                  <ChoicePill
                    key={p.id}
                    label={p.label}
                    active={active}
                    onClick={() => set({ invoiceFrom: r.from, invoiceTo: r.to })}
                  />
                );
              })}
            </div>
            {/* 오류는 원인이 되는 입력 **바로 아래**에 둔다. */}
            {rangeInvalid ? (
              <p
                role="alert"
                className="text-danger flex items-center gap-1.5 text-[length:var(--text-body-sm)] font-semibold"
              >
                <RiErrorWarningLine size={16} aria-hidden className="shrink-0" />
                시작일이 종료일보다 늦을 수 없습니다.
              </p>
            ) : null}
            {/* 기간이 조회 가능 범위를 아예 빗나가면 미리 알린다 — 다음 화면에서 빈 리스트를
                보고 "고장났나?" 로 이어지는 것을 막는다(평소에는 아무것도 띄우지 않는다). */}
            {rangeMissesData ? (
              <p className="text-foreground flex items-center gap-1.5 text-[length:var(--text-body-sm)] leading-snug font-medium">
                <RiErrorWarningLine size={14} aria-hidden className="text-warning shrink-0" />
                <span>
                  이 기간에는 조회되는 (세금)계산서가 없습니다 — 다음 리스트가 비어 나옵니다.
                </span>
              </p>
            ) : null}
          </QuestionRow>
        ) : null}

        {show('split') ? (
          <QuestionRow
            label={QUESTION_SHORT.split}
            help={
              <HelpTip label="비용분할 설명">
                한 장의 세금계산서를 예산단위·프로젝트·비용센터별로 나눠 다는 것입니다. 분할하면
                증빙유형이 원증빙 계열(과세 11 · 비과세 13)로 바뀝니다.
              </HelpTip>
            }
          >
            <div className="flex flex-wrap gap-2">
              <ChoicePill
                label={SPLIT_LABEL.single}
                active={value.split === 'single'}
                onClick={() => pickSplit('single')}
              />
              <ChoicePill
                label={SPLIT_LABEL.split}
                active={value.split === 'split'}
                onClick={() => pickSplit('split')}
              />
            </div>
          </QuestionRow>
        ) : null}

        {show('tax') ? (
          <QuestionRow
            label={QUESTION_SHORT.tax}
            help={
              <HelpTip label="과세 · 비과세 · 불공 용어 설명">
                <b className="text-foreground">과세</b>는 부가세가 붙는 일반 거래,{' '}
                <b className="text-foreground">비과세</b>는 부가세가 없는 거래입니다.{' '}
                <b className="text-foreground">불공</b>은 불공제 — 세금계산서는 받았지만 매입세액을
                공제받지 못하는 거래입니다.
              </HelpTip>
            }
          >
            <div className="flex flex-wrap gap-2">
              {taxOptions.map((t) => (
                <ChoicePill
                  key={t}
                  label={TAX_LABEL[t]}
                  active={value.tax === t}
                  onClick={() => pickTax(t)}
                />
              ))}
            </div>
          </QuestionRow>
        ) : null}

        {show('nondeduct') ? (
          <QuestionRow label={QUESTION_SHORT.nondeduct}>
            <div className="flex flex-wrap gap-2">
              {(Object.keys(NONDEDUCT_LABEL) as NondeductReason[]).map((r) => (
                <ChoicePill
                  key={r}
                  label={NONDEDUCT_LABEL[r]}
                  active={value.nondeduct === r}
                  onClick={() => set({ nondeduct: r })}
                />
              ))}
            </div>
          </QuestionRow>
        ) : null}
      </div>

      {/* 하단 한 줄 — 지금 답이 어떤 증빙유형 코드가 되는지 + 다음 단계 CTA.
          (문서 시뮬레이터 docs/tax-invoice-flow.html 과 같은 규칙.) */}
      <div className="border-border-subtle bg-muted/40 flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1.5 rounded-[var(--radius-md)] border px-3.5 py-2.5">
        <span className="text-foreground-secondary text-[length:var(--text-caption)] font-semibold tracking-wide">
          증빙유형
        </span>
        {ev ? (
          <>
            <span className="text-accent font-mono text-[length:var(--text-heading)] leading-none font-bold tabular-nums">
              {ev.code}
            </span>
            <span className="text-foreground text-[length:var(--text-body)] font-semibold">
              {ev.label}
            </span>
            {ev.note ? (
              <span className="text-foreground-tertiary text-[length:var(--text-body-sm)]">
                {ev.note}
              </span>
            ) : null}
          </>
        ) : (
          <span className="text-foreground-secondary text-[length:var(--text-body-sm)]">
            {pending}를 고르면 증빙유형이 정해집니다.
          </span>
        )}
        <div className="ml-auto">
          <Button onClick={onNext} disabled={!complete}>
            {ctaLabel}
            <RiArrowRightLine size={16} aria-hidden />
          </Button>
        </div>
      </div>
    </div>
  );
}

/**
 * 질문 한 행 — 왼쪽 고정폭 라벨 + 오른쪽 선택지/입력. 라벨 옆 [?]는 답하는 데 꼭 필요하지
 * 않은 설명(용어 풀이·동작 방식)을 접어 두는 자리다.
 */
function QuestionRow({
  label,
  help,
  children,
}: {
  label: string;
  help?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5 sm:flex-row sm:gap-4">
      <div className="flex shrink-0 items-center gap-1 sm:h-10 sm:w-24">
        <span className="text-foreground text-[length:var(--text-body-sm)] font-semibold">
          {label}
        </span>
        {help}
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">{children}</div>
    </div>
  );
}

/**
 * 선택지 pill — 활성 표시는 테두리+배경만. 바깥으로 그려지는 ring(box-shadow)은 스크롤
 * 컨테이너 경계에서 잘리고, focus-visible 링은 쓰지 않는다(2026-08-04 사용자 확정).
 *
 * 규격은 같은 줄에 놓이는 폼 컨트롤(DatePicker·Button md)과 맞춘다 — h-10 · rounded-sm ·
 * 14px(body). 활성 색은 앱의 틴트형 선택 계열(FilterPill·RangeSegment·code-catalog)과 같은
 * `border-accent bg-accent/10 text-accent`. 굵기는 상태와 무관하게 고정 — 활성에서 굵어지면
 * 글자 폭이 변해 옆 pill 들이 밀린다.
 */
/**
 * 포털 카드 — 증빙유형 코드가 주인공(모노 볼드 액센트). 현재 답 조합과 일치하는 카드는
 * 활성(틴트)으로 켜져 "지금 상태 = 이 코드" 양방향 피드백을 겸한다.
 */
function PortalCard({
  pick,
  active,
  onClick,
}: {
  pick: QuickPick;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        'flex cursor-pointer items-center gap-2.5 rounded-[var(--radius-md)] border px-3.5 py-2.5 text-left transition-colors outline-none',
        active
          ? 'border-accent bg-accent/10'
          : 'border-border bg-surface hover:border-accent/50 hover:bg-muted/60',
      )}
    >
      <span className="text-accent font-mono text-[length:var(--text-body-lg)] font-bold tabular-nums">
        {pick.code}
      </span>
      <span
        className={cn(
          'text-[length:var(--text-body-sm)] font-medium',
          active ? 'text-accent' : 'text-foreground',
        )}
      >
        {pick.label}
      </span>
    </button>
  );
}

function ChoicePill({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        'h-10 cursor-pointer rounded-[var(--radius-sm)] border px-4 text-[length:var(--text-body)] font-medium transition-colors outline-none',
        active
          ? 'border-accent bg-accent/10 text-accent'
          : 'border-border text-foreground-secondary hover:border-accent/50 hover:bg-muted/60 hover:text-foreground',
      )}
    >
      {label}
    </button>
  );
}
