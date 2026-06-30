'use client';

import { useState } from 'react';
import { PageHeader } from '@/components/ui/page-header';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ACTIVE_WORKSPACE } from '@/lib/data/workspace';
import { DangerTab } from './danger-tab';
import { GeneralTab } from './general-tab';
import { ModulesTab } from './modules-tab';
import { NotificationsTab } from './notifications-tab';

const TABS = [
  { value: 'general', label: '일반' },
  { value: 'modules', label: '모듈' },
  { value: 'notifications', label: '알림' },
  { value: 'danger', label: '위험 구역' },
] as const;

/**
 * 조직 설정의 클라이언트 셸. 활성 탭만 소유하고, 각 탭은 자기 폼 상태와
 * 저장 토스트를 스스로 관리한다(탭 간 격리 → 작은 파일 유지).
 */
export function SettingsClient() {
  const [tab, setTab] = useState<string>('general');

  return (
    <div className="flex max-w-[var(--content-max)] flex-col gap-8">
      <PageHeader
        caption="워크스페이스"
        title="조직 설정"
        description={`${ACTIVE_WORKSPACE.name} 워크스페이스의 기본 정보와 사용 모듈, 알림 수신 방식을 한곳에서 관리합니다.`}
      />

      <Tabs value={tab} onValueChange={setTab} className="flex flex-col gap-6">
        <TabsList className="no-scrollbar overflow-x-auto">
          {TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="general">
          <GeneralTab />
        </TabsContent>
        <TabsContent value="modules">
          <ModulesTab />
        </TabsContent>
        <TabsContent value="notifications">
          <NotificationsTab />
        </TabsContent>
        <TabsContent value="danger">
          <DangerTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
