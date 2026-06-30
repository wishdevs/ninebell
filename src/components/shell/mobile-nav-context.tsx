'use client';

import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';

interface MobileNavContextValue {
  open: boolean;
  openDrawer: () => void;
  closeDrawer: () => void;
}

const MobileNavContext = createContext<MobileNavContextValue | null>(null);

/**
 * 모바일 슬라이드인 사이드바 드로어 상태.
 *
 * 드로어 상태를 셸 레벨에 두어 토프바의 햄버거 버튼과 사이드바가 prop
 * drilling 없이 협력하게 한다. 경로가 바뀌면 자동으로 닫는다.
 */
export function MobileNavProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [state, setState] = useState<{ pathname: string | null; requested: boolean }>({
    pathname,
    requested: false,
  });
  const open = state.requested && state.pathname === pathname;

  const openDrawer = useCallback(() => {
    setState({ pathname, requested: true });
  }, [pathname]);
  const closeDrawer = useCallback(() => {
    setState((prev) => ({ pathname: prev.pathname, requested: false }));
  }, []);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') closeDrawer();
    }
    document.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = prev;
      document.removeEventListener('keydown', onKey);
    };
  }, [open, closeDrawer]);

  return (
    <MobileNavContext.Provider value={{ open, openDrawer, closeDrawer }}>
      {children}
    </MobileNavContext.Provider>
  );
}

export function useMobileNav(): MobileNavContextValue {
  const ctx = useContext(MobileNavContext);
  if (!ctx) {
    throw new Error('useMobileNav must be used inside MobileNavProvider');
  }
  return ctx;
}
