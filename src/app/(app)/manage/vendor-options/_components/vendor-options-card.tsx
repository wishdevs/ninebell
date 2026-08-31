'use client';

import { useLayoutEffect, useRef, useState } from 'react';
import { RiCloseLine, RiDraggable } from '@remixicon/react';
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
 * 추가는 **거래처 카탈로그 검색뿐**이다 — ERP 화면 ③(구매발주일괄입력)의 변경 거래처
 * 코드피커가 이름으로 대조하므로, 카탈로그의 실명과 일치해야 적용이 된다(tax-invoice 선례).
 * ERP 가 데이터 단일 소스라 직접 입력 폴백은 두지 않는다(제거 2026-08-31) — 거래처 등록은
 * ERP 에서 한다.
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

  // 재배열 애니메이션(FLIP) — 순서가 바뀐 행은 직전 위치에서 새 위치로 transform 으로 미끄러진다.
  // 레이아웃 속성이 아닌 transform 만 쓰고, 축소 모션 설정이면 건너뛴다.
  const rowRefs = useRef(new Map<string, HTMLLIElement>());
  const lastTops = useRef(new Map<string, number>());
  useLayoutEffect(() => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const nextTops = new Map<string, number>();
    for (const [name, el] of rowRefs.current) {
      const top = el.getBoundingClientRect().top;
      nextTops.set(name, top);
      const prev = lastTops.current.get(name);
      if (reduce || prev == null || prev === top) continue;
      el.style.transition = 'none';
      el.style.transform = `translateY(${prev - top}px)`;
      // 미끄러지는 동안은 히트테스트에서 뺀다 — 커서 아래를 지나는 행이 dragover 를 받아
      // 되돌아가는(왕복) 오작동 방지.
      el.style.pointerEvents = 'none';
      requestAnimationFrame(() => {
        el.style.transition = 'transform 180ms cubic-bezier(0.16, 1, 0.3, 1)';
        el.style.transform = '';
      });
      window.setTimeout(() => {
        el.style.pointerEvents = '';
      }, 200);
    }
    lastTops.current = nextTops;
  }, [rows]);

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
              ref={(el) => {
                if (el) rowRefs.current.set(r.name, el);
                else rowRefs.current.delete(r.name);
              }}
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
    </div>
  );
}
