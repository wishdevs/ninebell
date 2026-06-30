'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { SectionCard } from '@/components/ui/section-card';
import { Switch } from '@/components/ui/switch';
import { ACTIVE_WORKSPACE, type ModuleKey } from '@/lib/data/workspace';

interface ModuleDescriptor {
  key: ModuleKey;
  title: string;
  description: string;
}

const MODULES: readonly ModuleDescriptor[] = [
  { key: 'geo', title: 'GEO 모니터링', description: 'LLM 인용 분석과 브랜드 가시성을 추적합니다.' },
  { key: 'work', title: '업무', description: '프로젝트별 업무를 등록하고 진행 상태를 관리합니다.' },
  { key: 'ga', title: 'GA 대시보드', description: 'Google Analytics 지표를 블록 단위로 시각화합니다.' },
  { key: 'monitoring', title: '모니터링', description: '사이트 가용성과 Core Web Vitals를 추적합니다.' },
  {
    key: 'playbook',
    title: '플레이북',
    description: '업무 데이터를 기반으로 운영 가이드를 자동 큐레이션합니다.',
  },
  { key: 'projects', title: '프로젝트', description: '업무와 대시보드를 프로젝트 단위로 묶어 관리합니다.' },
];

export function ModulesTab() {
  const [enabled, setEnabled] = useState<Record<ModuleKey, boolean>>(() => {
    const active = new Set(ACTIVE_WORKSPACE.enabledModules);
    return MODULES.reduce(
      (acc, mod) => ({ ...acc, [mod.key]: active.has(mod.key) }),
      {} as Record<ModuleKey, boolean>,
    );
  });

  function toggle(key: ModuleKey, next: boolean) {
    setEnabled((prev) => ({ ...prev, [key]: next }));
  }

  function handleSave() {
    const count = MODULES.filter((mod) => enabled[mod.key]).length;
    toast.success(`모듈 ${count}개를 적용했습니다`);
  }

  return (
    <SectionCard
      density="comfortable"
      caption="기능 구성"
      title="사용 모듈"
      description="이 조직에서 사용할 모듈을 켜고 끕니다. 공통 메뉴(멤버, 조직 설정 등)는 항상 활성화됩니다."
    >
      <ul className="flex flex-col gap-3">
        {MODULES.map((mod) => {
          const isOn = enabled[mod.key];
          return (
            <li
              key={mod.key}
              className="border-border-subtle bg-muted/30 flex items-center justify-between gap-4 rounded-[var(--radius-md)] border p-4"
            >
              <div className="grid min-w-0 gap-0.5">
                <span className="text-foreground text-sm font-medium">{mod.title}</span>
                <span className="text-muted-foreground text-xs">{mod.description}</span>
              </div>
              <Switch
                checked={isOn}
                onCheckedChange={(next) => toggle(mod.key, next)}
                aria-label={`${mod.title} ${isOn ? '비활성화' : '활성화'}`}
              />
            </li>
          );
        })}
      </ul>

      <div className="border-border-subtle flex justify-end border-t pt-5">
        <Button type="button" onClick={handleSave}>
          변경 사항 저장
        </Button>
      </div>
    </SectionCard>
  );
}
