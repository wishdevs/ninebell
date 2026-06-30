import { forwardRef } from 'react';
import { cn } from '@/lib/utils';

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, type = 'text', ...props }, ref) => {
    return (
      <input
        ref={ref}
        type={type}
        className={cn(
          'border-border text-foreground placeholder:text-muted-foreground flex h-10 w-full rounded-sm border bg-white px-3 py-2 text-sm shadow-xs transition-all duration-200 outline-none',
          'dark:bg-surface-raised',
          'focus-visible:border-accent focus-visible:ring-accent focus-visible:ring-2',
          'aria-invalid:border-danger aria-invalid:ring-danger aria-invalid:ring-2',
          'disabled:cursor-not-allowed disabled:opacity-50',
          className,
        )}
        {...props}
      />
    );
  },
);
Input.displayName = 'Input';
