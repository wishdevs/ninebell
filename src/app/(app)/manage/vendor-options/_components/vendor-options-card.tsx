'use client';

import { useState } from 'react';
import { RiCloseLine, RiDraggable } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { CatalogCombobox, type ComboOption } from '@/components/live/pre-run/catalog-combobox';
import { fetchCatalog } from '@/lib/api/me-codes';
import {
  MAX_VENDOR_NAME_LEN,
  MAX_VENDOR_OPTIONS_PER_CLASS,
  VENDOR_CLASSES,
  type VendorClass,
  type VendorOptions,
} from '@/lib/purchase/vendor-options';
import { cn } from '@/lib/utils';

/** 거래처 카탈로그 검색 건수 — 이름 일부 검색이라 넉넉히. */
const SEARCH_LIMIT = 30;

interface VendorOptionsFieldsProps {
  value: VendorOptions;
  disabled?: boolean;
  onChange: (next: VendorOptions) => void;
}

/**
 * 통합 지정 거래처 후보 편집 필드(분류 3열) — 계획서 콤보박스(통합 지정·발주단위 거래처
 * 그룹)의 선택지를 편집한다. 카드 셸·저장 바는 클라이언트(vendor-options-client)가 소유한다.
 *
 * 추가는 **거래처 카탈로그 검색**이 기본이다 — ERP 화면 ③(구매발주일괄입력)의 변경 거래처
 * 코드피커가 이름으로 대조하므로, 카탈로그의 실명과 일치해야 적용이 된다(tax-invoice 선례).
 * 카탈로그에 없는 거래처만 직접 입력으로 추가한다.
 */
export function VendorOptionsFields({
  value,
  disabled = false,
  onChange,
}: VendorOptionsFieldsProps) {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {VENDOR_CLASSES.map((vendorClass) => (
        <ClassColumn
          key={vendorClass}
          vendorClass={vendorClass}
          rows={value[vendorClass]}
          disabled={disabled}
          onChange={(rows) => onChange({ ...value, [vendorClass]: rows })}
        />
      ))}
    </div>
  );
}

