'use client';

import { RiAddLine, RiDeleteBinLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';
import { MAX_MENU_ITEMS, newMenuItemId, type VoucherMenuItem } from '@/lib/voucher/menu-items';

/** 한 행 검증 — 이름이 비어있지 않아야 한다(id 는 자동 생성이라 항상 유효). */
export function isMenuItemValid(row: VoucherMenuItem): boolean {
  return row.label.trim().length > 0;
}

/**
 * 메뉴 필터 항목 편집기 — 관리자가 행을 추가/삭제하고 이름(ERP 메뉴 표시명)과 기본 선택을
 * 편집한다. 이름은 ERP 그리드의 '메뉴' 텍스트와 그대로 대조되므로 표시명을 정확히 적어야 한다.
 * 제어 컴포넌트: value(초안 목록)/onChange 를 부모(AgentSettingsCard)가 소유한다.
 */
export function MenuItemsEditor({
  value,
  disabled,
  onChange,
}: {
  value: VoucherMenuItem[];
  disabled?: boolean;
  onChange: (next: VoucherMenuItem[]) => void;
}) {
  const update = (id: string, patch: Partial<VoucherMenuItem>) =>
    onChange(value.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  const remove = (id: string) => onChange(value.filter((r) => r.id !== id));
  const add = () =>
    onChange([...value, { id: newMenuItemId(), label: '', defaultSelected: false }]);

  const atLimit = value.length >= MAX_MENU_ITEMS;

  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-[1fr_5rem_1.75rem] items-center gap-2 px-1">
        <span className="text-foreground-tertiary text-[10px] font-semibold tracking-wider uppercase">
          메뉴 이름
        </span>
        <span className="text-foreground-tertiary text-[10px] font-semibold tracking-wider uppercase">
          기본 선택
        </span>
        <span aria-hidden />
      </div>

      {value.map((row, idx) => (
        <div key={row.id} className="grid grid-cols-[1fr_5rem_1.75rem] items-center gap-2">
          <Input
            aria-label={`${idx + 1}행 메뉴 이름`}
            value={row.label}
            disabled={disabled}
            placeholder="예: 매출등록 / 수출비용입력[나인벨]"
            onChange={(e) => update(row.id, { label: e.target.value })}
          />
          <Switch
            checked={row.defaultSelected}
            disabled={disabled}
            aria-label={`${idx + 1}행 기본 선택`}
            onCheckedChange={(next) => update(row.id, { defaultSelected: next })}
          />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className={cn('text-foreground-tertiary hover:text-danger px-0')}
            onClick={() => remove(row.id)}
            disabled={disabled || value.length <= 1}
            aria-label={`${idx + 1}번째 메뉴 항목 삭제`}
            title={value.length <= 1 ? '최소 1개는 있어야 합니다' : undefined}
          >
            <RiDeleteBinLine size={15} aria-hidden />
          </Button>
        </div>
      ))}

      <div>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={add}
          disabled={disabled || atLimit}
          title={atLimit ? `최대 ${MAX_MENU_ITEMS}개까지 등록할 수 있습니다` : undefined}
        >
          <RiAddLine size={15} aria-hidden />
          메뉴 항목 추가
        </Button>
      </div>
    </div>
  );
}
