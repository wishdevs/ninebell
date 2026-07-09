'use client';

import { RiAddLine, RiDeleteBinLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import type { FuelClass } from '@/lib/trip/fuel-calc';

/** 편집용 행 — kmPerL 은 입력 중 문자열로 두고 저장 시 숫자로 파싱한다. */
export interface FuelClassDraft {
  id: string;
  label: string;
  kmPerL: string;
}

export const MAX_KM_PER_L = 100;

let idSeq = 0;
/** 새 차량종류 id — 안정 식별자(라벨과 무관). 기존 id 와 겹치지 않게 접두 + 시퀀스. */
function newClassId(): string {
  idSeq += 1;
  return `c${Date.now().toString(36)}${idSeq}`;
}

export function toClassDraft(classes: readonly FuelClass[]): FuelClassDraft[] {
  return classes.map((c) => ({ id: c.id, label: c.label, kmPerL: String(c.kmPerL) }));
}

/** 한 행 검증 — 라벨 비어있지 않음 + kmPerL 1~100 정수. */
export function isClassDraftValid(row: FuelClassDraft): boolean {
  const n = Number(row.kmPerL);
  return row.label.trim().length > 0 && Number.isInteger(n) && n >= 1 && n <= MAX_KM_PER_L;
}

/**
 * 차량종류 기준연비 편집기 — 관리자가 행을 추가/삭제하고 라벨·기준연비(km/L)를 편집한다.
 * cc 가 아닌 분류(전기차 등)도 라벨 자유입력으로 담는다. id 는 내부 안정 식별자(자동 생성).
 * 제어 컴포넌트: value(초안 목록)/onChange 를 부모(AgentSettingsCard)가 소유한다.
 */
export function FuelClassesEditor({
  value,
  disabled,
  onChange,
}: {
  value: FuelClassDraft[];
  disabled?: boolean;
  onChange: (next: FuelClassDraft[]) => void;
}) {
  const update = (id: string, patch: Partial<FuelClassDraft>) =>
    onChange(value.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  const remove = (id: string) => onChange(value.filter((r) => r.id !== id));
  const add = () => onChange([...value, { id: newClassId(), label: '', kmPerL: '' }]);

  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-[1fr_8rem_1.75rem] items-center gap-2 px-1">
        <span className="text-foreground-tertiary text-[10px] font-semibold tracking-wider uppercase">
          차량종류
        </span>
        <span className="text-foreground-tertiary text-[10px] font-semibold tracking-wider uppercase">
          기준연비(km/L)
        </span>
        <span aria-hidden />
      </div>

      {value.map((row, idx) => {
        const kmInvalid = row.kmPerL.trim() !== '' && !isClassDraftValid({ ...row, label: 'x' });
        return (
          <div key={row.id} className="grid grid-cols-[1fr_8rem_1.75rem] items-start gap-2">
            <Input
              aria-label={`${idx + 1}행 차량종류 이름`}
              value={row.label}
              disabled={disabled}
              placeholder="예: 1,800cc 미만 / 전기차"
              onChange={(e) => update(row.id, { label: e.target.value })}
            />
            <div className="flex flex-col gap-1">
              <Input
                type="number"
                min={1}
                max={MAX_KM_PER_L}
                step={1}
                inputMode="numeric"
                aria-label={`${idx + 1}행 기준연비`}
                value={row.kmPerL}
                disabled={disabled}
                placeholder="예: 9"
                onChange={(e) => update(row.id, { kmPerL: e.target.value })}
                aria-invalid={kmInvalid ? true : undefined}
              />
              {kmInvalid ? (
                <p className="text-danger text-[11px]">1 ~ {MAX_KM_PER_L} 정수</p>
              ) : null}
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className={cn('text-foreground-tertiary hover:text-danger mt-1 px-0')}
              onClick={() => remove(row.id)}
              disabled={disabled || value.length <= 1}
              aria-label={`${idx + 1}번째 차량종류 삭제`}
              title={value.length <= 1 ? '최소 1개는 있어야 합니다' : undefined}
            >
              <RiDeleteBinLine size={15} aria-hidden />
            </Button>
          </div>
        );
      })}

      <div>
        <Button type="button" variant="secondary" size="sm" onClick={add} disabled={disabled}>
          <RiAddLine size={15} aria-hidden />
          차량종류 추가
        </Button>
      </div>
    </div>
  );
}
