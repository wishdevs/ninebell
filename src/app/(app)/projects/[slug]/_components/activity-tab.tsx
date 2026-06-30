import { SectionCard } from '@/components/ui/section-card';
import { PROJECT_ACTIVITY } from '@/lib/data/projects';
import { formatRelativeKorean } from '@/lib/data/format';

/**
 * 활동 탭 — 프로젝트 타임라인. 좌측 점/연결선으로 시간 순 흐름을 표현한다.
 */
export function ActivityTab() {
  return (
    <SectionCard caption="기록" title="최근 활동" density="comfortable">
      <ol>
        {PROJECT_ACTIVITY.map((item, index) => {
          const isLast = index === PROJECT_ACTIVITY.length - 1;
          return (
            <li key={item.id} className="flex gap-3">
              <div className="flex flex-col items-center">
                <span
                  aria-hidden
                  className="bg-accent ring-accent/15 mt-1.5 h-2 w-2 shrink-0 rounded-full ring-4"
                />
                {!isLast ? (
                  <span aria-hidden className="bg-border-subtle my-1 w-px flex-1" />
                ) : null}
              </div>
              <div className={isLast ? 'pb-0.5' : 'pb-5'}>
                <p className="text-foreground text-sm">
                  <span className="font-semibold">{item.actor}</span>
                  <span className="text-foreground-secondary"> 님이 {item.action}</span>
                </p>
                <p className="text-foreground-secondary mt-0.5 text-sm">{item.target}</p>
                <p className="text-muted-foreground mt-1 text-xs tabular-nums">
                  {formatRelativeKorean(item.at)}
                </p>
              </div>
            </li>
          );
        })}
      </ol>
    </SectionCard>
  );
}
