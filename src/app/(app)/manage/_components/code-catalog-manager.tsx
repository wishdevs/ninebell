'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
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
import { Td, Th } from '@/components/ui/table-cell';
import { errorMessage } from '@/lib/api/client';
import {
  addFavorite,
  fetchCatalog,
  fetchFavorites,
  fetchSyncStatus,
  removeFavorite,
  reorderFavorites,
  setDefaultFavorite,
  startCatalogSync,
  type CatalogItem,
  type CatalogKind,
  type CodeExtra,
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
}

/** 카탈로그 테이블 컬럼 헤더(주 컬럼이 첫 컬럼). */
const CATALOG_HEADERS: Record<CatalogKind, readonly string[]> = {
  budget_unit: ['예산계정명', '예산단위명', '사업계획명'],
  project: ['프로젝트', 'WBS요소', '위치'],
};

const SEARCH_PLACEHOLDER: Record<CatalogKind, string> = {
  budget_unit: '예산계정·예산단위·사업계획 검색',
  project: '프로젝트·WBS·위치 검색',
};

/**
 * 코드(예산단위·프로젝트) 관리 — 자주쓰는(순서변경·삭제·기본지정) + 전체 카탈로그(테이블·★ 토글) +
 * ERP 동기화(진행 중 3초 폴링). 두 kind 가 로직을 공유하므로 kind 로 매개변수화한 단일 컴포넌트다.
 * 전체 목록은 sticky 헤더 테이블(예산단위=예산계정명 주 컬럼, 프로젝트=프로젝트/WBS요소/위치)이며
 * 두 kind 모두 서버 검색을 갖는다. 예산단위만 '전체 부서' 토글을 추가한다.
 */
