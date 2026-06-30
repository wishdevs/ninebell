'use client';

import { useState } from 'react';
import { Check } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { SectionCard } from '@/components/ui/section-card';
import { ACTIVE_WORKSPACE } from '@/lib/data/workspace';
import { cn } from '@/lib/utils';

interface ColorSwatch {
  value: string;
  label: string;
}

/**
 * 식별 색상 프리셋. 라이트/다크 양쪽에서 안전하도록 hex 대신 oklch 문자열을
 * 쓴다(동적 데이터 색상은 inline style 허용). 첫 값은 ACTIVE_WORKSPACE.color와
 * 일치해 초기 선택 상태가 된다.
 */
const COLOR_SWATCHES: readonly ColorSwatch[] = [
  { value: 'oklch(56% 0.21 258)', label: '블루' },
  { value: 'oklch(64% 0.17 150)', label: '그린' },
  { value: 'oklch(68% 0.16 40)', label: '오렌지' },
  { value: 'oklch(58% 0.22 27)', label: '레드' },
  { value: 'oklch(62% 0.2 300)', label: '바이올렛' },
  { value: 'oklch(64% 0.13 200)', label: '시안' },
];

export function GeneralTab() {
  const [name, setName] = useState(ACTIVE_WORKSPACE.name);
  const [color, setColor] = useState<string>(ACTIVE_WORKSPACE.color ?? COLOR_SWATCHES[0].value);

  function handleSave() {
    toast.success('저장했습니다');
  }

  return (
    <SectionCard
      density="comfortable"
      caption="기본 정보"
      title="일반"
      description="조직 이름과 식별 색상을 설정합니다. 슬러그는 생성 후 변경할 수 없습니다."
    >
      <FormField
        id="org-name"
        label="조직 이름"
        required
        hint="사이드바와 멤버 초대 화면에 표시됩니다."
      >
        <Input
          id="org-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={60}
        />
      </FormField>

      <FormField id="org-slug" label="슬러그" hint="URL 식별자입니다. 변경할 수 없습니다.">
        <Input id="org-slug" value={ACTIVE_WORKSPACE.slug} readOnly disabled />
      </FormField>

      <div className="grid gap-2">
        <span className="text-foreground text-sm font-medium">식별 색상</span>
        <div role="group" aria-label="조직 식별 색상" className="flex flex-wrap gap-2.5">
          {COLOR_SWATCHES.map((swatch) => {
            const isSelected = color === swatch.value;
            return (
              <button
                key={swatch.value}
                type="button"
                aria-label={`${swatch.label}${isSelected ? ' (선택됨)' : ''}`}
                aria-pressed={isSelected}
                onClick={() => setColor(swatch.value)}
                className={cn(
                  'ring-offset-background focus-visible:ring-accent relative flex h-9 w-9 items-center justify-center rounded-full transition-transform duration-200 hover:scale-110 focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none',
                  isSelected ? 'ring-foreground ring-2 ring-offset-2' : '',
                )}
                style={{ backgroundColor: swatch.value }}
              >
                {isSelected ? (
                  <Check size={14} strokeWidth={2.5} className="text-white" aria-hidden />
                ) : null}
              </button>
            );
          })}
        </div>
        <p className="text-muted-foreground text-xs">사이드바에서 조직을 빠르게 구분할 때 쓰입니다.</p>
      </div>

      <div className="border-border-subtle flex justify-end border-t pt-5">
        <Button type="button" onClick={handleSave}>
          변경 사항 저장
        </Button>
      </div>
    </SectionCard>
  );
}
