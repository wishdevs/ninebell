'use client';

import { memo } from 'react';
import { RiTvLine } from '@remixicon/react';

interface LiveScreenProps {
  /** 최신 스크린캐스트 dataURL('data:image/jpeg;base64,...'). 없으면 placeholder. */
  src: string | null;
  /** 세션이 라이브(연결/진행)인지 — placeholder 문구를 좌우한다. */
  live: boolean;
  alt?: string;
}

/**
 * 라이브 스크린캐스트 뷰. 부모(라이브 브라우저 스테이지, ≈16:10) 박스를 object-contain 으로
 * 채운다 — 잘림 없이 스크린캐스트 전체 프레임을 보여주고, 종횡비를 맞춰 레터박스도 최소화한다.
 *
 * `src` 만 의존하도록 `memo` 로 감싼다 — CDP 스크린캐스트가 프레임을 빠르게 보내도
 * 이 컴포넌트만 갱신되고(부모 리렌더는 skip), 단계/로그/채팅은 함께 재렌더되지 않는다.
 */
export const LiveScreen = memo(function LiveScreen({
  src,
  live,
  alt = '헤드리스 브라우저 화면',
}: LiveScreenProps) {
  if (src) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- dataURL 스트림이라 next/image 부적합
      <img
        src={src}
        alt={alt}
        className="bg-surface-raised absolute inset-0 h-full w-full object-contain"
      />
    );
  }
  return (
    <div className="border-border-strong/60 text-foreground-tertiary absolute inset-3 flex flex-col items-center justify-center gap-2 rounded-[var(--radius-md)] border border-dashed text-center">
      <RiTvLine size={26} aria-hidden />
      <p className="text-foreground-secondary text-[length:var(--text-body-sm)] font-medium">
        {live ? '화면 캡처 대기 중…' : '라이브 화면 없음'}
      </p>
      <p className="max-w-xs text-[11px] leading-relaxed">
        {live
          ? '에이전트가 화면을 조작하기 시작하면 여기에 실시간으로 표시됩니다.'
          : '실행을 시작하면 더존 옴니솔 화면이 이 영역에 라이브로 표시됩니다.'}
      </p>
    </div>
  );
});
