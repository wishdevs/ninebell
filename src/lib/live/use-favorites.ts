'use client';

import { useCallback, useState } from 'react';
import { toast } from 'sonner';
import { errorMessage } from '@/lib/api/client';
import { addFavorite, fetchFavorites, removeFavorite, type CatalogKind } from '@/lib/api/me-codes';

/**
 * 자주쓰는(즐겨찾기) 로컬 상태 — code→favId 맵. `reset(seed)` 로 초기 표시 상태를 시드하고
 * (id 미상 ''), `loadIds()` 가 REST 로 실제 id 를 채운다(삭제에 필요). 토글은 낙관적,
 * 실패 시 롤백+토스트. 백엔드가 아직 없을 수 있어 REST 실패는 조용히 무시한다(표시 상태는 유지).
 *
 * LiveGridCard(예산단위·프로젝트 ★)와 에이전트 목록/홈(kind='agent' ★)이 공용으로 쓴다.
 */
export function useFavorites(kind: CatalogKind) {
  const [ids, setIds] = useState<Record<string, string>>({});

  const reset = useCallback((seed: readonly { code: string }[]) => {
    setIds(Object.fromEntries(seed.map((s) => [s.code, ''] as const)));
  }, []);

  const loadIds = useCallback(async () => {
    try {
      const favs = await fetchFavorites(kind);
      setIds((prev) => {
        const next = { ...prev };
        for (const f of favs) next[f.code] = f.id;
        return next;
      });
    } catch {
      /* 백엔드 미배포 — 표시 상태만 유지 */
    }
  }, [kind]);

  const has = useCallback((code: string) => code in ids, [ids]);

  const toggle = useCallback(
    async (code: string, name: string, extra?: Record<string, string> | null) => {
      if (!code) return;
      if (code in ids) {
        const prevId = ids[code];
        setIds((p) => {
          const n = { ...p };
          delete n[code];
          return n;
        });
        try {
          let id = prevId;
          if (!id) {
            const favs = await fetchFavorites(kind);
            id = favs.find((f) => f.code === code)?.id ?? '';
          }
          if (id) await removeFavorite(id);
        } catch (err) {
          setIds((p) => ({ ...p, [code]: prevId }));
          toast.error(errorMessage(err, '자주쓰는 해제에 실패했습니다.'));
        }
      } else {
        setIds((p) => ({ ...p, [code]: '' }));
        try {
          const fav = await addFavorite({ kind, code, name, extra: extra ?? null });
          setIds((p) => ({ ...p, [code]: fav.id }));
        } catch (err) {
          setIds((p) => {
            const n = { ...p };
            delete n[code];
            return n;
          });
          toast.error(errorMessage(err, '자주쓰는 추가에 실패했습니다.'));
        }
      }
    },
    [ids, kind],
  );

  return { has, toggle, reset, loadIds };
}
