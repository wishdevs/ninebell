import { RiArrowDownSLine } from '@remixicon/react';
import { forwardRef } from 'react';
import { cn } from '@/lib/utils';

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  wrapperClassName?: string;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, wrapperClassName, children, ...props }, ref) => {
    return (
      <span className={cn('relative inline-flex w-full', wrapperClassName)}>
        <select
          ref={ref}
          className={cn(
            'border-border bg-surface text-foreground flex h-10 w-full appearance-none rounded-sm border py-2 pr-9 pl-3 text-sm',
            'focus-visible:ring-accent focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none',
            'disabled:cursor-not-allowed disabled:opacity-50',
            className,
          )}
          {...props}
        >
          {children}
        </select>
        <RiArrowDownSLine
          aria-hidden="true"
          className="text-foreground-tertiary pointer-events-none absolute top-1/2 right-3 h-3 w-3 -translate-y-1/2"
        />
      </span>
    );
  },
);
Select.displayName = 'Select';
