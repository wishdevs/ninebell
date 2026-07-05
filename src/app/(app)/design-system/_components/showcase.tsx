import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface ShowcaseProps {
  /** Uppercase eyebrow above the inset panel. Optional. */
  label?: string;
  children: ReactNode;
  className?: string;
}

/**
 * Inset showcase panel used inside the design-system SectionCards.
 *
 * Renders a labelled, bordered well on `bg-background` so demoed
 * components sit one layer below the surrounding `bg-surface` card —
 * giving the page a sense of depth instead of flat stacked rows.
 */
export function Showcase({ label, children, className }: ShowcaseProps) {
  return (
    <div className="flex flex-col gap-2">
      {label ? (
        <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
          {label}
        </p>
      ) : null}
      <div
        className={cn(
          'border-border bg-background flex flex-wrap items-center gap-4 rounded-[var(--radius-md)] border p-5',
          className,
        )}
      >
        {children}
      </div>
    </div>
  );
}

/**
 * One-glance usage snippet (import line / minimal call). Kept to a single
 * `<pre>` so sections stay scannable — link to the source file for details.
 */
export function Snippet({ code }: { code: string }) {
  return (
    <pre className="border-border bg-background text-foreground-secondary overflow-x-auto rounded-[var(--radius-sm)] border px-3 py-2 font-mono text-[11px] leading-relaxed">
      <code>{code}</code>
    </pre>
  );
}

interface DoDontProps {
  /** Things to do — rendered with a success-toned header. */
  doItems: ReadonlyArray<ReactNode>;
  /** Things to avoid — rendered with a danger-toned header. */
  dontItems: ReadonlyArray<ReactNode>;
}

/** Side-by-side Do / Don't rule card pair used across guide sections. */
export function DoDont({ doItems, dontItems }: DoDontProps) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="border-success/30 bg-success/5 flex flex-col gap-2 rounded-[var(--radius-md)] border p-4">
        <p className="text-success text-[length:var(--text-caption)] font-semibold tracking-[0.08em] uppercase">
          Do
        </p>
        <ul className="text-foreground-secondary flex list-disc flex-col gap-1.5 pl-4 text-[13px] leading-relaxed">
          {doItems.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      </div>
      <div className="border-danger/30 bg-danger/5 flex flex-col gap-2 rounded-[var(--radius-md)] border p-4">
        <p className="text-danger text-[length:var(--text-caption)] font-semibold tracking-[0.08em] uppercase">
          Don&apos;t
        </p>
        <ul className="text-foreground-secondary flex list-disc flex-col gap-1.5 pl-4 text-[13px] leading-relaxed">
          {dontItems.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
