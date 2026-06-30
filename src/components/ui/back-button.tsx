'use client';

import { useRouter } from 'next/navigation';
import { RiArrowLeftLine } from '@remixicon/react';
import { cn } from '@/lib/utils';

export interface BackButtonProps {
  /** Visible label (usually the parent page's title). */
  label: string;
  /**
   * Absolute path used when no browser history is available — e.g. the user
   * opened the detail page via deep link or pasted URL. Without this the
   * button would no-op and leave the user stranded.
   */
  fallback: string;
  /** Optional override for the wrapping className. */
  className?: string;
  /** Icon size — defaults to 14px to match the previous Link-based buttons. */
  iconSize?: number;
}

const BASE_CLASSES =
  'text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs transition-colors focus-visible:ring-accent/40 focus-visible:ring-2 focus-visible:outline-none rounded-[var(--radius-sm)]';

/**
 * Navigates back in browser history when possible, falling back to the
 * provided canonical parent path when the detail page was entered via a
 * deep link and history length is 1. Keeping the visual treatment matched
 * to the original Link-based breadcrumb so the swap is invisible.
 */
export function BackButton({ label, fallback, className, iconSize = 14 }: BackButtonProps) {
  const router = useRouter();

  function handleClick() {
    if (typeof window !== 'undefined' && window.history.length > 1) {
      router.back();
      return;
    }
    router.push(fallback);
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      className={cn(BASE_CLASSES, className)}
      aria-label={`${label}으로 돌아가기`}
    >
      <RiArrowLeftLine size={iconSize} /> {label}
    </button>
  );
}
