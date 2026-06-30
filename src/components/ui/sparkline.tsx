interface SparklineProps {
  /** 데이터 포인트(좌→우). 비거나 1점이면 평평한 기준선으로 폴백. */
  values: readonly number[];
  width?: number;
  height?: number;
  /** Tailwind text-color 클래스 — stroke는 currentColor. */
  className?: string;
  ariaLabel?: string;
}

/**
 * 작은 인라인 스파크라인. viewBox로 width/height에 맞춰 스케일되며 축/라벨
 * 없이 장식적으로 동작한다. KPI 카드용.
 */
export function Sparkline({
  values,
  width = 96,
  height = 28,
  className = 'text-accent',
  ariaLabel,
}: SparklineProps) {
  const points = values.length > 0 ? values : [0, 0];
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;

  const path = points
    .map((value, idx) => {
      const x = points.length === 1 ? 0 : (idx / (points.length - 1)) * 100;
      const y = 30 - ((value - min) / range) * 26 - 2;
      return `${idx === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(' ');

  return (
    <svg
      width={width}
      height={height}
      viewBox="0 0 100 30"
      preserveAspectRatio="none"
      role={ariaLabel ? 'img' : undefined}
      aria-label={ariaLabel}
      aria-hidden={ariaLabel ? undefined : true}
      className={className}
    >
      <path
        d={path}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.75}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
