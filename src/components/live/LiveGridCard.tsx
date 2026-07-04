'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { RiCheckLine, RiSearchLine, RiStarFill, RiStarLine, RiTableLine } from '@remixicon/react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import { addFavorite, fetchFavorites, removeFavorite, type CatalogKind } from '@/lib/api/me-codes';
import { errorMessage } from '@/lib/api/client';
import type {
  BudgetUnitOption,
  GridRowSubmit,
  LiveGridRow,
  LiveHitl,
  PrefillSource,
  ProjectOption,
} from '@/lib/live/types';
import { cn } from '@/lib/utils';

interface LiveGridCardProps {
  hitl: LiveHitl;
  /** 프로젝트 ERP 검색 — 부모가 sendQuery(hitl.id, query) 로 바인딩. */
  onQuery: (query: string) => Promise<boolean>;
  /** 행 일괄 제출 — 부모가 sendRows(hitl.id, rows) 로 바인딩. */
  onSubmit: (rows: GridRowSubmit[]) => Promise<boolean>;
}

/** 행별 사용자 입력(예산단위·프로젝트·적요·제외). budgetUnitCode='' = 미선택.
 * projectWbsNo = 선택한 WBS 행의 WBS_NO(반영 시 정확 선택용).
 * budgetSource/projectSource = 프리셀렉트 출처 배지(AI/기본) — 사용자가 값을 바꾸면 null 로 지운다. */
interface RowEdit {
  budgetUnitCode: string;
  projectCode: string;
  projectName: string;
  projectWbsNo: string;
  note: string;
  skip: boolean;
  budgetSource: PrefillSource | null;
  projectSource: PrefillSource | null;
}

function initEdits(rows: readonly LiveGridRow[]): Record<number, RowEdit> {
  return Object.fromEntries(
    rows.map((r) => [
      r.no,
      {
        // AI 추천·기본지정 프리셀렉트를 초기값으로 시드(사용자가 그대로 적용하거나 수정).
        budgetUnitCode: r.budgetUnit?.code ?? '',
        projectCode: r.project?.code ?? '',
        projectName: r.project?.name ?? '',
        projectWbsNo: r.project?.wbsNo ?? '',
        note: r.note ?? '',
        skip: false,
        budgetSource: r.budgetUnit ? (r.budgetSource ?? null) : null,
        projectSource: r.project ? (r.projectSource ?? null) : null,
      },
    ]),
  );
}

/**
 * 자주쓰는(즐겨찾기) 로컬 상태 — code→favId 맵. 프레임 favorites 로 시드하고(id 미상 ''),
 * 마운트 시 REST 로 실제 id 를 채운다(삭제에 필요). 토글은 낙관적, 실패 시 롤백+토스트.
 * 백엔드가 아직 없을 수 있어 REST 실패는 조용히 무시한다(표시 상태는 유지).
 */
