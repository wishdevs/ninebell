'use client';

import { Component, type ReactNode } from 'react';

interface ErrorBoundaryProps {
  children: ReactNode;
  /**
   * 크래시 시 대체 렌더. `reset`을 호출하면 바운더리 상태를 비우고 children 을
   * 다시 렌더한다(부모 상태는 유지 — 라이브 세션 등은 끊기지 않는다).
   */
  fallback: (args: { error: Error | null; reset: () => void }) => ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * 재사용 클래스형 에러 바운더리 — 렌더 예외를 자기 영역 안에 가둔다.
 *
 * Next 라우트 error.tsx 는 세그먼트 전체를 대체하므로, 화면 일부(예: 라이브
 * 스테이지 카드)만 격리하고 나머지 UI(헤더·컨트롤)는 살려야 할 때 이걸 쓴다.
 * React 에러 바운더리는 클래스 컴포넌트로만 만들 수 있다(getDerivedStateFromError).
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  reset = () => {
    this.setState({ error: null });
  };

  render() {
    if (this.state.error) {
      return this.props.fallback({ error: this.state.error, reset: this.reset });
    }
    return this.props.children;
  }
}
