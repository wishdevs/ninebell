import Link from 'next/link';
import {
  RiAlertLine,
  RiArrowRightLine,
  RiNotification3Line,
  RiInformationLine,
} from '@remixicon/react';
import { EmptyState } from '@/components/ui/empty-state';
import { SectionCard } from '@/components/ui/section-card';
import type { HomeAlert, HomeAlertSeverity } from '@/lib/data/home';
import { formatRelativeKorean } from '@/lib/data/format';
import { cn } from '@/lib/utils';

interface WelcomeAlertFeedProps {
  alerts: readonly HomeAlert[];
}

const SEVERITY_ICON: Record<HomeAlertSeverity, typeof RiAlertLine> = {
  urgent: RiAlertLine,
  warning: RiAlertLine,
  info: RiInformationLine,
};

/**
 * 알림 배지 톤. Pill 프리미티브 대신 인라인으로 둔 이유는 홈 알림 팔레트가
 * 의도된 신호등이기 때문이다: 빨강(urgent) / 주황(warning) / 파랑(info).
 */
const SEVERITY_TONE: Record<HomeAlertSeverity, string> = {
  urgent: 'text-danger bg-danger/10 ring-danger/30',
  warning: 'text-warning bg-warning/10 ring-warning/30',
  info: 'text-info bg-info/10 ring-info/30',
};

/**
 * 홈 상단 액션 피드. 다음으로 조치가 필요한 고-신호 항목 3~4건을 보여준다.
 * 항목을 클릭하면 해당 모듈 페이지로 이동한다. 항목이 없으면 빈 셸 대신
 * `EmptyState`를 띄워 표면이 의도된 상태로 보이게 한다.
 */
export function WelcomeAlertFeed({ alerts }: WelcomeAlertFeedProps) {
  return (
    <SectionCard
      density="comfortable"
      caption="액션 필요"
      title="확인이 필요한 항목"
      description="모듈에서 자동 감지된 우선순위 작업입니다. 클릭하면 해당 페이지로 이동합니다."
    >
      {alerts.length === 0 ? (
        <EmptyState
          icon={<RiNotification3Line size={18} aria-hidden />}
          title="처리할 항목이 없습니다"
          description="모니터링/모듈에서 새 알림이 발생하면 이 영역에 표시됩니다."
          compact
        />
      ) : (
        <ul className="divide-border-subtle flex flex-col divide-y">
          {alerts.map((alert) => (
            <li key={alert.id}>
              <AlertRow alert={alert} />
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}

function AlertRow({ alert }: { alert: HomeAlert }) {
  const Icon = SEVERITY_ICON[alert.severity];
  const relativeTime = formatRelativeKorean(alert.occurredAt);
  return (
    <Link
      href={alert.href}
      className="hover:bg-muted/40 group flex items-center justify-between gap-4 px-1 py-3 transition-colors"
      aria-label={`${alert.title} — ${alert.ctaLabel}`}
    >
      <div className="flex min-w-0 items-start gap-3">
        <span
          aria-hidden
          className={cn(
            'mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full ring-1',
            SEVERITY_TONE[alert.severity],
          )}
        >
          <Icon size={14} />
        </span>
        <div className="grid min-w-0 gap-0.5">
          <p className="text-foreground truncate text-sm font-medium">{alert.title}</p>
          <p className="text-muted-foreground text-xs leading-relaxed">
            <span className="text-foreground-tertiary font-mono">{relativeTime}</span>
            {alert.detail ? <span className="mx-1.5">·</span> : null}
            {alert.detail}
          </p>
        </div>
      </div>
      <span className="text-muted-foreground group-hover:text-foreground inline-flex shrink-0 items-center gap-1 text-xs font-medium transition-colors">
        {alert.ctaLabel}
        <RiArrowRightLine size={12} aria-hidden />
      </span>
    </Link>
  );
}
