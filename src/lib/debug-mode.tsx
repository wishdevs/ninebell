'use client';

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';

/**
 * 디버그 모드 — 로그인 시 켜는 클라이언트 전용 UI 모드.
 *
 * 켜면 메뉴·기능이 조금 달라진다(대표적으로 사이드바 AI 모델 스위치 노출,
 * 변경사항·개발 메뉴와 홈 푸시 알람 테스트 노출, 회계전표의 상신 미클릭). 서버와 무관한 화면 표시
 * 전용 플래그라 localStorage 에만 담고(로그인 '아이디 저장'과 동일 계층), 컨텍스트로
 * 앱 전역에 배포한다. 로그인 폼은 (app) 프로바이더 밖이므로 read/write 헬퍼를 직접 쓴다.
 */
const DEBUG_MODE_KEY = 'nb_debug_mode';

/** localStorage 에서 디버그 모드 여부를 읽는다(SSR·차단 환경이면 false). */
export function readDebugMode(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.localStorage.getItem(DEBUG_MODE_KEY) === '1';
  } catch {
    return false;
  }
}

/** 디버그 모드 여부를 localStorage 에 기록한다(끄면 키 제거). */
export function writeDebugMode(on: boolean): void {
  if (typeof window === 'undefined') return;
  try {
    if (on) window.localStorage.setItem(DEBUG_MODE_KEY, '1');
    else window.localStorage.removeItem(DEBUG_MODE_KEY);
  } catch {
    /* 저장 실패는 무시 — 디버그 모드는 부가 기능이라 조용히 넘어간다. */
  }
}

interface DebugModeValue {
  debugMode: boolean;
  setDebugMode: (on: boolean) => void;
}

const DebugModeContext = createContext<DebugModeValue | null>(null);

/**
 * 디버그 모드 제공자. SSR·초기 하이드레이션은 false 로 시작하고(서버/클라 일치 →
 * 하이드레이션 불일치 없음), 마운트 후 localStorage 값을 반영한다.
 */
export function DebugModeProvider({ children }: { children: ReactNode }) {
  const [debugMode, setDebugModeState] = useState(false);

  useEffect(() => {
    setDebugModeState(readDebugMode());
  }, []);

  const setDebugMode = useCallback((on: boolean) => {
    writeDebugMode(on);
    setDebugModeState(on);
  }, []);

  return (
    <DebugModeContext.Provider value={{ debugMode, setDebugMode }}>
      {children}
    </DebugModeContext.Provider>
  );
}

/** 현재 디버그 모드 여부. 제공자 밖이면 false(안전 기본값). */
export function useDebugMode(): boolean {
  return useContext(DebugModeContext)?.debugMode ?? false;
}

/** 디버그 모드를 켜고 끄는 setter. 제공자 밖 호출은 예외. */
export function useSetDebugMode(): (on: boolean) => void {
  const ctx = useContext(DebugModeContext);
  if (!ctx) {
    throw new Error('useSetDebugMode must be used inside <DebugModeProvider>');
  }
  return ctx.setDebugMode;
}
