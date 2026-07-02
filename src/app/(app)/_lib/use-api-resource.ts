'use client';

import { useCallback, useEffect, useState } from 'react';
import { ApiError, api, toApiError } from '@/lib/api/client';

/**
 * 단일 GET 리소스를 클라이언트에서 로드하는 경량 훅.
 *
 * 백엔드 세션은 httpOnly 쿠키라 브라우저에서만 첨부되므로 화면 데이터는
 * 클라이언트 컴포넌트에서 이 훅으로 가져온다. SWR/React Query를 들이지 않고
 * 화면 와이어링에 필요한 최소(로딩/성공/에러 + 재시도)만 제공한다.
 *
 * - `path`가 null이면 요청하지 않는다(권한이 없어 호출 자체가 무의미할 때).
 * - 네트워크 실패(백엔드 다운)는 `ApiError(0, ...)`로 정규화해 status로 분기 가능.
 * - `error.status`로 404(없음)·403(권한)·0(네트워크)을 구분한다.
 */

type ResourceState<T> =
  | { status: 'loading'; data: null; error: null }
  | { status: 'success'; data: T; error: null }
  | { status: 'error'; data: null; error: ApiError };

interface UseApiResourceResult<T> {
  status: ResourceState<T>['status'];
  data: T | null;
  error: ApiError | null;
  /** 동일 경로를 다시 가져온다(에러 후 재시도). */
  reload: () => void;
}

export function useApiResource<T>(path: string | null): UseApiResourceResult<T> {
  const [state, setState] = useState<ResourceState<T>>(
    path === null
      ? { status: 'success', data: null as T, error: null }
      : { status: 'loading', data: null, error: null },
  );

  const load = useCallback(() => {
    if (path === null) {
      return () => {};
    }
    let active = true;
    setState({ status: 'loading', data: null, error: null });
    api
      .get<T>(path)
      .then((data) => {
        if (active) {
          setState({ status: 'success', data, error: null });
        }
      })
      .catch((err: unknown) => {
        if (active) {
          setState({ status: 'error', data: null, error: toApiError(err) });
        }
      });
    return () => {
      active = false;
    };
  }, [path]);

  useEffect(() => load(), [load]);

  return {
    status: state.status,
    data: state.data,
    error: state.status === 'error' ? state.error : null,
    reload: load,
  };
}
