import type { Metadata } from 'next';
import localFont from 'next/font/local';
import { Toaster } from 'sonner';
import { ThemeProvider } from '@/components/theme-provider';
import './globals.css';

// Pretendard handles both Hangul and Latin in body copy.
const pretendard = localFont({
  src: './fonts/PretendardVariable.woff2',
  variable: '--font-pretendard',
  weight: '45 920',
  style: 'normal',
  display: 'swap',
  preload: true,
});

// Geist Sans is reserved for English/numeric display accents.
const geistSans = localFont({
  src: './fonts/Geist-Variable.woff2',
  variable: '--font-geist-sans',
  weight: '100 900',
  style: 'normal',
  display: 'swap',
  preload: false,
});

const geistMono = localFont({
  src: './fonts/GeistMono-Variable.woff2',
  variable: '--font-geist-mono',
  weight: '100 900',
  style: 'normal',
  display: 'swap',
  preload: false,
});

export const metadata: Metadata = {
  title: {
    default: 'NINEBELL',
    template: '%s · NINEBELL',
  },
  description: '나인벨 더존 옴니솔 자동화 대시보드',
  icons: {
    icon: '/favicon.ico',
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const fontClasses = `${pretendard.variable} ${geistSans.variable} ${geistMono.variable}`;

  return (
    <html lang="ko" suppressHydrationWarning className={fontClasses}>
      <body className="bg-background text-foreground min-h-dvh antialiased">
        <ThemeProvider
          attribute="class"
          defaultTheme="light"
          enableSystem
          disableTransitionOnChange
        >
          {children}
          <Toaster
            position="top-right"
            richColors
            closeButton
            toastOptions={{
              style: {
                borderRadius: 'var(--radius-md)',
                boxShadow: 'var(--shadow-card)',
              },
            }}
          />
        </ThemeProvider>
      </body>
    </html>
  );
}
