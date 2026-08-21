'use client';

import { RiAddLine, RiArrowDownSLine, RiArrowUpSLine, RiDeleteBinLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { StatusPill } from '@/components/ui/status-pill';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import {
  BASE_DATE_KEYS,
  MAX_GROUP_EXCEPTIONS,
  MAX_GROUP_MODULES,
  MAX_OFFSET_WEEKS,
  PJT_PLACEHOLDER,
  PROCESSED_DUE_BASE,
  newPatternId,
  type BaseDateKey,
  type ExceptionScopeKind,
} from '@/lib/purchase/order-patterns';
import type { ExceptionDraft, GroupDraft, ModuleDraft } from './order-patterns-editor';

const MICRO = 'text-foreground-tertiary text-[10px] font-semibold tracking-wider uppercase';
/** 네이티브 셀렉트를 Input 과 같은 높이·포커스 표현으로 맞춘다(바깥 오프셋 링 제거). */
const SELECT =
  'h-9 py-1 pr-8 pl-2.5 text-[12px] focus-visible:border-accent focus-visible:ring-offset-0';
const MODULE_COLS = 'grid grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_1.75rem] items-center gap-2';

/** 예외 대상 3종 — 값의 의미가 kind 마다 달라 라벨에 예시를 붙인다. */
const SCOPE_LABELS: Record<ExceptionScopeKind, string> = {
  vendorClass: '분류',
  vendor: '거래처',
  exceptClass: '분류 제외',
};

/**
 * 값 칸은 비어 있는 경우가 흔해 '예:' 를 붙인다 — 채워진 옆 행과 헷갈리지 않게.
 * 거래처는 부분 일치라 정식명 전체가 아니라 일부('와이엔에스')만 적어도 된다.
 */
const SCOPE_PLACEHOLDERS: Record<ExceptionScopeKind, string> = {
  vendorClass: '예: 가공품',
  vendor: '예: 와이엔에스 (이름 일부)',
  exceptClass: '예: 판금품',
};

/**
 * 발주그룹 카드 1장 — 그룹 1개가 계획서의 발주단위 1건이 된다.
 *
 * 본문 3단: 그룹 속성(발주묶음·그룹명·납기 규칙·구매사유) → 모듈(규격/품명) → 예외 규칙.
 * 예외는 배열 순서가 곧 필드별 first-wins 우선순위라 이동 버튼을 남긴다.
 * 제어 컴포넌트: group/onChange 를 부모(OrderPatternsEditor)가 소유한다.
 */
export function GroupEditor({
  group,
  index,
  total,
  disabled,
  onChange,
  onMove,
  onRemove,
}: {
  group: GroupDraft;
  index: number;
  total: number;
  disabled?: boolean;
  onChange: (next: GroupDraft) => void;
  onMove: (delta: number) => void;
  onRemove: () => void;
}) {
  const coord = `그룹 ${index + 1}`;

  const patch = (next: Partial<GroupDraft>) => onChange({ ...group, ...next });

  const patchModule = (id: string, next: Partial<ModuleDraft>) =>
    patch({ modules: group.modules.map((m) => (m.id === id ? { ...m, ...next } : m)) });

  const patchException = (id: string, next: Partial<ExceptionDraft>) =>
    patch({ exceptions: group.exceptions.map((x) => (x.id === id ? { ...x, ...next } : x)) });

  const moveException = (idx: number, delta: number) => {
    const to = idx + delta;
    if (to < 0 || to >= group.exceptions.length) return;
    const next = [...group.exceptions];
    [next[idx], next[to]] = [next[to], next[idx]];
    patch({ exceptions: next });
  };

  return (
    <section className="border-border bg-surface overflow-hidden rounded-[var(--radius-md)] border shadow-[var(--shadow-card)]">
      {/* 헤더 밴드 — 순서·발주묶음·그룹명을 카드 경계로 띄운다(발주단위 카드와 같은 패턴). */}
      <div className="bg-muted/50 border-border/70 flex flex-wrap items-center gap-2 border-b px-4 py-2.5">
        <span className="text-foreground-tertiary text-[11px] tabular-nums">{index + 1}</span>
        <StatusPill label={group.bundle.trim() || '(발주묶음 없음)'} variant="info" />
        <span className="text-foreground text-[length:var(--text-body)] font-semibold">
          {group.name.trim() || '(그룹명 없음)'}
        </span>
        <span className="text-foreground-tertiary text-[11px] tabular-nums">
          모듈 {group.modules.length}
          {group.exceptions.length > 0 ? ` · 예외 ${group.exceptions.length}` : ''}
        </span>
        <div className="ml-auto flex shrink-0 items-center gap-0.5">
          <IconBtn
            label={`${coord} 위로`}
            onClick={() => onMove(-1)}
            disabled={disabled || index === 0}
          >
            <RiArrowUpSLine size={16} aria-hidden />
          </IconBtn>
          <IconBtn
            label={`${coord} 아래로`}
            onClick={() => onMove(1)}
            disabled={disabled || index === total - 1}
          >
            <RiArrowDownSLine size={16} aria-hidden />
          </IconBtn>
          <IconBtn
            label={`${coord} 삭제`}
            onClick={onRemove}
            disabled={disabled || total <= 1}
            title={total <= 1 ? '최소 1개 그룹은 있어야 합니다' : undefined}
            danger
          >
            <RiDeleteBinLine size={15} aria-hidden />
          </IconBtn>
        </div>
      </div>

      <div className="flex flex-col gap-4 p-4">
        {/* 1단 — 그룹 속성. */}
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-end gap-2">
            <Field label="발주묶음" className="w-24">
              <Input
                aria-label={`${coord} 발주묶음`}
                value={group.bundle}
                disabled={disabled}
                placeholder="EFEM"
                maxLength={32}
                className="h-9 text-[12px]"
                onChange={(e) => patch({ bundle: e.target.value })}
              />
            </Field>
            <Field label="그룹명" className="w-56">
              <Input
                aria-label={`${coord} 그룹명`}
                value={group.name}
                disabled={disabled}
                placeholder="1공장"
                maxLength={64}
                className="h-9 text-[12px]"
                onChange={(e) => patch({ name: e.target.value })}
              />
            </Field>
            <Field label="납기 기준" className="w-32">
              <Select
                aria-label={`${coord} 납기 기준일`}
                value={group.dueBase}
                disabled={disabled}
                className={SELECT}
                onChange={(e) => patch({ dueBase: e.target.value as BaseDateKey })}
              >
                {BASE_DATE_KEYS.map((key) => (
                  <option key={key} value={key}>
                    {key}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="주 전" className="w-20">
              <Input
                type="number"
                min={0}
                max={MAX_OFFSET_WEEKS}
                step={1}
                inputMode="numeric"
                aria-label={`${coord} 납기 주 전`}
                value={group.dueOffset}
                disabled={disabled}
                className="h-9 px-2 text-[12px]"
                onChange={(e) => patch({ dueOffset: e.target.value })}
              />
            </Field>
          </div>
          <Field label="구매사유">
            <Textarea
              rows={2}
              aria-label={`${coord} 구매사유`}
              value={group.reason}
              disabled={disabled}
              placeholder={`${PJT_PLACEHOLDER} EFEM 1공장`}
              maxLength={200}
              className="font-sans text-[12px]"
              onChange={(e) => patch({ reason: e.target.value })}
            />
          </Field>
        </div>

        {/* 2단 — 모듈(규격이 매칭 1순위 키). */}
        <div className="flex flex-col gap-2">
          <div className={cn(MODULE_COLS, 'px-1')}>
            <span className={MICRO}>규격</span>
            <span className={MICRO}>품명</span>
            <span aria-hidden />
          </div>

          {group.modules.map((module, mi) => (
            <div key={module.id} className={MODULE_COLS}>
              <Input
                aria-label={`${coord} 모듈 ${mi + 1} 규격`}
                value={module.spec}
                disabled={disabled}
                placeholder="EFEM-Frame Assy"
                maxLength={128}
                className="h-9 text-[12px]"
                onChange={(e) => patchModule(module.id, { spec: e.target.value })}
              />
              <Input
                aria-label={`${coord} 모듈 ${mi + 1} 품명`}
                value={module.name}
                disabled={disabled}
                placeholder="외주조립-F"
                maxLength={128}
                className="h-9 text-[12px]"
                onChange={(e) => patchModule(module.id, { name: e.target.value })}
              />
              <IconBtn
                label={`${coord} 모듈 ${mi + 1} 삭제`}
                onClick={() => patch({ modules: group.modules.filter((m) => m.id !== module.id) })}
                disabled={disabled || group.modules.length <= 1}
                title={group.modules.length <= 1 ? '모듈은 최소 1개가 필요합니다' : undefined}
                danger
              >
                <RiDeleteBinLine size={15} aria-hidden />
              </IconBtn>
            </div>
          ))}

          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() =>
                patch({
                  modules: [...group.modules, { id: newPatternId('m'), spec: '', name: '' }],
                })
              }
              disabled={disabled || group.modules.length >= MAX_GROUP_MODULES}
              title={
                group.modules.length >= MAX_GROUP_MODULES
                  ? `모듈은 최대 ${MAX_GROUP_MODULES}개까지 등록할 수 있습니다`
                  : undefined
              }
            >
              <RiAddLine size={15} aria-hidden />
              모듈 추가
            </Button>
            <p className="text-foreground-tertiary text-[11px] leading-relaxed">
              규격에 EFEM-/Process- 접두가 없으면 장비명으로 묶음을 판별해 매칭합니다.
            </p>
          </div>
        </div>

        {/* 3단 — 예외 규칙(계획서의 거래처 그룹 기본값을 덮는다). */}
        <div className="flex flex-col gap-2">
          <div className="flex items-baseline gap-2 px-1">
            <span className={MICRO}>예외 규칙</span>
            <span className="text-foreground-tertiary text-[11px] leading-relaxed">
              위에 있는 예외가 먼저 적용됩니다(납기·거래처·비고 각각 따로).
            </span>
          </div>

          {group.exceptions.map((exception, xi) => (
            <div
              key={exception.id}
              className="border-border-subtle bg-muted/25 flex flex-wrap items-end gap-2 rounded-[var(--radius-md)] border px-3 py-2.5"
            >
              <span className="text-foreground-tertiary self-center text-[11px] tabular-nums">
                {xi + 1}
              </span>
              <Field label="대상" className="w-28">
                <Select
                  aria-label={`${coord} 예외 ${xi + 1} 대상`}
                  value={exception.kind}
                  disabled={disabled}
                  className={SELECT}
                  onChange={(e) => {
                    const kind = e.target.value as ExceptionScopeKind;
                    // 거래처 대상 예외는 거래처를 다시 고정할 수 없다(자기참조) — 입력값을 비운다.
                    patchException(exception.id, {
                      kind,
                      ...(kind === 'vendor' ? { vendor: '' } : null),
                    });
                  }}
                >
                  {(Object.keys(SCOPE_LABELS) as ExceptionScopeKind[]).map((kind) => (
                    <option key={kind} value={kind}>
                      {SCOPE_LABELS[kind]}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="값" className="min-w-[7rem] flex-1">
                <Input
                  aria-label={`${coord} 예외 ${xi + 1} 대상 값`}
                  value={exception.value}
                  disabled={disabled}
                  placeholder={SCOPE_PLACEHOLDERS[exception.kind]}
                  maxLength={64}
                  className="h-9 text-[12px]"
                  onChange={(e) => patchException(exception.id, { value: e.target.value })}
                />
              </Field>
              <Field label="납기" className="w-32">
                <Select
                  aria-label={`${coord} 예외 ${xi + 1} 납기 기준일`}
                  value={exception.dueBase}
                  disabled={disabled}
                  className={SELECT}
                  onChange={(e) =>
                    patchException(exception.id, {
                      dueBase: e.target.value as ExceptionDraft['dueBase'],
                    })
                  }
                >
                  <option value="">변경 없음</option>
                  {BASE_DATE_KEYS.map((key) => (
                    <option key={key} value={key}>
                      {key}
                    </option>
                  ))}
                  <option value={PROCESSED_DUE_BASE}>{PROCESSED_DUE_BASE}</option>
                </Select>
              </Field>
              <Field label="주 전" className="w-[4.5rem]">
                <Input
                  type="number"
                  min={0}
                  max={MAX_OFFSET_WEEKS}
                  step={1}
                  inputMode="numeric"
                  aria-label={`${coord} 예외 ${xi + 1} 납기 주 전`}
                  value={exception.dueOffset}
                  disabled={disabled || exception.dueBase === ''}
                  className="h-9 px-2 text-[12px]"
                  onChange={(e) => patchException(exception.id, { dueOffset: e.target.value })}
                />
              </Field>
              <Field label="거래처 고정" className="min-w-[7rem] flex-1">
                <Input
                  aria-label={`${coord} 예외 ${xi + 1} 거래처 고정`}
                  value={exception.vendor}
                  disabled={disabled || exception.kind === 'vendor'}
                  placeholder={
                    exception.kind === 'vendor' ? '대상이 거래처면 불가' : '예: 한국메카트로닉스'
                  }
                  maxLength={64}
                  className="h-9 text-[12px]"
                  onChange={(e) => patchException(exception.id, { vendor: e.target.value })}
                />
              </Field>
              <Field label="비고" className="min-w-[9rem] flex-[1.4]">
                <Input
                  aria-label={`${coord} 예외 ${xi + 1} 비고`}
                  value={exception.note}
                  disabled={disabled}
                  placeholder="예: 직배송 가공품"
                  maxLength={200}
                  className="h-9 text-[12px]"
                  onChange={(e) => patchException(exception.id, { note: e.target.value })}
                />
              </Field>
              <div className="ml-auto flex shrink-0 items-center gap-0.5 self-center">
                <IconBtn
                  label={`${coord} 예외 ${xi + 1} 위로`}
                  onClick={() => moveException(xi, -1)}
                  disabled={disabled || xi === 0}
                >
                  <RiArrowUpSLine size={16} aria-hidden />
                </IconBtn>
                <IconBtn
                  label={`${coord} 예외 ${xi + 1} 아래로`}
                  onClick={() => moveException(xi, 1)}
                  disabled={disabled || xi === group.exceptions.length - 1}
                >
                  <RiArrowDownSLine size={16} aria-hidden />
                </IconBtn>
                <IconBtn
                  label={`${coord} 예외 ${xi + 1} 삭제`}
                  onClick={() =>
                    patch({ exceptions: group.exceptions.filter((x) => x.id !== exception.id) })
                  }
                  disabled={disabled}
                  danger
                >
                  <RiDeleteBinLine size={15} aria-hidden />
                </IconBtn>
              </div>
            </div>
          ))}

          <div>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() =>
                patch({
                  exceptions: [
                    ...group.exceptions,
                    {
                      id: newPatternId('x'),
                      kind: 'vendorClass',
                      value: '',
                      dueBase: '',
                      dueOffset: '0',
                      vendor: '',
                      note: '',
                    },
                  ],
                })
              }
              disabled={disabled || group.exceptions.length >= MAX_GROUP_EXCEPTIONS}
              title={
                group.exceptions.length >= MAX_GROUP_EXCEPTIONS
                  ? `예외는 최대 ${MAX_GROUP_EXCEPTIONS}개까지 등록할 수 있습니다`
                  : undefined
              }
            >
              <RiAddLine size={15} aria-hidden />
              예외 추가
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}

/** 라벨 + 컨트롤 한 칸 — 행이 좁아지면 줄바꿈되므로 라벨을 칸마다 달아둔다. */
function Field({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn('flex min-w-0 flex-col gap-1', className)}>
      <span className={MICRO}>{label}</span>
      {children}
    </div>
  );
}

function IconBtn({
  label,
  onClick,
  disabled,
  title,
  danger,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  title?: string;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={title ?? label}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'text-foreground-tertiary hover:bg-muted flex size-7 items-center justify-center rounded-[var(--radius-sm)] transition-colors disabled:cursor-not-allowed disabled:opacity-40',
        danger ? 'hover:text-danger' : 'hover:text-foreground',
      )}
    >
      {children}
    </button>
  );
}
