import { BookOpen, ClipboardCheck } from 'lucide-react';
import type { PlaybookInsight } from '@/lib/data/home';
import { formatRelativeKorean } from '@/lib/data/format';
import { InsightCardShell } from './insight-card-shell';

interface InsightCardPlaybookProps {
  data: PlaybookInsight;
}

/**
 * 플레이북 — 최신 버전 핀 + 갱신 상대시간 + 리뷰 대기 수.
 * Wide 카드(span=12)라 좌측 버전, 우측 리뷰 대기 스트립으로 균형을 잡는다.
 */
export function InsightCardPlaybook({ data }: InsightCardPlaybookProps) {
  const updatedRelative = formatRelativeKorean(data.latestUpdatedAt);

  return (
    <InsightCardShell label={data.label} caption={data.caption} href={data.href} hint={data.hint}>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="grid gap-1.5">
          <p className="text-foreground-tertiary inline-flex items-center gap-1.5 text-[10px] tracking-[0.06em] uppercase">
            <BookOpen size={11} strokeWidth={2} aria-hidden />
            현재 버전
          </p>
          <p className="font-display text-foreground text-2xl leading-none font-semibold tracking-tight tabular-nums">
            {data.latestVersion}
          </p>
          <p className="text-muted-foreground text-xs">{updatedRelative} 갱신</p>
        </div>
        <div className="grid gap-1.5">
          <p className="text-foreground-tertiary inline-flex items-center gap-1.5 text-[10px] tracking-[0.06em] uppercase">
            <ClipboardCheck size={11} strokeWidth={2} aria-hidden />
            리뷰 대기
          </p>
          <p className="font-display text-foreground text-2xl leading-none font-semibold tracking-tight tabular-nums">
            {data.pendingReviewCount}
            <span className="text-muted-foreground ml-1 text-sm font-normal">건</span>
          </p>
          <p className="text-muted-foreground text-xs">
            {data.pendingReviewCount > 0 ? '관리자 검토 필요' : '검토 대기 없음'}
          </p>
        </div>
      </div>
    </InsightCardShell>
  );
}
