'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  RiArrowDownSLine,
  RiArrowUpSLine,
  RiDeleteBinLine,
  RiErrorWarningLine,
  RiRefreshLine,
  RiSearchLine,
  RiStarFill,
  RiStarLine,
} from '@remixicon/react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { Input } from '@/components/ui/input';
import { Pagination } from '@/components/ui/pagination';
import { SectionCard } from '@/components/ui/section-card';
import { Spinner } from '@/components/ui/spinner';
import { errorMessage } from '@/lib/api/client';
import {
  addFavorite,
  fetchCatalog,
  fetchFavorites,
  fetchSyncStatus,
  removeFavorite,
  reorderFavorites,
  startCatalogSync,
  type CatalogItem,
  type CatalogKind,
  type Favorite,
  type SyncStatus,
} from '@/lib/api/me-codes';
import { formatDateTime } from '@/lib/data/format';
import { cn } from '@/lib/utils';

const PAGE_SIZE = 50;
const SYNC_POLL_MS = 3000;
const SEARCH_DEBOUNCE_MS = 300;

interface CodeCatalogManagerProps {
  kind: CatalogKind;
  caption: string;
  title: string;
  description: string;
  /** 예산단위 — '전체 부서' 토글 노출(기본은 내 부서). */
  supportsDept?: boolean;
  /** 프로젝트 — 서버 검색 입력 노출(2,000+ 항목). */
  supportsSearch?: boolean;
}

/**
 * 코드(예산단위·프로젝트) 관리 — 자주쓰는(순서변경·삭제) + 전체 카탈로그(★ 토글) +
 * ERP 동기화(진행 중 3초 폴링). 예산단위는 부서 필터 토글, 프로젝트는 서버 검색을 갖는다.
 * 두 관리 화면이 로직을 공유하므로 kind 로 매개변수화한 단일 컴포넌트로 둔다.
 */
