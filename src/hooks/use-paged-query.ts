'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, toApiError } from '@/lib/api/client';

/**
 * 서버 페이징 로더 훅 — audit/logs 가 각자 복제하던 "Phase 상태 + loadPage + effect 재조회"
 * 보일러플레이트가 여기 착지한다. 응답 키가 화면마다 달라({logs}·{runs}·{items}) 화면별
 * fetcher 어댑터 한 줄로 정규형 `Page<T>{rows,total}` 에 맞춰 넘긴다.
 *
 * - fetcher 정체성 또는 page 변경 시 재조회 — 화면은 useCallback 으로 fetcher 를 만들고
 *   검색어/필터를 클로저에 넣는다(기존 "loadPage useCallback 재생성 → effect 재조회" 시맨틱).
 * - fetcher 가 null 이면 요청하지 않는다(권한 게이트 — use-api-resource.ts 의 path:null 관례 계승).
 * - 경쟁 방지는 요청 세대 카운터 — effect 재조회뿐 아니라 reload() 로 시작한 요청도 다음
 *   load 가 세대를 올리며 무효화한다(늦은 응답이 새 결과를 덮어쓰지 못한다).
 * - opts.setPage 를 전달하면 스테일 URL(북마크/공유)의 page 오버플로를 마지막 페이지로
 *   자동 클램프한다 — 빈 상태가 Pagination 을 삼켜 복구 UI 가 사라지는 것을 방지.
 * - 에러는 lib/api/client 의 toApiError 로 정규화(status 0 = 네트워크).
 *
 * 향후 자동 새로고침/폴링 등 "전 화면 공통 페칭 기능"의 착지 지점.
 */

/** 서버 페이지 응답의 정규형 — 응답 키 이원화(logs/runs/items)는 어댑터에서 통일한다. */
export interface Page<T> {
  rows: T[];
  total: number;
}

export type ListPhase = 'loading' | 'ready' | 'error';

interface PagedQueryResult<T> {
  rows: T[];
  total: number;
  phase: ListPhase;
  error: ApiError | null;
  /** 현재 파라미터로 재요청 — '다시 시도' 버튼에 연결. */
  reload: () => void;
}

interface PagedQueryState<T> {
  rows: T[];
  total: number;
  phase: ListPhase;
  error: ApiError | null;
}

export function usePagedQuery<T>(
  /** null 이면 요청하지 않음 — 권한 게이트. */
  fetcher: ((args: { limit: number; offset: number }) => Promise<Page<T>>) | null,
  opts: {
    page: number;
    pageSize: number;
    /** 전달 시 page 오버플로(총 페이지수 초과)를 마지막 페이지로 자동 클램프 — useListParams 의 setPage. */
    setPage?: (page: number) => void;
  },
): PagedQueryResult<T> {
  const { page, pageSize, setPage } = opts;
  const [state, setState] = useState<PagedQueryState<T>>({
    rows: [],
    total: 0,
    phase: fetcher === null ? 'ready' : 'loading',
    error: null,
  });
  // 요청 세대 — load 마다 증가. 이전 세대의 늦은 응답은 무시된다(reload 포함 전 경로).
  const genRef = useRef(0);

  const load = useCallback(() => {
    if (fetcher === null) {
      return () => {};
    }
    const gen = ++genRef.current;
    // 이전 rows/total 은 유지한 채 phase 만 전환 — 기존 audit/logs 와 동일 시맨틱.
    setState((prev) => ({ ...prev, phase: 'loading', error: null }));
    fetcher({ limit: pageSize, offset: (page - 1) * pageSize })
      .then(({ rows, total }) => {
        if (gen !== genRef.current) return;
        // 스테일 URL 의 page 가 실제 총 페이지수를 넘으면 빈 목록을 그리지 않고 마지막
        // 페이지로 클램프 — page 변경이 재조회를 잇는다(phase 는 loading 유지).
        if (setPage && rows.length === 0 && total > 0 && page > 1) {
          setPage(Math.max(1, Math.ceil(total / pageSize)));
          return;
        }
        setState({ rows, total, phase: 'ready', error: null });
      })
      .catch((err: unknown) => {
        if (gen !== genRef.current) return;
        setState((prev) => ({ ...prev, phase: 'error', error: toApiError(err) }));
      });
    return () => {
      // 언마운트/의존성 교체 시 현재 세대 무효화(다음 load 는 어차피 세대를 올린다).
      if (gen === genRef.current) genRef.current += 1;
    };
  }, [fetcher, page, pageSize, setPage]);

  useEffect(() => load(), [load]);

  return {
    rows: state.rows,
    total: state.total,
    phase: state.phase,
    error: state.error,
    reload: load,
  };
}
