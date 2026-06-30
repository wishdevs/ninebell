import { forwardRef } from 'react';
import { cn } from '@/lib/utils';

export type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>;

/**
 * Multi-line text input. Mirrors the {@link Input} component's
 * border / focus / disabled states so a form mixing single-line
 * inputs and textareas reads as one cohesive surface.
 */
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, rows = 4, ...props }, ref) => {
    return (
      <textarea
        ref={ref}
        rows={rows}
        className={cn(
          'border-border text-foreground placeholder:text-muted-foreground flex w-full rounded-sm border bg-white px-3 py-2 text-sm shadow-xs transition-all duration-200 outline-none',
          'dark:bg-surface-raised',
          'focus-visible:border-accent focus-visible:ring-accent focus-visible:ring-2',
          'aria-invalid:border-danger aria-invalid:ring-danger aria-invalid:ring-2',
          'disabled:cursor-not-allowed disabled:opacity-50',
          'font-mono text-xs leading-relaxed',
          className,
        )}
        {...props}
      />
    );
  },
);
Textarea.displayName = 'Textarea';