export function CodeCatalogManager({
  kind,
  caption,
  title,
  description,
  supportsDept = false,
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
        q: query || undefined,
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
  }, [kind, query, supportsDept, deptAll, page]);

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

  // 검색어 디바운스 — 입력 후 300ms 안정되면 서버 질의, 페이지 1로.
  useEffect(() => {
    const t = setTimeout(() => {
      setQuery(queryInput.trim());
      setPage(1);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [queryInput]);

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

  const setDefault = async (id: string) => {
    const prev = favorites;
    // 낙관적: 대상만 기본, 나머지는 해제(같은 kind 내 단일성).
    setFavorites((cur) => cur.map((f) => ({ ...f, isDefault: f.id === id })));
    try {
      await setDefaultFavorite(id);
    } catch (err) {
      setFavorites(prev);
      toast.error(errorMessage(err, '기본 지정에 실패했습니다.'));
    }
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
  const headers = CATALOG_HEADERS[kind];

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
      {/* 자주쓰는 — 순서변경 + 기본지정 + 삭제 */}
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
                <CodeRowInfo kind={kind} name={f.name} code={f.code} extra={f.extra} />
                <DefaultToggle active={f.isDefault} onClick={() => void setDefault(f.id)} />
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

      {/* 전체 카탈로그 — 검색/부서 토글 + sticky 헤더 테이블 + ★ 토글 */}
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

        <div className="relative">
          <RiSearchLine
            size={15}
            aria-hidden
            className="text-foreground-tertiary pointer-events-none absolute top-1/2 left-3 -translate-y-1/2"
          />
          <Input
            value={queryInput}
            onChange={(e) => setQueryInput(e.target.value)}
            placeholder={SEARCH_PLACEHOLDER[kind]}
            className="pl-9"
          />
        </div>

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
          <div className="border-border max-h-[520px] overflow-y-auto rounded-[var(--radius-md)] border">
            <table className="w-full border-separate border-spacing-0 text-[12px]">
              <thead>
                <tr>
                  {headers.map((h, idx) => (
                    <Th
                      key={h}
                      className={cn(
                        'bg-surface text-foreground-tertiary border-border-subtle sticky top-0 z-10 border-b text-left',
                        idx === 0 && 'text-foreground-secondary',
                      )}
                    >
                      {h}
                    </Th>
                  ))}
                  <Th className="bg-surface border-border-subtle sticky top-0 z-10 w-12 border-b text-center">
                    자주쓰는
                  </Th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.code} className="hover:bg-muted/40 transition-colors">
                    <CatalogRowCells kind={kind} item={item} />
                    <Td className="border-border-subtle border-b text-center">
                      <StarButton
                        active={favByCode.has(item.code)}
                        disabled={busy}
                        onClick={() => toggleFav(item)}
                      />
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {!loading && !loadError ? (
          <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
        ) : null}
      </div>
    </SectionCard>
  );
}

/** 카탈로그 테이블 한 행의 데이터 셀(★ 컬럼 제외) — kind 별 컬럼 스펙.
 * 예산단위 = 예산계정명(주·강조) · 예산단위명 · 사업계획명.
 * 프로젝트 = 프로젝트(이름/번호) · WBS요소(번호/이름) · 위치. */
function CatalogRowCells({ kind, item }: { kind: CatalogKind; item: CatalogItem }) {
  const extra = item.extra ?? {};
  const cellBorder = 'border-border-subtle border-b align-top';
  if (kind === 'budget_unit') {
    return (
      <>
        <Td className={cn(cellBorder, 'text-foreground font-medium')}>{extra.bgacctNm || '-'}</Td>
        <Td className={cn(cellBorder, 'text-foreground-secondary')}>{item.name || '-'}</Td>
        <Td className={cn(cellBorder, 'text-foreground-secondary')}>{extra.bizplanNm || '-'}</Td>
      </>
    );
  }
  return (
    <>
      <Td className={cellBorder}>
        <span className="text-foreground block font-medium">{item.name || '-'}</span>
        <span className="text-foreground-tertiary block font-mono text-[11px]">
          {extra.pjtNo || '-'}
        </span>
      </Td>
      <Td className={cellBorder}>
        <span className="text-foreground-secondary block font-mono text-[11px]">
          {extra.wbsNo || '-'}
        </span>
        <span className="text-foreground-tertiary block">{extra.wbsNm || '-'}</span>
      </Td>
      <Td className={cn(cellBorder, 'text-foreground-secondary')}>{extra.loc || '-'}</Td>
    </>
  );
}

/** 자주쓰는 행 표시 — 선택에 필요한 정보를 노출한다.
 * 예산단위 = 예산단위명·사업계획명·예산계정명 3필드, 프로젝트 = 이름·프로젝트번호·WBS요소명. */
function CodeRowInfo({
  kind,
  name,
  code,
  extra,
}: {
  kind: CatalogKind;
  name: string;
  code: string;
  extra: CodeExtra | null;
}) {
  if (kind === 'budget_unit') {
    return (
      <div className="min-w-0 flex-1">
        <p className="text-foreground truncate text-[length:var(--text-body-sm)] font-medium">
          <span className="text-foreground-tertiary mr-1 text-[11px] font-normal">예산단위명</span>
          {name}
        </p>
        <p className="text-foreground-secondary truncate text-[12px]">
          <span className="text-foreground-tertiary mr-1 text-[11px]">사업계획명</span>
          {extra?.bizplanNm || '-'}
        </p>
        <p className="text-foreground-secondary truncate text-[12px]">
          <span className="text-foreground-tertiary mr-1 text-[11px]">예산계정명</span>
          {extra?.bgacctNm || '-'}
        </p>
      </div>
    );
  }
  return (
    <div className="min-w-0 flex-1">
      <p className="text-foreground truncate text-[length:var(--text-body-sm)] font-medium">
        {name}
      </p>
      <p className="text-foreground-tertiary truncate font-mono text-[11px]">
        {extra?.pjtNo || code}
        {extra?.wbsNm ? <span className="ml-1.5 font-sans">· {extra.wbsNm}</span> : null}
      </p>
    </div>
  );
}

/** 기본지정 토글 — 하나만 활성(라디오 성격). 활성 시 강조 뱃지 '기본'. */
function DefaultToggle({ active, onClick }: { active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      aria-label={active ? '기본 지정됨' : '기본으로 지정'}
      title={active ? '기본 지정됨' : '기본으로 지정'}
      className={cn(
        'flex h-6 shrink-0 items-center rounded-full border px-2 text-[11px] font-medium transition-colors',
        active
          ? 'border-accent bg-accent/10 text-accent'
          : 'border-border text-foreground-tertiary hover:border-accent/50 hover:text-foreground-secondary',
      )}
    >
      기본
    </button>
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
