'use client';

import { RiSaveLine } from '@remixicon/react';
import { useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { FormField } from '@/components/ui/form-field';
import { InlineConfirm } from '@/components/ui/inline-confirm';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select-dropdown';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';

const RANGE_LABELS: Record<string, string> = {
  '7d': '최근 7일',
  '30d': '최근 30일',
  '90d': '최근 90일',
};

/**
 * Stateful form-control + tabs showcase. Split into a client island so the
 * surrounding page can stay a server component and export `metadata`.
 */
export function InteractiveDemos() {
  const [name, setName] = useState('');
  const [memo, setMemo] = useState('user.login.success');
  const [notify, setNotify] = useState(true);
  const [range, setRange] = useState('30d');
  const [confirmDelete, setConfirmDelete] = useState(false);

  return (
    <div className="grid gap-8 lg:grid-cols-2">
      <div className="flex flex-col gap-5">
        <FormField
          id="ds-name"
          label="표시 이름"
          required
          hint="목록과 헤더에 노출되는 이름입니다."
        >
          <Input
            id="ds-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="예: 신규 캠페인"
          />
        </FormField>

        <FormField id="ds-memo" label="메모" hint="모노스페이스 · 로그·식별자 입력에 사용합니다.">
          <Textarea id="ds-memo" value={memo} onChange={(e) => setMemo(e.target.value)} rows={3} />
        </FormField>

        <FormField id="ds-range" label="집계 기간" hint="대시보드 데이터 범위를 선택합니다.">
          <Select value={range} onValueChange={setRange}>
            <SelectTrigger
              id="ds-range"
              className="h-10 w-full justify-between rounded-sm px-3 text-sm"
            >
              <SelectValue>{RANGE_LABELS[range]}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="7d">최근 7일</SelectItem>
              <SelectItem value="30d">최근 30일</SelectItem>
              <SelectItem value="90d">최근 90일</SelectItem>
            </SelectContent>
          </Select>
        </FormField>

        <div className="border-border bg-background flex items-center justify-between gap-4 rounded-sm border px-3 py-2.5">
          <div className="flex min-w-0 flex-col">
            <Label>이메일 알림</Label>
            <span className="text-muted-foreground text-xs">
              새 활동이 있을 때 메일로 알립니다.
            </span>
          </div>
          <Switch checked={notify} onCheckedChange={setNotify} aria-label="이메일 알림 토글" />
        </div>

        <div>
          <Button size="sm" onClick={() => toast.success('저장했습니다.')}>
            <RiSaveLine size={14} /> 저장
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
          탭 · Tabs
        </p>
        <Tabs defaultValue="overview" className="flex flex-col gap-4">
          <TabsList>
            <TabsTrigger value="overview">개요</TabsTrigger>
            <TabsTrigger value="activity">활동</TabsTrigger>
            <TabsTrigger value="settings">설정</TabsTrigger>
          </TabsList>
          <TabsContent value="overview" className="text-muted-foreground text-sm leading-relaxed">
            라디스 기반 탭은 키보드 화살표 이동과 활성 상태 표시를 기본 제공합니다. 활성 탭은 하단
            보더로만 강조해 데이터에 방해되지 않습니다.
          </TabsContent>
          <TabsContent value="activity" className="text-muted-foreground text-sm leading-relaxed">
            최근 활동 스트림이 들어갈 영역입니다. 콘텐츠가 없을 때는 EmptyHint 로 대체합니다.
          </TabsContent>
          <TabsContent value="settings" className="text-muted-foreground text-sm leading-relaxed">
            설정 폼이 들어갈 영역입니다. 좌측 폼 컨트롤과 동일한 FormField · Input · Switch 패턴을
            재사용합니다.
          </TabsContent>
        </Tabs>
      </div>

      <div className="flex flex-col gap-3">
        <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
          인라인 확인 · InlineConfirm
        </p>
        <p className="text-muted-foreground text-sm leading-relaxed">
          모달 없이 되돌릴 수 없는 동작(삭제·중단)을 트리거 버튼 자리에서 바로 한 번 더 확인시킬 때
          사용합니다.
        </p>
        <div>
          {confirmDelete ? (
            <InlineConfirm
              question="삭제할까요?"
              confirmLabel="삭제"
              onConfirm={() => {
                setConfirmDelete(false);
                toast.success('삭제했습니다.');
              }}
              onCancel={() => setConfirmDelete(false)}
            />
          ) : (
            <Button size="sm" variant="danger" onClick={() => setConfirmDelete(true)}>
              삭제
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
