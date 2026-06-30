import { cn } from '@/lib/utils';

export type Sentiment = 'positive' | 'neutral' | 'negative';

const SENTIMENT_CLASSES: Record<Sentiment, string> = {
  positive: 'bg-success/10 text-success',
  neutral: 'bg-muted text-muted-foreground',
  negative: 'bg-danger/10 text-danger',
};

const SENTIMENT_LABEL: Record<Sentiment, string> = {
  positive: '긍정',
  neutral: '중립',
  negative: '부정',
};

export interface SentimentBadgeProps {
  sentiment: Sentiment;
  className?: string;
}

export function SentimentBadge({ sentiment, className }: SentimentBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold',
        SENTIMENT_CLASSES[sentiment],
        className,
      )}
    >
      {SENTIMENT_LABEL[sentiment]}
    </span>
  );
}
