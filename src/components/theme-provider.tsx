'use client';

import { ThemeProvider as NextThemesProvider } from 'next-themes';
import type { ComponentProps } from 'react';

// React 19 + Next 16 false-positive warning suppression.
// next-themes renders an inline <script> via createElement, which React 19's
// reconciler logs even though the script DOES execute (via SSR HTML). Per
// shadcn-ui/ui#10104 the canonical workaround is to narrowly filter this
// exact warning in dev.
if (typeof window !== 'undefined' && process.env.NODE_ENV === 'development') {
  const orig = console.error;
  console.error = (...args: unknown[]) => {
    if (typeof args[0] === 'string' && args[0].includes('Encountered a script tag')) {
      return;
    }
    orig.apply(console, args);
  };
}

export function ThemeProvider(props: ComponentProps<typeof NextThemesProvider>) {
  return <NextThemesProvider {...props} />;
}

// Re-export the hook so consumers don't need to import next-themes directly.
export { useTheme } from 'next-themes';