function ClassColumn({
  vendorClass,
  rows,
  disabled,
  onChange,
}: {
  vendorClass: VendorClass;
  rows: VendorOptions[VendorClass];
  disabled: boolean;
  onChange: (rows: VendorOptions[VendorClass]) => void;
}) {
  // 카탈로그에 없는 거래처용 폴백 — 검색 추가가 기본이고, 직접 입력은 접혀 있다.
  const [manual, setManual] = useState(false);
  const [manualName, setManualName] = useState('');
  const full = rows.length >= MAX_VENDOR_OPTIONS_PER_CLASS;

  function add(name: string): void {
    const trimmed = name.trim().slice(0, MAX_VENDOR_NAME_LEN);
    if (!trimmed || full) return;
    if (rows.some((r) => r.name === trimmed)) return; // 중복은 조용히 무시(이미 목록에 있음).
    onChange([...rows, { name: trimmed, isDefault: rows.length === 0 }]);
  }

  function remove(name: string): void {
    const rest = rows.filter((r) => r.name !== name);
    // 기본 거래처를 지우면 첫 행이 기본을 이어받는다(빈 목록은 저장 검증이 막는다).
    if (rest.length > 0 && !rest.some((r) => r.isDefault)) {
      rest[0] = { ...rest[0], isDefault: true };
    }
    onChange(rest);
  }

  function setDefault(name: string): void {
    onChange(rows.map((r) => ({ ...r, isDefault: r.name === name })));
  }

  // 드래그 순서 변경(2026-08-28) — 같은 분류 안에서만. 저장 순서 = 계획서 콤보박스 노출 순서.
  // 끌고 있는 행은 다른 행 위를 지나는 순간 그 자리로 **즉시 이동**한다(예상 위치 미리보기) —
  // 드롭 대상 강조 방식이 아니라, 놓기 전에 결과 순서가 그대로 보인다.
  const [dragName, setDragName] = useState<string | null>(null);

  function move(from: string, to: string): void {
    if (from === to) return;
    const fi = rows.findIndex((r) => r.name === from);
    const ti = rows.findIndex((r) => r.name === to);
    if (fi < 0 || ti < 0) return;
    const next = [...rows];
    const [moved] = next.splice(fi, 1);
    next.splice(ti, 0, moved);
    onChange(next);
  }

  return (
    <div className="border-border-subtle flex min-w-0 flex-col gap-2.5 rounded-[var(--radius-md)] border p-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-foreground text-[length:var(--text-body-sm)] font-semibold">
          {vendorClass}
        </span>
        <span className="text-foreground-tertiary text-[11px] tabular-nums">
          {rows.length}/{MAX_VENDOR_OPTIONS_PER_CLASS}
        </span>
      </div>

      {rows.length === 0 ? (
        <p className="text-warning text-[11px]">거래처를 1개 이상 등록해야 저장할 수 있습니다.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {rows.map((r) => (
            <li
              key={r.name}
              draggable={!disabled}
              onDragStart={(e) => {
                e.dataTransfer.effectAllowed = 'move';
                e.dataTransfer.setData('text/plain', r.name);
                setDragName(r.name);
              }}
              onDragOver={(e) => {
                if (!dragName) return;
                e.preventDefault(); // 드롭 허용.
                e.dataTransfer.dropEffect = 'move';
                if (dragName !== r.name) move(dragName, r.name); // 지나는 자리로 즉시 이동.
              }}
              onDrop={(e) => e.preventDefault()}
              onDragEnd={() => setDragName(null)}
              className={cn(
                'border-border/60 bg-surface flex items-center gap-2 rounded-[var(--radius-sm)] border px-2 py-1.5 transition-colors',
                // 끌고 있는 행 — 자리는 실시간으로 바뀌고, 표시는 테두리+배경(포커스링 미사용).
                dragName === r.name ? 'border-accent bg-accent/10' : '',
              )}
            >
              <span
                aria-hidden
                className={cn(
                  'text-foreground-tertiary shrink-0',
                  disabled ? 'opacity-40' : 'cursor-grab active:cursor-grabbing',
                )}
                title="드래그해서 순서 변경"
              >
                <RiDraggable size={14} />
              </span>
              <span className="text-foreground min-w-0 flex-1 truncate text-[length:var(--text-body-sm)]">
                {r.name}
              </span>
              <button
                type="button"
                disabled={disabled}
                onClick={() => setDefault(r.name)}
                title={r.isDefault ? '계획서 첫 진입값' : '기본 거래처로 지정'}
                className={cn(
                  'shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold',
                  r.isDefault
                    ? 'border-accent/40 bg-accent/10 text-accent'
                    : 'border-border text-foreground-tertiary hover:text-foreground',
                  'disabled:opacity-50',
                )}
              >
                기본
              </button>
              <button
                type="button"
                disabled={disabled}
                onClick={() => remove(r.name)}
                aria-label={`${r.name} 삭제`}
                className="text-foreground-tertiary hover:text-danger flex size-6 shrink-0 items-center justify-center disabled:opacity-50"
              >
                <RiCloseLine size={14} aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}

      {/* 추가 — 거래처 카탈로그 검색이 기본(ERP 실명 일치 보장). */}
      <CatalogCombobox
        value={{ code: '', name: '' }}
        placeholder={full ? '최대 개수에 도달했습니다' : '거래처 검색해 추가'}
        favorites={[]}
        disabled={disabled || full}
        search={async (q): Promise<ComboOption[]> => {
          const page = await fetchCatalog({ kind: 'partner', q, limit: SEARCH_LIMIT });
          return page.items.map((it) => ({ code: it.code, name: it.name }));
        }}
        onSelect={(opt) => add(opt.name)}
        onClear={() => {}}
      />
      <div>
        <button
          type="button"
          disabled={disabled}
          onClick={() => setManual((v) => !v)}
          className="text-accent hover:text-accent/80 text-[11px] font-semibold underline underline-offset-2 disabled:opacity-50"
        >
          {manual ? '검색으로 추가하기' : '카탈로그에 없나요? 직접 입력'}
        </button>
      </div>
      {manual ? (
        <div className="flex gap-2">
          <Input
            value={manualName}
            disabled={disabled || full}
            placeholder="거래처명 그대로 입력"
            maxLength={MAX_VENDOR_NAME_LEN}
            onChange={(e) => setManualName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                add(manualName);
                setManualName('');
              }
            }}
          />
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={disabled || full || !manualName.trim()}
            onClick={() => {
              add(manualName);
              setManualName('');
            }}
          >
            추가
          </Button>
        </div>
      ) : null}
    </div>
  );
}
