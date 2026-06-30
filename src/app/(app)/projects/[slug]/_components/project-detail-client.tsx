'use client';

import { useState } from 'react';
import { BarChart3, CalendarDays, ListChecks, Pencil, Share2, Users } from 'lucide-react';
import { toast } from 'sonner';
import { BackButton } from '@/components/ui/back-button';
import { Button } from '@/components/ui/button';
import { StatusPill } from '@/components/ui/status-pill';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { PROJECT_STATUS_LABEL, type Project, type ProjectStatus } from '@/lib/data/projects';
import { formatDate, formatPercent } from '@/lib/data/format';
import { OverviewTab } from './overview-tab';
import { WorksTab } from './works-tab';
import { ActivityTab } from './activity-tab';
import { FilesTab } from './files-tab';

interface ProjectDetailClientProps {
  project: Project;
}

type PillVariant = 'success' | 'warn' | 'info' | 'danger';

const STATUS_VARIANT: Record<ProjectStatus, PillVariant> = {
  active: 'success',
  paused: 'warn',
  archived: 'info',
};

const TABS = [
  { value: 'overview', label: '개요' },
  { value: 'works', label: '업무' },
  { value: 'activity', label: '활동' },
  { value: 'files', label: '파일' },
] as const;

export function ProjectDetailClient({ project }: ProjectDetailClientProps) {
  const [tab, setTab] = useState<string>('overview');

  const meta = [
    { icon: BarChart3, label: '진행률', value: formatPercent(project.progress, 0) },
    {
      icon: ListChecks,
      label: '업무',
      value: `열린 ${project.openWorkCount} / 전체 ${project.workCount}`,
    },
    { icon: Users, label: '멤버', value: `${project.members.length}명` },
    { icon: CalendarDays, label: '생성', value: formatDate(project.createdAt) },
  ];

  return (
    <div className="flex max-w-[var(--content-max)] flex-col gap-6">
      <header className="flex flex-col gap-4">
        <BackButton label="프로젝트" fallback="/projects" />

        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="flex min-w-0 gap-3">
            <span
              aria-hidden
              className="mt-1 h-9 w-1.5 shrink-0 rounded-full"
              style={{ backgroundColor: project.color }}
            />
            <div className="grid min-w-0 gap-2">
              <div className="flex flex-wrap items-center gap-2.5">
                <h1 className="text-[length:var(--text-heading)] leading-tight font-semibold tracking-tight">
                  {project.name}
                </h1>
                <StatusPill
                  label={PROJECT_STATUS_LABEL[project.status]}
                  variant={STATUS_VARIANT[project.status]}
                />
              </div>
              <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
                {project.description}
              </p>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => toast('편집 화면은 준비 중입니다.')}
            >
              <Pencil size={14} aria-hidden /> 편집
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => toast.success('공유 링크를 클립보드에 복사했습니다.')}
            >
              <Share2 size={14} aria-hidden /> 공유
            </Button>
          </div>
        </div>

        <dl className="border-border-subtle flex flex-wrap items-center gap-x-6 gap-y-2 border-t pt-4">
          {meta.map(({ icon: Icon, label, value }) => (
            <div key={label} className="flex items-center gap-2">
              <Icon size={15} className="text-foreground-tertiary shrink-0" aria-hidden />
              <dt className="text-muted-foreground text-xs">{label}</dt>
              <dd className="text-foreground text-sm font-medium tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
      </header>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="overflow-x-auto">
          {TABS.map(({ value, label }) => (
            <TabsTrigger key={value} value={value}>
              {label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="overview" className="pt-6">
          <OverviewTab project={project} />
        </TabsContent>
        <TabsContent value="works" className="pt-6">
          <WorksTab project={project} />
        </TabsContent>
        <TabsContent value="activity" className="pt-6">
          <ActivityTab />
        </TabsContent>
        <TabsContent value="files" className="pt-6">
          <FilesTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