export function CodeCatalogManager({
  kind,
  caption,
  title,
  description,
  supportsDept = false,
  supportsSearch = false,
}: CodeCatalogManagerProps) {
  const [favorites, setFavorites] = useState<Favorite[]>([]);
  const [busy, setBusy] = useState(false);

  const [items, setItems] = useState<CatalogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [syncedAt, setSyncedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [page, setPage] = useState(1);
  const [deptAll, setDeptAll] = useState(false);
  const [queryInput, setQueryInput] = useState('');
  const [query, setQuery] = useState('');

  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [polling, setPolling] = useState(false);

  const favByCode = useMemo(() => {
    const m = new Map<string, Favorite>();
    for (const f of favorites) m.set(f.code, f);
    return m;
  }, [favorites]);

  const loadFavorites = useCallback(async () => {
    try {
      setFavorites(await fetchFavorites(kind));
    } catch (err) {
      toast.error(errorMessage(err, '자주쓰는 목록을 불러오지 못했습니다.'));
    }
  }, [kind]);

  const loadCatalog = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const res = await fetchCatalog({
        kind,
        q: supportsSearch && query ? query : undefined,
        dept: supportsDept && deptAll ? 'all' : undefined,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      });
      setItems(res.items);
      setTotal(res.total);
      setSyncedAt(res.syncedAt);
    } catch (err) {
      setLoadError(errorMessage(err, '카탈로그를 불러오지 못했습니다.'));
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [kind, supportsSearch, query, supportsDept, deptAll, page]);

  useEffect(() => {
    void loadFavorites();
  }, [loadFavorites]);

  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog]);

  // 초기 동기화 상태 확인 — 이미 실행 중이면 폴링을 켠다.
  useEffect(() => {
    let active = true;
    fetchSyncStatus(kind)
      .then((s) => {
        if (!active) return;
        setSync(s);
        if (s.running) setPolling(true);
      })
      .catch(() => {
        /* 백엔드 미배포 — 무시 */
      });
    return () => {
      active = false;
    };
  }, [kind]);

  // 검색어 디바운스(프로젝트) — 입력 후 300ms 안정되면 서버 질의, 페이지 1로.
  useEffect(() => {
    if (!supportsSearch) return;
    const t = setTimeout(() => {
      setQuery(queryInput.trim());
      setPage(1);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [queryInput, supportsSearch]);

  // 동기화 진행 중 폴링 — 끝나면 목록을 새로고침하고 결과를 토스트.
  useEffect(() => {
    if (!polling) return;
    let active = true;
    const tick = async () => {
      try {
        const s = await fetchSyncStatus(kind);
        if (!active) return;
        setSync(s);
        if (!s.running) {
          setPolling(false);
          if (s.error) toast.error(s.error);
          else toast.success('동기화를 완료했습니다.');
          void loadFavorites();
          void loadCatalog();
        }
      } catch {
        /* 일시 오류는 다음 tick 에서 재시도 */
      }
    };
    const t = setInterval(() => void tick(), SYNC_POLL_MS);
    return () => {
      active = false;
      clearInterval(t);
    };
  }, [polling, kind, loadFavorites, loadCatalog]);

  const runSync = async () => {
    try {
      await startCatalogSync(kind);
      setPolling(true);
      toast.success('동기화를 시작했습니다.');
    } catch (err) {
      toast.error(errorMessage(err, '동기화를 시작하지 못했습니다.'));
    }
  };

  const addFav = async (item: CatalogItem) => {
    setBusy(true);
    try {
      const fav = await addFavorite({ kind, code: item.code, name: item.name, extra: item.extra });
      setFavorites((prev) => (prev.some((f) => f.code === fav.code) ? prev : [...prev, fav]));
    } catch (err) {
      toast.error(errorMessage(err, '자주쓰는 추가에 실패했습니다.'));
    } finally {
      setBusy(false);
    }
  };

  const delFav = async (id: string) => {
    const prev = favorites;
    setFavorites((cur) => cur.filter((f) => f.id !== id));
    try {
      await removeFavorite(id);
    } catch (err) {
      setFavorites(prev);
      toast.error(errorMessage(err, '자주쓰는 해제에 실패했습니다.'));
    }
  };

  const toggleFav = (item: CatalogItem) => {
    const existing = favByCode.get(item.code);
    if (existing) void delFav(existing.id);
    else void addFav(item);
  };

  const move = async (index: number, dir: -1 | 1) => {
    const next = index + dir;
    if (next < 0 || next >= favorites.length) return;
    const prev = favorites;
    const reordered = [...favorites];
    [reordered[index], reordered[next]] = [reordered[next], reordered[index]];
    setFavorites(reordered);
    try {
      await reorderFavorites(
        kind,
        reordered.map((f) => f.id),
      );
    } catch (err) {
      setFavorites(prev);
      toast.error(errorMessage(err, '순서 변경에 실패했습니다.'));
    }
  };

  const syncLabel = sync?.lastSyncedAt ?? syncedAt;

  return (
    <SectionCard
      density="comfortable"
      caption={caption}
      title={title}
      description={description}
      action={
        <div className="flex flex-col items-end gap-1">
          <Button size="sm" variant="secondary" onClick={() => void runSync()} disabled={polling}>
            {polling ? <Spinner size={14} /> : <RiRefreshLine size={14} aria-hidden />}
            {polling ? '동기화 중…' : '동기화'}
          </Button>
          {syncLabel ? (
            <span className="text-foreground-tertiary text-[10px] tabular-nums">
              마지막 동기화 {formatDateTime(syncLabel)}
            </span>
          ) : null}
        </div>
      }
    >
      {/* 자주쓰는 — 순서변경 + 삭제 */}
      <div className="flex flex-col gap-2">
        <p className="text-foreground text-[length:var(--text-body-sm)] font-semibold">
          자주쓰는
          <span className="text-foreground-tertiary ml-1.5 text-[11px] tabular-nums">
            {favorites.length}
          </span>
        </p>
        {favorites.length === 0 ? (
          <p className="text-foreground-tertiary border-border-subtle rounded-[var(--radius-md)] border border-dashed px-3 py-4 text-center text-[12px]">
            아래 목록에서 ★ 을 눌러 자주쓰는 항목을 추가하세요.
          </p>
        ) : (
          <ul className="border-border divide-border-subtle flex flex-col divide-y overflow-hidden rounded-[var(--radius-md)] border">
            {favorites.map((f, i) => (
              <li key={f.id} className="flex items-center gap-3 px-3 py-2">
                <span className="text-foreground-tertiary w-5 text-center text-[11px] tabular-nums">
                  {i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-foreground truncate text-[length:var(--text-body-sm)] font-medium">
                    {f.name}
                  </p>
                  <p className="text-foreground-tertiary truncate font-mono text-[11px]">
                    {f.code}
                    {f.extra?.deptNm ? (
                      <span className="ml-1.5 font-sans">· {f.extra.deptNm}</span>
                    ) : null}
                  </p>
                </div>
                <div className="flex items-center gap-0.5">
                  <IconBtn label="위로" onClick={() => void move(i, -1)} disabled={i === 0}>
                    <RiArrowUpSLine size={16} aria-hidden />
                  </IconBtn>
                  <IconBtn
                    label="아래로"
                    onClick={() => void move(i, 1)}
                    disabled={i === favorites.length - 1}
                  >
                    <RiArrowDownSLine size={16} aria-hidden />
                  </IconBtn>
                  <IconBtn label="해제" onClick={() => void delFav(f.id)} danger>
                    <RiDeleteBinLine size={15} aria-hidden />
                  </IconBtn>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* 전체 카탈로그 — 검색/부서 토글 + ★ 토글 */}
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-foreground text-[length:var(--text-body-sm)] font-semibold">
            전체 목록
          </p>
          {supportsDept ? (
            <label className="text-foreground-secondary flex cursor-pointer items-center gap-1.5 text-[12px]">
              <input
                type="checkbox"
                checked={deptAll}
                onChange={(e) => {
                  setDeptAll(e.target.checked);
                  setPage(1);
                }}
                className="accent-accent size-3.5"
              />
              전체 부서 보기
            </label>
          ) : null}
        </div>

        {supportsSearch ? (
          <div className="relative">
            <RiSearchLine
              size={15}
              aria-hidden
              className="text-foreground-tertiary pointer-events-none absolute top-1/2 left-3 -translate-y-1/2"
            />
            <Input
              value={queryInput}
              onChange={(e) => setQueryInput(e.target.value)}
              placeholder="프로젝트 이름·코드 검색"
              className="pl-9"
            />
          </div>
        ) : null}

        {loading ? (
          <div className="text-muted-foreground flex items-center justify-center gap-2 py-10 text-sm">
            <Spinner size={16} label="불러오는 중" />
            불러오는 중…
          </div>
        ) : loadError ? (
          <EmptyState
            icon={<RiErrorWarningLine size={18} aria-hidden />}
            title="불러오지 못했습니다"
            description={loadError}
            compact
            action={
              <Button size="sm" variant="secondary" onClick={() => void loadCatalog()}>
                다시 시도
              </Button>
            }
          />
        ) : items.length === 0 ? (
          <EmptyState
            icon={<RiErrorWarningLine size={18} aria-hidden />}
            title="항목이 없습니다"
            description={query ? '검색 결과가 없습니다.' : '동기화를 실행해 ERP 코드를 가져오세요.'}
            compact
          />
        ) : (
          <ul className="border-border divide-border-subtle flex flex-col divide-y overflow-hidden rounded-[var(--radius-md)] border">
            {items.map((item) => {
              const fav = favByCode.has(item.code);
              return (
                <li key={item.code} className="flex items-center gap-3 px-3 py-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-foreground truncate text-[length:var(--text-body-sm)] font-medium">
                      {item.name}
                    </p>
                    <p className="text-foreground-tertiary truncate font-mono text-[11px]">
                      {item.code}
                      {item.extra?.deptNm ? (
                        <span className="ml-1.5 font-sans">· {item.extra.deptNm}</span>
                      ) : null}
                    </p>
                  </div>
                  <StarButton active={fav} disabled={busy} onClick={() => toggleFav(item)} />
                </li>
              );
            })}
          </ul>
        )}

        {!loading && !loadError ? (
          <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
        ) : null}
      </div>
    </SectionCard>
  );
}

function IconBtn({
  label,
  onClick,
  disabled,
  danger,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'text-foreground-tertiary hover:bg-muted flex size-8 items-center justify-center rounded-[var(--radius-sm)] transition-colors disabled:cursor-not-allowed disabled:opacity-40',
        danger ? 'hover:text-danger' : 'hover:text-foreground',
      )}
    >
      {children}
    </button>
  );
}

function StarButton({
  active,
  disabled,
  onClick,
}: {
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      aria-pressed={active}
      aria-label={active ? '자주쓰는 해제' : '자주쓰는 추가'}
      title={active ? '자주쓰는 해제' : '자주쓰는 추가'}
      className={cn(
        'flex size-8 shrink-0 items-center justify-center rounded-[var(--radius-sm)] transition-colors disabled:cursor-not-allowed disabled:opacity-40',
        active ? 'text-warning hover:bg-warning/10' : 'text-foreground-tertiary hover:bg-muted',
      )}
    >
      {active ? <RiStarFill size={16} aria-hidden /> : <RiStarLine size={16} aria-hidden />}
    </button>
  );
}