function useFavorites(kind: CatalogKind) {
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

/** 읽기 전용 표시 컬럼 키(문자열 값만) — 프리셀렉트 객체 필드(budgetUnit/project)는 제외. */
type TxColumnKey = 'card' | 'merchant' | 'amount' | 'date' | 'time' | 'approved' | 'vatType';

const TX_COLUMNS: { key: TxColumnKey; header: string; align?: 'right' }[] = [
  { key: 'card', header: '카드명' },
  { key: 'merchant', header: '가맹점명' },
  { key: 'amount', header: '승인액', align: 'right' },
  { key: 'date', header: '승인일' },
  { key: 'time', header: '거래시간' },
  { key: 'approved', header: '카드승인여부' },
  { key: 'vatType', header: '부가세구분' },
];

/**
 * 그리드 개입(kind=grid) — 카드 거래내역을 표로 보여주고 행마다 예산단위·프로젝트·적요를
 * 채우게 한다. 넓은 사이드 패널을 가정한 실 테이블(가로 스크롤 폴백·sticky 헤더)이며,
 * 헤더 일괄 지정 · 자주쓰는 ★ 토글 · 제외 체크 · 검증 요약 + 적용을 갖춘다.
 *
 * 같은 id 의 새 프레임(프로젝트 검색 후 searchResults 채움)이 와도 진행 중 편집을 유지한다
 * (편집 상태는 hitl.id 기준으로만 초기화). 옵셔널 필드가 비어도 무너지지 않는다.
 */
export function LiveGridCard({ hitl, onQuery, onSubmit }: LiveGridCardProps) {
  const rows = hitl.rows ?? [];
  const bFavList = hitl.budgetUnits?.favorites ?? [];
  const bMineList = hitl.budgetUnits?.mine ?? [];
  const bAllList = hitl.budgetUnits?.all ?? [];
  const pFavList = hitl.projects?.favorites ?? [];
  const searchResults = hitl.projects?.searchResults ?? null;
  const searchQuery = hitl.projects?.query ?? null;

  const [edits, setEdits] = useState<Record<number, RowEdit>>(() => initEdits(rows));
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const bFav = useFavorites('budget_unit');
  const pFav = useFavorites('project');

  // 편집·자주쓰는 상태는 hitl.id 기준으로만 초기화 — 검색 결과만 갱신되는 동일 id 프레임에선 유지.
  const idRef = useRef<string | null>(null);
  useEffect(() => {
    if (idRef.current === hitl.id) return;
    idRef.current = hitl.id;
    setEdits(initEdits(hitl.rows ?? []));
    setSubmitted(false);
    setError(null);
    bFav.reset(hitl.budgetUnits?.favorites ?? []);
    pFav.reset(hitl.projects?.favorites ?? []);
    void bFav.loadIds();
    void pFav.loadIds();
  }, [hitl.id, hitl.rows, hitl.budgetUnits, hitl.projects, bFav, pFav]);

  // 예산단위 코드 → 옵션(이름·부서) 조회. 자주쓰는 우선. 프리셀렉트가 그룹 밖 코드여도
  // 라벨·★ 가 풀리도록 행 프리셀렉트를 맵에 보강한다.
  const budgetByCode = useMemo(() => {
    const m = new Map<string, BudgetUnitOption>();
    for (const o of [...bFavList, ...bMineList, ...bAllList]) if (!m.has(o.code)) m.set(o.code, o);
    for (const r of rows)
      if (r.budgetUnit && !m.has(r.budgetUnit.code)) m.set(r.budgetUnit.code, r.budgetUnit);
    return m;
  }, [hitl.budgetUnits, rows]); // eslint-disable-line react-hooks/exhaustive-deps

  // 그룹 간 중복 제거: 자주쓰는 → 내 부서 → 전체 순으로 앞 그룹에 나온 코드는 뒤에서 제외.
  const bMineExclFav = useMemo(() => {
    const favCodes = new Set(bFavList.map((o) => o.code));
    return bMineList.filter((o) => !favCodes.has(o.code));
  }, [hitl.budgetUnits]); // eslint-disable-line react-hooks/exhaustive-deps

  const bAllExclFav = useMemo(() => {
    const shown = new Set([...bFavList, ...bMineList].map((o) => o.code));
    return bAllList.filter((o) => !shown.has(o.code));
  }, [hitl.budgetUnits]); // eslint-disable-line react-hooks/exhaustive-deps

  const disabled = busy || submitted;

  const setRow = useCallback((no: number, patch: Partial<RowEdit>) => {
    setEdits((prev) => ({ ...prev, [no]: { ...prev[no], ...patch } }));
  }, []);

  const applyAll = useCallback(
    (patch: Partial<RowEdit>) => {
      setEdits((prev) => {
        const next = { ...prev };
        for (const r of rows) if (!next[r.no]?.skip) next[r.no] = { ...next[r.no], ...patch };
        return next;
      });
    },
    [rows],
  );

  const isRowValid = (no: number): boolean => {
    const e = edits[no];
    return !!e && e.budgetUnitCode !== '' && e.note.trim().length > 0;
  };

  const nonSkip = rows.filter((r) => !edits[r.no]?.skip);
  const validCount = nonSkip.filter((r) => isRowValid(r.no)).length;
  const allValid = nonSkip.length > 0 && validCount === nonSkip.length;

  async function submit() {
    if (!allValid || disabled) return;
    setBusy(true);
    setError(null);
    const payload: GridRowSubmit[] = rows.map((r) => {
      const e = edits[r.no];
      if (e.skip) {
        return { no: r.no, budgetUnit: null, project: null, note: e.note.trim(), skip: true };
      }
      const b = budgetByCode.get(e.budgetUnitCode);
      return {
        no: r.no,
        budgetUnit: b
          ? { code: b.code, name: b.name, bizplanNm: b.bizplanNm, bgacctNm: b.bgacctNm }
          : { code: e.budgetUnitCode, name: e.budgetUnitCode },
        project: e.projectCode
          ? { code: e.projectCode, name: e.projectName, wbsNo: e.projectWbsNo || undefined }
          : null,
        note: e.note.trim(),
        skip: false,
      };
    });
    const ok = await onSubmit(payload);
    if (ok) {
      // 성공 시 스트림이 이어받는다(진행 로그·상태표). hitl 이 닫히며 카드가 사라진다.
      setSubmitted(true);
    } else {
      setError('적용을 전달하지 못했습니다(흐름이 종료됐을 수 있음).');
      setBusy(false);
    }
  }

  if (rows.length === 0) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <GridHeader title={hitl.title} prompt={hitl.prompt} />
        <p className="text-foreground-tertiary py-10 text-center text-[12px]">
          정리할 거래내역이 없습니다.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <GridHeader title={hitl.title} prompt={hitl.prompt} />

      {/* 일괄 지정 — 비제외 행 전체에 같은 예산단위·프로젝트를 한 번에 채운다(이후 개별 수정 가능). */}
      <BulkBar
        budgetFavs={bFavList}
        budgetMineExclFav={bMineExclFav}
        budgetAllExclFav={bAllExclFav}
        projectFavs={pFavList}
        disabled={disabled}
        onBulkBudget={(code) => applyAll({ budgetUnitCode: code })}
        onBulkProject={(code, name, wbsNo) =>
          applyAll({ projectCode: code, projectName: name, projectWbsNo: wbsNo })
        }
      />

      <div className="border-border min-h-0 flex-1 overflow-auto rounded-[var(--radius-md)] border">
        <table className="w-full min-w-[1080px] border-collapse text-[11px]">
          <thead className="bg-muted/70 text-foreground-tertiary sticky top-0 z-10">
            <tr>
              <Th className="w-10 text-center">번호</Th>
              {TX_COLUMNS.map((c) => (
                <Th key={c.key} className={c.align === 'right' ? 'text-right' : 'text-left'}>
                  {c.header}
                </Th>
              ))}
              <Th className="min-w-[220px]">예산단위</Th>
              <Th className="min-w-[220px]">프로젝트</Th>
              <Th className="min-w-[180px]">적요</Th>
              <Th className="w-14 text-center">제외</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const e = edits[r.no] ?? {
                budgetUnitCode: '',
                projectCode: '',
                projectName: '',
                projectWbsNo: '',
                note: '',
                skip: false,
                budgetSource: null,
                projectSource: null,
              };
              const rowInvalid = !e.skip && !isRowValid(r.no);
              return (
                <tr
                  key={r.no}
                  className={cn(
                    'border-border/50 border-t align-top',
                    e.skip && 'opacity-40',
                    rowInvalid && 'bg-danger/[0.04]',
                  )}
                >
                  <Td className="text-foreground-tertiary text-center tabular-nums">{r.no}</Td>
                  {TX_COLUMNS.map((c) => (
                    <Td
                      key={c.key}
                      className={cn(
                        'text-foreground-secondary whitespace-nowrap tabular-nums',
                        c.align === 'right' ? 'text-right' : 'text-left',
                      )}
                    >
                      {r[c.key] ?? ''}
                    </Td>
                  ))}

                  {/* 예산단위 select + ★ */}
                  <Td>
                    <div className="flex items-center gap-1.5">
                      {e.budgetSource ? <SourceBadge source={e.budgetSource} /> : null}
                      <BudgetSelect
                        value={e.budgetUnitCode}
                        favorites={bFavList}
                        mineExclFav={bMineExclFav}
                        allExclFav={bAllExclFav}
                        selectedOption={budgetByCode.get(e.budgetUnitCode)}
                        disabled={e.skip || disabled}
                        invalid={rowInvalid && e.budgetUnitCode === ''}
                        onChange={(code) =>
                          setRow(r.no, { budgetUnitCode: code, budgetSource: null })
                        }
                      />
                      <StarButton
                        active={bFav.has(e.budgetUnitCode)}
                        disabled={e.skip || disabled || e.budgetUnitCode === ''}
                        onClick={() => {
                          const o = budgetByCode.get(e.budgetUnitCode);
                          void bFav.toggle(
                            e.budgetUnitCode,
                            o?.name ?? e.budgetUnitCode,
                            o ? { bizplanNm: o.bizplanNm ?? '', bgacctNm: o.bgacctNm ?? '' } : null,
                          );
                        }}
                      />
                    </div>
                  </Td>

                  {/* 프로젝트 combobox + ★ */}
                  <Td>
                    <div className="flex items-center gap-1.5">
                      {e.projectSource ? <SourceBadge source={e.projectSource} /> : null}
                      <ProjectCombobox
                        code={e.projectCode}
                        name={e.projectName}
                        favorites={pFavList}
                        searchResults={searchResults}
                        searchQuery={searchQuery}
                        disabled={e.skip || disabled}
                        onSelect={(code, name, wbsNo) =>
                          setRow(r.no, {
                            projectCode: code,
                            projectName: name,
                            projectWbsNo: wbsNo,
                            projectSource: null,
                          })
                        }
                        onClear={() =>
                          setRow(r.no, {
                            projectCode: '',
                            projectName: '',
                            projectWbsNo: '',
                            projectSource: null,
                          })
                        }
                        onSearch={onQuery}
                      />
                      <StarButton
                        active={pFav.has(e.projectCode)}
                        disabled={e.skip || disabled || e.projectCode === ''}
                        onClick={() =>
                          void pFav.toggle(e.projectCode, e.projectName || e.projectCode, {
                            wbsNo: e.projectWbsNo,
                            wbsNm: '',
                          })
                        }
                      />
                    </div>
                  </Td>

                  {/* 적요 */}
                  <Td>
                    <input
                      value={e.note}
                      onChange={(ev) => setRow(r.no, { note: ev.target.value })}
                      disabled={e.skip || disabled}
                      maxLength={200}
                      placeholder="적요"
                      aria-invalid={rowInvalid && e.note.trim() === ''}
                      className={cn(
                        'border-border bg-surface text-foreground placeholder:text-muted-foreground h-8 w-full rounded-[var(--radius-sm)] border px-2 text-[11px] outline-none',
                        'focus-visible:border-accent focus-visible:ring-accent/40 focus-visible:ring-2',
                        'aria-invalid:border-danger disabled:opacity-50',
                      )}
                    />
                  </Td>

                  {/* 제외 */}
                  <Td className="text-center">
                    <input
                      type="checkbox"
                      checked={e.skip}
                      disabled={disabled}
                      onChange={(ev) => setRow(r.no, { skip: ev.target.checked })}
                      aria-label={`${r.no}행 제외`}
                      className="accent-accent size-4 cursor-pointer disabled:cursor-not-allowed"
                    />
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* 검증 요약 + 적용 */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-foreground-secondary text-[11px]">
          {nonSkip.length}행 중{' '}
          <span
            className={cn('font-semibold tabular-nums', allValid ? 'text-success' : 'text-warning')}
          >
            {validCount}행
          </span>{' '}
          입력 완료
          {nonSkip.length - validCount > 0 ? (
            <span className="text-foreground-tertiary">
              {' '}
              · 예산단위·적요 미입력 {nonSkip.length - validCount}행
            </span>
          ) : null}
        </p>
        <Button size="sm" onClick={() => void submit()} disabled={!allValid || disabled}>
          {submitted ? (
            <>
              <Spinner size={14} />
              반영·저장 진행 중…
            </>
          ) : busy ? (
            <>
              <Spinner size={14} />
              전송 중…
            </>
          ) : (
            <>
              <RiCheckLine size={14} aria-hidden />
              입력 완료
            </>
          )}
        </Button>
      </div>

      {error ? <span className="text-danger text-[12px]">{error}</span> : null}
    </div>
  );
}

// ── 헤더 ─────────────────────────────────────────────────────────────

function GridHeader({ title, prompt }: { title: string; prompt?: string }) {
  return (
    <div className="border-warning/30 bg-warning/10 flex items-start gap-2.5 rounded-[var(--radius-md)] border px-3 py-2.5">
      <RiTableLine size={16} aria-hidden className="text-warning mt-0.5 shrink-0" />
      <div className="min-w-0">
        <p className="text-foreground text-[length:var(--text-body-sm)] font-semibold">
          {title} · 승인내역 정리
        </p>
        {prompt ? (
          <p className="text-foreground-secondary mt-0.5 text-[11px] leading-relaxed">{prompt}</p>
        ) : null}
      </div>
    </div>
  );
}

// ── 일괄 지정 바 ─────────────────────────────────────────────────────

function BulkBar({
  budgetFavs,
  budgetMineExclFav,
  budgetAllExclFav,
  projectFavs,
  disabled,
  onBulkBudget,
  onBulkProject,
}: {
  budgetFavs: BudgetUnitOption[];
  budgetMineExclFav: BudgetUnitOption[];
  budgetAllExclFav: BudgetUnitOption[];
  projectFavs: ProjectOption[];
  disabled: boolean;
  onBulkBudget: (code: string) => void;
  onBulkProject: (code: string, name: string, wbsNo: string) => void;
}) {
  return (
    <div className="border-border-subtle bg-muted/40 flex flex-wrap items-center gap-2 rounded-[var(--radius-md)] border px-2.5 py-2">
      <span className="text-foreground-tertiary text-[10px] font-semibold tracking-wider uppercase">
        일괄 지정
      </span>
      <BudgetSelect
        value=""
        favorites={budgetFavs}
        mineExclFav={budgetMineExclFav}
        allExclFav={budgetAllExclFav}
        disabled={disabled}
        placeholder="예산단위 전체 적용"
        className="h-8 w-48 text-[11px]"
        onChange={(code) => code && onBulkBudget(code)}
      />
      <select
        value=""
        disabled={disabled || projectFavs.length === 0}
        onChange={(ev) => {
          const p = projectFavs.find((x) => x.code === ev.target.value);
          if (p) onBulkProject(p.code, p.name, p.wbsNo ?? '');
        }}
        className="border-border bg-surface text-foreground focus-visible:border-accent focus-visible:ring-accent/40 h-8 w-48 rounded-[var(--radius-sm)] border px-2 text-[11px] outline-none focus-visible:ring-2 disabled:opacity-50"
      >
        <option value="">프로젝트 전체 적용(자주쓰는)</option>
        {projectFavs.map((p) => (
          <option key={p.code} value={p.code}>
            {p.name}
            {p.wbsNm ? ` · ${p.wbsNm}` : ''}
          </option>
        ))}
      </select>
    </div>
  );
}

// ── 예산단위 select ──────────────────────────────────────────────────

function BudgetSelect({
  value,
  favorites,
  mineExclFav = [],
  allExclFav,
  selectedOption,
  disabled,
  invalid,
  placeholder = '예산단위 선택',
  className,
  onChange,
}: {
  value: string;
  favorites: BudgetUnitOption[];
  /** 내 부서 매칭(자주쓰는 제외분). */
  mineExclFav?: BudgetUnitOption[];
  allExclFav: BudgetUnitOption[];
  /** 현재 값의 옵션 — 그룹 밖(프리셀렉트) 코드일 때 라벨을 표시하려 별도 옵션을 끼운다. */
  selectedOption?: BudgetUnitOption;
  disabled?: boolean;
  invalid?: boolean;
  placeholder?: string;
  className?: string;
  onChange: (code: string) => void;
}) {
  // 선택 단위 = 조합 행 — 예산단위명·사업계획명·예산계정명을 모두 보여줘야 고를 수 있다.
  const label = (o: BudgetUnitOption) =>
    o.bgacctNm || o.bizplanNm
      ? `${o.name} · ${o.bizplanNm || '-'} · ${o.bgacctNm || '-'}`
      : `${o.name} (${o.code})`;
  const inGroups =
    value !== '' && [...favorites, ...mineExclFav, ...allExclFav].some((o) => o.code === value);
  return (
    <select
      value={value}
      disabled={disabled}
      aria-invalid={invalid}
      onChange={(ev) => onChange(ev.target.value)}
      className={cn(
        'border-border bg-surface text-foreground h-8 min-w-0 flex-1 rounded-[var(--radius-sm)] border px-2 text-[11px] outline-none',
        'focus-visible:border-accent focus-visible:ring-accent/40 focus-visible:ring-2',
        'aria-invalid:border-danger disabled:opacity-50',
        className,
      )}
    >
      <option value="">{placeholder}</option>
      {!inGroups && value !== '' && selectedOption ? (
        <option value={value}>{label(selectedOption)}</option>
      ) : null}
      {favorites.length > 0 ? (
        <optgroup label="자주쓰는">
          {favorites.map((o) => (
            <option key={`f-${o.code}`} value={o.code}>
              {label(o)}
            </option>
          ))}
        </optgroup>
      ) : null}
      {mineExclFav.length > 0 ? (
        <optgroup label="내 부서">
          {mineExclFav.map((o) => (
            <option key={`m-${o.code}`} value={o.code}>
              {label(o)}
            </option>
          ))}
        </optgroup>
      ) : null}
      {allExclFav.length > 0 ? (
        <optgroup label="전체">
          {allExclFav.map((o) => (
            <option key={`a-${o.code}`} value={o.code}>
              {label(o)}
            </option>
          ))}
        </optgroup>
      ) : null}
    </select>
  );
}

// ── 프로젝트 combobox ────────────────────────────────────────────────

function ProjectCombobox({
  code,
  name,
  favorites,
  searchResults,
  searchQuery,
  disabled,
  onSelect,
  onClear,
  onSearch,
}: {
  code: string;
  name: string;
  favorites: ProjectOption[];
  searchResults: ProjectOption[] | null;
  searchQuery: string | null;
  disabled?: boolean;
  onSelect: (code: string, name: string, wbsNo: string) => void;
  onClear: () => void;
  onSearch: (query: string) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const [searching, setSearching] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  // 검색 결과/질의가 갱신되면(새 프레임) 로딩 상태 해제.
  useEffect(() => {
    setSearching(false);
  }, [searchResults, searchQuery]);

  // 바깥 클릭 시 닫기.
  useEffect(() => {
    if (!open) return;
    const onDoc = (ev: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(ev.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const q = text.trim().toLowerCase();
  const filteredFavs = q
    ? favorites.filter((p) => p.name.toLowerCase().includes(q) || p.code.toLowerCase().includes(q))
    : favorites;

  const pick = (p: ProjectOption) => {
    onSelect(p.code, p.name, p.wbsNo ?? '');
    setOpen(false);
    setText('');
  };

  async function runSearch() {
    const query = text.trim();
    if (!query || searching) return;
    setSearching(true);
    const ok = await onSearch(query);
    if (!ok) setSearching(false);
  }

  return (
    <div ref={wrapRef} className="relative min-w-0 flex-1">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'border-border bg-surface flex h-8 w-full items-center justify-between gap-1 rounded-[var(--radius-sm)] border px-2 text-left text-[11px] outline-none',
          'focus-visible:border-accent focus-visible:ring-accent/40 focus-visible:ring-2 disabled:opacity-50',
        )}
      >
        <span className={cn('truncate', code ? 'text-foreground' : 'text-muted-foreground')}>
          {code ? name || code : '프로젝트 선택'}
        </span>
      </button>

      {open ? (
        <div className="border-border bg-surface absolute left-0 z-20 mt-1 w-[280px] rounded-[var(--radius-md)] border p-2 shadow-[var(--shadow-card)]">
          <div className="flex items-center gap-1.5">
            <input
              autoFocus
              value={text}
              onChange={(ev) => setText(ev.target.value)}
              onKeyDown={(ev) => {
                if (ev.key === 'Enter') {
                  ev.preventDefault();
                  void runSearch();
                }
                if (ev.key === 'Escape') setOpen(false);
              }}
              placeholder="자주쓰는 필터 / ERP 검색어"
              className="border-border bg-surface text-foreground placeholder:text-muted-foreground focus-visible:border-accent focus-visible:ring-accent/40 h-8 min-w-0 flex-1 rounded-[var(--radius-sm)] border px-2 text-[11px] outline-none focus-visible:ring-2"
            />
            <Button
              size="sm"
              variant="secondary"
              className="h-8 shrink-0 px-2"
              disabled={!text.trim() || searching}
              onClick={() => void runSearch()}
            >
              {searching ? <Spinner size={13} /> : <RiSearchLine size={13} aria-hidden />}
              검색
            </Button>
          </div>

          <div className="mt-2 max-h-52 overflow-y-auto">
            {code ? (
              <button
                type="button"
                onClick={() => {
                  onClear();
                  setOpen(false);
                }}
                className="text-foreground-tertiary hover:bg-muted/60 flex w-full items-center rounded-[var(--radius-sm)] px-2 py-1.5 text-left text-[11px]"
              >
                선택 해제
              </button>
            ) : null}

            {filteredFavs.length > 0 ? (
              <>
                <p className="text-foreground-tertiary px-2 py-1 text-[10px] font-semibold tracking-wider uppercase">
                  자주쓰는
                </p>
                {filteredFavs.map((p) => (
                  <ProjectOptionRow key={`f-${p.code}`} option={p} onClick={() => pick(p)} />
                ))}
              </>
            ) : null}

            {searchResults && searchResults.length > 0 ? (
              <>
                <p className="text-foreground-tertiary px-2 py-1 text-[10px] font-semibold tracking-wider uppercase">
                  ERP 검색결과{searchQuery ? ` · ${searchQuery}` : ''}
                </p>
                {searchResults.map((p) => (
                  <ProjectOptionRow key={`s-${p.code}`} option={p} onClick={() => pick(p)} />
                ))}
              </>
            ) : searchResults && searchResults.length === 0 ? (
              <p className="text-foreground-tertiary px-2 py-2 text-[11px]">
                검색 결과가 없습니다.
              </p>
            ) : null}

            {filteredFavs.length === 0 && !searchResults ? (
              <p className="text-foreground-tertiary px-2 py-2 text-[11px]">
                검색어를 입력해 ERP 프로젝트를 찾으세요.
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ProjectOptionRow({ option, onClick }: { option: ProjectOption; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="hover:bg-muted/60 flex w-full items-center justify-between gap-2 rounded-[var(--radius-sm)] px-2 py-1.5 text-left text-[11px]"
    >
      <span className="text-foreground truncate">{option.name}</span>
      {option.wbsNm ? (
        <span className="text-foreground-tertiary shrink-0 truncate">{option.wbsNm}</span>
      ) : option.wbsNo ? (
        <span className="text-foreground-tertiary shrink-0 font-mono">{option.wbsNo}</span>
      ) : null}
    </button>
  );
}

// ── 자주쓰는 ★ 토글 ──────────────────────────────────────────────────

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
        'flex size-7 shrink-0 items-center justify-center rounded-[var(--radius-sm)] transition-colors disabled:cursor-not-allowed disabled:opacity-30',
        active ? 'text-warning hover:bg-warning/10' : 'text-foreground-tertiary hover:bg-muted',
      )}
    >
      {active ? <RiStarFill size={14} aria-hidden /> : <RiStarLine size={14} aria-hidden />}
    </button>
  );
}

// ── 프리셀렉트 출처 배지(AI / 기본) ──────────────────────────────────

const SOURCE_META: Record<PrefillSource, { label: string; title: string; cls: string }> = {
  ai: { label: 'AI', title: 'AI 추천으로 미리 선택됨', cls: 'bg-accent/15 text-accent' },
  learned: {
    label: '학습',
    title: '과거 이 가맹점에 확정했던 선택으로 미리 채움(개입 학습)',
    cls: 'bg-success/15 text-success',
  },
  default: { label: '기본', title: '기본지정으로 미리 선택됨', cls: 'bg-muted text-foreground-tertiary' },
};

function SourceBadge({ source }: { source: PrefillSource }) {
  const meta = SOURCE_META[source] ?? SOURCE_META.default;
  return (
    <span
      title={meta.title}
      className={cn(
        'shrink-0 rounded-[var(--radius-sm)] px-1.5 py-0.5 text-[9px] font-semibold tracking-wide',
        meta.cls,
      )}
    >
      {meta.label}
    </span>
  );
}

// ── 테이블 셀(그리드 전용 컴팩트) ────────────────────────────────────

function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <th className={cn('px-2 py-1.5 font-semibold whitespace-nowrap', className)}>{children}</th>
  );
}

function Td({ children, className }: { children: React.ReactNode; className?: string }) {
  return <td className={cn('px-2 py-1.5', className)}>{children}</td>;
}
