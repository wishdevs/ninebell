'use client';

import Image from 'next/image';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  RiBarChartBoxLine,
  RiRobot2Line,
  RiBriefcaseLine,
  RiFolderLine,
  RiHome5Line,
  RiPaletteLine,
  RiSettings3Line,
  RiUserSettingsLine,
  RiCloseLine,
  type RemixiconComponentType,
} from '@remixicon/react';
import { NAV_GROUPS, type NavIconKey } from '@/lib/data/nav';
import { cn } from '@/lib/utils';
import { useMobileNav } from './mobile-nav-context';
import { SidebarSession } from './sidebar-session';
import { SidebarUserCard } from './sidebar-user-card';

const ICONS: Record<NavIconKey, RemixiconComponentType> = {
  home: RiHome5Line,
  agents: RiRobot2Line,
  works: RiBriefcaseLine,
  analytics: RiBarChartBoxLine,
  projects: RiFolderLine,
  members: RiUserSettingsLine,
  settings: RiSettings3Line,
  design: RiPaletteLine,
};

export function Sidebar() {
  const pathname = usePathname();
  const { open: mobileOpen, closeDrawer } = useMobileNav();

  const inner = <SidebarInner pathname={pathname} />;

  return (
    <>
      <aside className="border-border relative z-30 hidden w-64 shrink-0 flex-col border-r md:flex">
        {inner}
      </aside>
      {mobileOpen ? (
        <div className="fixed inset-0 z-50 md:hidden" role="dialog" aria-modal="true">
          <button
            type="button"
            aria-label="메뉴 닫기"
            onClick={closeDrawer}
            className="absolute inset-0 bg-black/40 backdrop-blur-[2px]"
          />
          <aside className="sidebar-glass border-border animate-page-enter relative flex h-full w-72 max-w-[85vw] flex-col border-r shadow-[var(--shadow-overlay)]">
            <button
              type="button"
              onClick={closeDrawer}
              className="text-muted-foreground hover:text-foreground absolute top-3 right-3 inline-flex h-8 w-8 items-center justify-center rounded-[var(--radius-sm)] transition-colors"
              aria-label="메뉴 닫기"
            >
              <RiCloseLine size={16} aria-hidden />
            </button>
            {inner}
          </aside>
        </div>
      ) : null}
    </>
  );
}

function SidebarInner({ pathname }: { pathname: string | null }) {
  return (
    <>
      <div className="border-border-subtle shrink-0 border-b px-5 py-5">
        <Link href="/" aria-label="NINEBELL 홈" className="inline-flex items-center">
          <Image
            src="/ninebell-logo.png"
            alt="NINEBELL"
            width={2303}
            height={350}
            priority
            className="h-6 w-auto"
          />
        </Link>
      </div>
      <div className="flex-1 overflow-x-hidden overflow-y-auto">
        <nav className="flex flex-col gap-4 px-4 pt-4 pb-6">
          {NAV_GROUPS.map((group) => (
            <div key={group.label ?? '__home'} className="flex flex-col gap-0.5">
              {group.label ? (
                <p className="text-foreground-tertiary mt-4 mb-1.5 px-3 text-[10px] font-semibold tracking-widest uppercase">
                  {group.label}
                </p>
              ) : null}
              {group.items.map(({ href, label, icon, exact }) => {
                const Icon = ICONS[icon];
                const active = exact
                  ? pathname === href
                  : pathname === href || (href !== '/' && pathname?.startsWith(`${href}/`));
                return (
                  <Link
                    key={href}
                    href={href}
                    className={cn(
                      'relative flex items-center gap-3 rounded-[var(--radius-sm)] px-3 py-2.5 text-[length:var(--text-body)] transition-all duration-[var(--duration-fast)]',
                      active
                        ? 'bg-surface text-foreground ring-border/50 font-semibold shadow-sm ring-1'
                        : 'text-muted-foreground hover:text-foreground hover:bg-black/5 dark:hover:bg-white/5',
                    )}
                  >
                    <Icon size={18} aria-hidden />
                    {label}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
      </div>
      <div className="mt-auto">
        <SidebarSession />
        <SidebarUserCard />
      </div>
    </>
  );
}
