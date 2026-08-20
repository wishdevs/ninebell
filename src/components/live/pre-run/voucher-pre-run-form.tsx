'use client';

import { useState } from 'react';
import { RiInformationLine, RiPlayLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { DatePicker } from '@/components/ui/date-picker';
import { FormField } from '@/components/ui/form-field';
import { SectionCard } from '@/components/ui/section-card';
import { useDebugMode } from '@/lib/debug-mode';
import type { PreRunFormProps } from './index';

/**
 * 미지급금 법인카드(voucher-card) 실행 전 폼 — 회계일 조회기간.
 * (종전엔 외상매출금·외상매입금도 공용했으나 두 에이전트는 voucher-by-type 으로 통합,
 *  전용 폼 voucher-type-pre-run-form 을 쓴다.)
 *
 * 조회 조건이 대부분 고정(회계단위·전표상태 미결·전자결재상태 저장·전표유형)이고
 * 사용자가 고르는 값은 **회계일 기간** 하나다. 기본값은 이번 달 1일~말일이며, 월 일부(예: 7/1~
 * 7/5)도 그대로 지정할 수 있다.
 *
 * 백엔드 계약: `params["voucher"] = { period_from, period_to }`(YYYY-MM-DD 로 보내면 서버가
 * YYYYMMDD 로 정규화). 기간을 보내지 않으면 서버는 화면 기본값(당월)을 쓴다.
 */

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

/** 로컬 기준 'yyyy-mm-dd'(TZ 밀림 방지 — toISOString 미사용, DatePicker 와 같은 규약). */
function toIso(y: number, m1: number, d: number): string {
  return `${y}-${pad2(m1)}-${pad2(d)}`;
}

/** 이번 달 1일~말일(로컬 기준) — 폼 기본값. */
function currentMonthRange(): { from: string; to: string } {
  const now = new Date();
  const y = now.getFullYear();
  const m1 = now.getMonth() + 1;
  const last = new Date(y, m1, 0).getDate(); // 다음 달 0일 = 이번 달 말일
  return { from: toIso(y, m1, 1), to: toIso(y, m1, last) };
}

/** 'YYYYMMDD' | 'YYYY-MM-DD' → 'YYYY-MM-DD'. 형식 불일치는 undefined(기본값 사용). */
function toDateInput(v: unknown): string | undefined {
  if (typeof v !== 'string') return undefined;
  const digits = v.replace(/-/g, '');
  if (!/^\d{8}$/.test(digits)) return undefined;
  return `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6, 8)}`;
}

/** 마지막 제출 params → 폼 초기값 복원(종료 후 값 수정 재실행). 없으면 이번 달. */
function seedRange(initial: Record<string, unknown> | undefined): { from: string; to: string } {
  const fallback = currentMonthRange();
  const v = initial?.voucher as Record<string, unknown> | undefined;
  if (!v || typeof v !== 'object') return fallback;
  return {
    from: toDateInput(v.period_from) ?? fallback.from,
    to: toDateInput(v.period_to) ?? fallback.to,
  };
}

export function VoucherPreRunForm({ agent, disabled, initialParams, onStart }: PreRunFormProps) {
  const debugMode = useDebugMode();
  const [range] = useState(() => seedRange(initialParams));
  const [from, setFrom] = useState(range.from);
  const [to, setTo] = useState(range.to);

  const rangeInvalid = !!from && !!to && from > to;
  const canSubmit = !disabled && !!from && !!to && !rangeInvalid;

  const submit = () => {
    if (!canSubmit) return;
    // 백엔드 계약: params["voucher"] — 서버가 YYYYMMDD 정규화 + 시작>종료 재검증한다.
    onStart({ voucher: { period_from: from, period_to: to } });
  };

  return (
    <SectionCard
      caption="실행 전 입력"
      title={`${agent.name} — 조회기간`}
      description="조회할 회계일 기간을 지정하고 실행하세요. 기본값은 이번 달 1일~말일이며, 월 일부 기간(예: 1일~5일)도 지정할 수 있습니다. 나머지 조회 조건(전표상태 미결·전자결재상태 저장·전표유형)은 고정입니다."
      density="comfortable"
    >
      <div className="border-border/60 bg-muted/30 flex gap-2 rounded-[var(--radius-md)] border p-3">
        <RiInformationLine
          size={16}
          aria-hidden
          className="text-foreground-tertiary mt-0.5 shrink-0"
        />
        <p className="text-foreground-tertiary text-xs leading-relaxed">
          {debugMode ? (
            <>
              <b>디버그 모드 — 상신 버튼을 클릭하지 않습니다.</b> 결제창 확인(가상 상신)까지만
              수행하며, 전표는 목록에 그대로 남습니다.
            </>
          ) : (
            <>
              지정한 기간의 대상 전표를 순회하며 결제창을 열어 <b>전자결재로 실제 상신합니다.</b>{' '}
              전표 저장·삭제는 하지 않습니다.
            </>
          )}
        </p>
      </div>

      <div className="grid gap-5 sm:max-w-md">
        <FormField
          id="voucher-period-from"
          label="회계일 시작"
          required
          error={rangeInvalid ? '시작일이 종료일보다 늦을 수 없습니다.' : undefined}
        >
          <DatePicker
            ariaLabel="회계일 시작일"
            value={from}
            disabled={disabled}
            onChange={setFrom}
          />
        </FormField>

        <FormField id="voucher-period-to" label="회계일 종료" required>
          <DatePicker ariaLabel="회계일 종료일" value={to} disabled={disabled} onChange={setTo} />
        </FormField>
      </div>

      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-end md:gap-3">
        {/* 비활성 사유 — disabled:pointer-events-none 라 title 툴팁은 안 뜨므로 인라인으로 안내. */}
        {!canSubmit ? (
          <p className="text-foreground-tertiary text-xs md:text-right">
            회계일 기간을 올바르게 지정하면 실행할 수 있습니다.
          </p>
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
