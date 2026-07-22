'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';

/**
 * 목록 화면 파라미터 소유 훅 — 필터·검색 디바운스·페이지 + URL 동기화(상시)를 단일 소유한다.
 *
 * 지금까지 members/audit/logs 가 각자 손으로 하던 것들이 여기 착지한다:
 * - 필터 변경·검색 안정화 시 page 1 자동 리셋
 * - 검색 인풋 즉시값(searchInput)과 디바운스 안정값(search)의 분리(기본 250ms)
 * - URL searchParams 동기화 — 초기값은 URL 에서 읽고(검색 'q'·페이지 'page'·필터는 키 이름
 *   그대로), 변경은 `window.history.replaceState` 로만 기록한다. next/navigation 의
 *   router.replace 는 RSC 재요청을 유발하므로 금지(docs/LIST-COMMONALIZATION.md 결정).
 *   기본값과 같은 필터·page=1·빈 q 는 URL 에서 제거해 깨끗한 URL 을 유지하고,
 *   검색은 디바운스 안정화 후에만 기록한다(타이핑마다 기록 금지).
 * - 정렬은 없다 — 6개 화면 전부 정렬 UI 가 없어 첫 요구 발생 시 `sort` 예약 키로 확장한다.
 *
 * 향후 저장된 필터·필터 프리셋 등 "전 화면 공통 파라미터 기능"의 1차 착지 지점.
 * 주의: useSearchParams 사용으로 소비 화면의 page.tsx 에는 `<Suspense>` 경계가 필요하다.
 */

const DEFAULT_SEARCH_DEBOUNCE_MS = 250;

interface ListParamsConfig<F extends Record<string, string>> {
  /** 필터 키와 기본값 — 예: { status: 'all' }. 기본값과 같으면 URL 에서 제거. */
  filters: F;
  /** 검색어 디바운스 ms. 기본 250. 검색이 없는 화면은 searchInput 을 안 쓰면 됨. */
  searchDebounceMs?: number;
}

interface ListParams<F extends Record<string, string>> {
  /** 인풋 즉시값 — <SearchInput value> 에 바인딩. */
  searchInput: string;
  setSearchInput: (v: string) => void;
  /** 디바운스 안정화된 검색어 — 요청/필터링에 쓰는 값. */
  search: string;
  filters: F;
  setFilter: <K extends keyof F>(key: K, value: F[K]) => void;
  /** 1-indexed — Pagination 과 동일 규약(pagination.tsx). */
  page: number;
  setPage: (page: number) => void;
  /** 기본값과 다른 조건이 하나라도 있는가(검색 포함) — 초기화 버튼 노출·빈 상태 문구 분기용. */
  isFiltered: boolean;
  reset: () => void;
}

/** URL 의 page 값을 1-indexed 정수로 파싱. 비정상 값은 1 로 폴백. */
function parsePage(raw: string | null): number {
  const parsed = Number(raw);
  return Number.isInteger(parsed) && parsed >= 1 ? parsed : 1;
}

export function useListParams<F extends Record<string, string>>(
  config: ListParamsConfig<F>,
): ListParams<F> {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // 기본값은 최초 렌더 시점에 고정 — 소비 화면이 리터럴로 넘겨도 정체성 변화에 흔들리지 않는다.
  const defaultsRef = useRef(config.filters);
  const debounceMs = config.searchDebounceMs ?? DEFAULT_SEARCH_DEBOUNCE_MS;

  // 초기값은 URL 에서 읽는다 — 새로고침/공유 시 목록 상태 유지(web/patterns.md 'URL As State').
  const [searchInput, setSearchInput] = useState(() => searchParams.get('q') ?? '');
  const [search, setSearch] = useState(searchInput);
  const [filters, setFilters] = useState<F>(() => {
    const initial: Record<string, string> = { ...defaultsRef.current };
    for (const key of Object.keys(initial)) {
      const fromUrl = searchParams.get(key);
      if (fromUrl !== null) initial[key] = fromUrl;
    }
    return initial as F;
  });
  const [page, setPage] = useState(() => parsePage(searchParams.get('page')));

  // 검색 디바운스 — 안정화 시점에만 search 를 갱신하고 page 를 1 로 리셋한다.
  useEffect(() => {
    if (searchInput === search) return;
    const timer = setTimeout(() => {
      setSearch(searchInput);
      setPage(1);
    }, debounceMs);
    return () => clearTimeout(timer);
  }, [searchInput, search, debounceMs]);

  const setFilter = useCallback(<K extends keyof F>(key: K, value: F[K]) => {
    setFilters((prev) => ({ ...prev, [key]: value }) as F);
    setPage(1);
  }, []);

  const reset = useCallback(() => {
    setSearchInput('');
    setSearch('');
    setFilters(defaultsRef.current);
    setPage(1);
  }, []);

  // URL 동기화 — 소유 키(q·page·필터 키)만 갱신하고 그 외 쿼리 키는 보존한다.
  // replaceState 라 히스토리 오염·RSC 재요청이 없다.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (search !== '') params.set('q', search);
    else params.delete('q');
    for (const key of Object.keys(defaultsRef.current)) {
      if (filters[key] !== defaultsRef.current[key]) params.set(key, filters[key]);
      else params.delete(key);
    }
    if (page > 1) params.set('page', String(page));
    else params.delete('page');
    const qs = params.toString();
    window.history.replaceState(null, '', qs ? `${pathname}?${qs}` : pathname);
  }, [search, filters, page, pathname]);

  // 초기화 버튼 노출은 인풋 즉시값 기준 — 타이핑 즉시 노출(기존 members/audit 동작과 동일).
  const isFiltered =
    searchInput.trim() !== '' ||
    Object.keys(defaultsRef.current).some((key) => filters[key] !== defaultsRef.current[key]);

  return {
    searchInput,
    setSearchInput,
    search,
    filters,
    setFilter,
    page,
    setPage,
    isFiltered,
    reset,
  };
}
