'use client';

import Link from 'next/link';
import { RiBookOpenLine, RiErrorWarningLine } from '@remixicon/react';
import { PageHeader } from '@/components/ui/page-header';
import { Spinner } from '@/components/ui/spinner';
import { EmptyState } from '@/components/ui/empty-state';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { Agent } from '@/lib/data/agents';
import { useApiResource } from '@/app/(app)/_lib/use-api-resource';

/** 왼쪽 분류의 한 섹션 — 지금은 에이전트 그룹에서 파생하지만, 항목이 에이전트가 아니어도 된다. */
interface ManualSection {
  label: string;
  items: { id: string; name: string }[];
}

/**
 * 에이전트 목록을 그룹별 문서 섹션으로 변환한다(등장 순서 유지).
 * 그룹 소속 섹션이 먼저, 무그룹은 '기타' 섹션으로 마지막에 둔다.
 */
function manualSections(agents: readonly Agent[]): ManualSection[] {
  const byLabel = new Map<string, ManualSection>();
  const standalone: ManualSection = { label: '기타', items: [] };
  for (const agent of agents) {
    const item = { id: agent.id, name: agent.name };
    if (!agent.group) {
      standalone.items.push(item);
      continue;
    }
    const section = byLabel.get(agent.group.id);
    if (section) {
      section.items.push(item);
    } else {
      byLabel.set(agent.group.id, { label: agent.group.name, items: [item] });
    }
  }
  const sections = [...byLabel.values()];
  if (standalone.items.length > 0) sections.push(standalone);
  return sections;
}

/**
 * 메뉴얼 — 왼쪽 분류(그룹별 문서 목록) + 오른쪽 본문.
 *
 * 문서 목록은 `GET /agents`에서 파생한다(에이전트 목록과 동일 소스·동일 노출 규칙).
 * 각 문서는 `/manual/{id}` 고유 주소를 가지며, 본문은 아직 공백(준비 중)이다.
 * `docId`가 없으면(/manual) 안내 화면을 보여준다.
 */
export function ManualClient({ docId }: { docId?: string }) {
  const { status, data, error, reload } = useApiResource<Agent[]>('/agents');

  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-6">
      <PageHeader
        caption="도움말"
        title="메뉴얼"
        description="에이전트별 사용 방법을 설명하는 문서입니다. 왼쪽 목록에서 문서를 선택하세요."
      />

      {status === 'loading' ? (
        <div className="text-muted-foreground flex items-center justify-center gap-2 py-16 text-sm">
          <Spinner size={18} label="문서 목록 불러오는 중" />
          문서 목록을 불러오는 중…
        </div>
      ) : status === 'error' ? (
        <EmptyState
          icon={<RiErrorWarningLine size={18} aria-hidden />}
          title="문서 목록을 불러오지 못했습니다"
          description={error?.status === 0 ? '서버에 연결할 수 없습니다.' : (error?.message ?? '')}
          action={
            <Button variant="secondary" size="sm" onClick={reload}>
              다시 시도
            </Button>
          }
        />
      ) : (
        (() => {
          const sections = manualSections(data ?? []);
          const selected = docId ? (data ?? []).find((agent) => agent.id === docId) : undefined;
          return (
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-[220px_minmax(0,1fr)] lg:items-start">
              {/* 왼쪽 분류 — 그룹 라벨 + 문서 링크. 데스크톱에선 스크롤을 따라온다. */}
              <nav aria-label="메뉴얼 문서 목록" className="flex flex-col gap-4 lg:sticky lg:top-6">
                {sections.map((section) => (
                  <div key={section.label} className="flex flex-col gap-0.5">
                    <p className="text-foreground-tertiary mb-1 px-3 text-[10px] font-semibold tracking-widest uppercase">
                      {section.label}
                    </p>
                    {section.items.map((item) => (
                      <Link
                        key={item.id}
                        href={`/manual/${item.id}`}
                        className={cn(
                          'rounded-[var(--radius-sm)] px-3 py-2 text-[length:var(--text-body-sm)] transition-colors',
                          item.id === docId
                            ? 'bg-surface text-foreground ring-border/50 font-semibold shadow-sm ring-1'
                            : 'text-muted-foreground hover:text-foreground hover:bg-black/5 dark:hover:bg-white/5',
                        )}
                      >
                        {item.name}
                      </Link>
                    ))}
                  </div>
                ))}
              </nav>

              {/* 본문 — 선택된 문서 헤딩 + 공백(준비 중) 본문. */}
              <section className="border-border bg-surface min-h-[420px] rounded-[var(--radius-lg)] border p-6">
                {selected ? (
                  <div className="flex flex-col gap-2">
                    {selected.group ? (
                      <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
                        {selected.group.name}
                      </p>
                    ) : null}
                    <h2 className="text-foreground text-[length:var(--text-heading)] leading-tight font-semibold tracking-tight">
                      {selected.name}
                    </h2>
                    <p className="text-muted-foreground mt-4 text-sm leading-relaxed">
                      문서 준비 중입니다.
                    </p>
                  </div>
                ) : docId ? (
                  <EmptyState
                    title="문서를 찾을 수 없습니다"
                    description="주소가 잘못되었거나 삭제된 문서입니다. 왼쪽 목록에서 다시 선택하세요."
                  />
                ) : (
                  <EmptyState
                    icon={<RiBookOpenLine size={18} aria-hidden />}
                    title="문서를 선택하세요"
                    description="왼쪽 목록에서 보고 싶은 메뉴얼을 선택하면 이곳에 내용이 표시됩니다."
                  />
                )}
              </section>
            </div>
          );
        })()
      )}
    </div>
  );
}
