'use client';

import { useEffect, useState } from 'react';
import { ThinkingOrb as BaseOrb, type ThinkingOrbProps } from 'thinking-orbs';

/**
 * ThinkingOrb 래퍼 — AI 계산 중 표시용 canvas 오브(thinking-orbs).
 *
 * 원본은 requestAnimationFrame 기반 canvas 라 globals.css 의 prefers-reduced-motion
 * 전역 블록(CSS 애니메이션만 차단)이 못 잡는다. 여기서 미디어쿼리를 구독해 reduced-motion
 * 이면 `paused`(첫 프레임 정지)로 넘겨 접근성을 지킨다. 테마는 원본 auto 감지(data-theme
 * 속성 MutationObserver)가 이 리포 Tailwind 규약과 맞물려 그대로 동작한다.
 *
 * size 는 원본이 64(아바타)·20(인라인) 두 프리셋만 지원 — 그 외 값은 타입에서 막힌다.
 */
export function ThinkingOrb(props: ThinkingOrbProps) {
  const reduced = usePrefersReducedMotion();
  return <BaseOrb paused={reduced} {...props} />;
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    setReduced(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setReduced(e.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);
  return reduced;
}
