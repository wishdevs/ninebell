import type { ReactNode } from 'react';

interface AuthPageHeaderProps {
  /** Required page title rendered as `<h1>`. */
  title: ReactNode;
  /** Optional eyebrow caption above the title (rendered uppercase, tracked). */
  caption?: ReactNode;
  /** Optional supporting copy below the title. */
  description?: ReactNode;
}

/**
 * Header for the `(auth)` route group (login/signup) — deliberately separate
 * from `@/components/ui/page-header` (`PageHeader`).
 *
 * `PageHeader`'s title uses `--text-section`, a `clamp()` tied to viewport
 * width — tuned for the dashboard's wide content canvas. The auth layout's
 * form column is pinned to `max-w-md` regardless of viewport, so a
 * viewport-relative title can grow out of proportion with the card on large
 * screens. This component uses the fixed `--text-heading` size instead, sized
 * for a narrow card rather than the dashboard's title role.
 *
 * Shared by login and signup so the two stay in sync — previously each page
 * hand-rolled this block independently (drifted, 2026-07-05 design audit).
 */
export function AuthPageHeader({ title, caption, description }: AuthPageHeaderProps) {
  return (
    <header className="grid gap-3">
      {caption ? (
        <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
          {caption}
        </p>
      ) : null}
      <h1 className="text-[length:var(--text-heading)] leading-[1.15] font-semibold tracking-[-0.01em]">
        {title}
      </h1>
      {description ? (
        <p className="text-muted-foreground text-[length:var(--text-body)] leading-relaxed">
          {description}
        </p>
      ) : null}
    </header>
  );
}
