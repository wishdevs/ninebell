'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { SectionCard } from '@/components/ui/section-card';
import { Switch } from '@/components/ui/switch';
import { CURRENT_USER } from '@/lib/data/workspace';

interface NotificationToggle {
  key: string;
  title: string;
  description: string;
}

const NOTIFICATIONS: readonly NotificationToggle[] = [
  { key: 'email', title: '이메일 알림', description: '중요한 활동을 이메일로 받습니다.' },
  { key: 'weekly', title: '주간 리포트', description: '매주 월요일 오전 조직 활동 요약을 보냅니다.' },
  { key: 'member', title: '멤버 활동 알림', description: '멤버 초대·역할 변경 시 알림을 받습니다.' },
];

export function NotificationsTab() {
  const [toggles, setToggles] = useState<Record<string, boolean>>({
    email: true,
    weekly: true,
    member: false,
  });
  const [email, setEmail] = useState(CURRENT_USER.email);

  function setToggle(key: string, next: boolean) {
    setToggles((prev) => ({ ...prev, [key]: next }));
  }

  function handleSave() {
    toast.success('저장했습니다');
  }

  return (
    <SectionCard
      density="comfortable"
      caption="알림"
      title="알림 설정"
      description="조직 활동을 어떤 방식으로 받을지 설정합니다."
    >
      <ul className="flex flex-col gap-3">
        {NOTIFICATIONS.map((item) => (
          <li
            key={item.key}
            className="border-border-subtle bg-muted/30 flex items-center justify-between gap-4 rounded-[var(--radius-md)] border p-4"
          >
            <div className="grid min-w-0 gap-0.5">
              <span className="text-foreground text-sm font-medium">{item.title}</span>
              <span className="text-muted-foreground text-xs">{item.description}</span>
            </div>
            <Switch
              checked={toggles[item.key]}
              onCheckedChange={(next) => setToggle(item.key, next)}
              aria-label={item.title}
            />
          </li>
        ))}
      </ul>

      <FormField id="notify-email" label="수신 이메일" hint="알림과 리포트를 받을 주소입니다.">
        <Input
          id="notify-email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </FormField>

      <div className="border-border-subtle flex justify-end border-t pt-5">
        <Button type="button" onClick={handleSave}>
          변경 사항 저장
        </Button>
      </div>
    </SectionCard>
  );
}
