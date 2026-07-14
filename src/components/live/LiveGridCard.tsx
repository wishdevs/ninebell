'use client';

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { RiCheckLine, RiSearchLine, RiTableLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { EmptyNote } from '@/components/ui/empty-note';
import { FavoriteToggle } from '@/components/ui/favorite-toggle';
import { Spinner } from '@/components/ui/spinner';
import { fetchNoteSuggest } from '@/lib/api/me-codes';
import { useFavorites } from '@/lib/live/use-favorites';
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
 * budgetSource/projectSource/noteSource = 프리필 출처 배지 — 사용자가 값을 바꾸면 null 로 지운다. */
interface RowEdit {
  budgetUnitCode: string;
  projectCode: string;
  projectName: string;
  projectWbsNo: string;
  note: string;
  skip: boolean;
  budgetSource: PrefillSource | null;
  projectSource: PrefillSource | null;
  noteSource: PrefillSource | null;
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
        noteSource: r.note ? (r.noteSource ?? null) : null,
      },
    ]),
  );
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

/** 예산단위 변경 → 계정 맞춤 적요 재추천 디바운스(ms). 빠른 연속 변경 시 마지막만 조회. */
const NOTE_SUGGEST_DEBOUNCE_MS = 250;

/** 예산단위 조합 코드(BG|BIZPLAN|BGACCT)에서 예산계정(BGACCT) 코드를 뽑는다.
 * 옵션에 bgacctCd 가 실려 오면(내 부서·전체 그룹) 우선, 없으면(즐겨찾기 등) 복합코드 3번째 세그먼트.
 * note-suggest 의 acct 매칭 키 — 어느 그룹에서 골랐든 동일하게 계정을 얻기 위한 단일 소스. */
function acctCodeOf(code: string, option?: BudgetUnitOption): string {
  const fromField = option?.bgacctCd?.trim();
  if (fromField) return fromField;
  return code.split('|')[2]?.trim() ?? '';
}

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
  // 예산계정 맞춤 적요 조회 중인 행(미세 로딩 표시). 행 no → 조회 중 여부.
  const [suggesting, setSuggesting] = useState<Record<number, boolean>>({});
  const tableWrapRef = useRef<HTMLDivElement>(null);
  // 계정 맞춤 적요 재추천 — 행별 디바운스 타이머 + 요청 토큰(레이스 방지: 최신 요청만 반영).
  const suggestTimers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());
  const suggestTokens = useRef<Map<number, number>>(new Map());

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

  // 그리드 도착(HITL) 시 첫 행 예산단위 콤보박스 트리거로 포커스 — 키보드 진입·40행 이동 개선.
  // (BudgetSelect→BudgetCombobox 교체로 select 가 사라져 data-budget-trigger 로 식별)
  useEffect(() => {
    const trigger = tableWrapRef.current?.querySelector<HTMLButtonElement>(
      'tbody tr [data-budget-trigger]',
    );
    trigger?.focus();
  }, [hitl.id]);

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

  /**
   * 예산단위(=예산계정) 변경 시 그 계정 맞춤 적요를 디바운스로 조회해 채운다.
   * - 디바운스(NOTE_SUGGEST_DEBOUNCE_MS): 빠른 연속 변경 시 마지막 요청만 나간다.
   * - 레이스 방지: 행별 토큰을 증가시키고, 응답 시점에 최신 토큰과 다르면 스테일 응답으로 버린다.
   * - 보호 규칙: 사용자가 직접 친 적요(noteSource=null && 내용 있음)는 절대 덮지 않는다
   *   (비어 있거나 자동채움 noteSource 가 있을 때만 채운다).
   * - 실패는 조용히 무시 — 기존 적요 유지(에러가 UI 를 깨지 않게).
   */
  const scheduleNoteSuggest = useCallback(
    (no: number, code: string, merchant: string | undefined) => {
      const timers = suggestTimers.current;
      const prev = timers.get(no);
      if (prev) clearTimeout(prev);
      // 이 행에서 발생한 최신 변경 표식 — 나중에 도착한 스테일 응답을 걸러낸다.
      // 매 변경마다 증가시키므로, 선택 해제·계정 없음이어도 진행 중 요청은 무효화된다.
      const token = (suggestTokens.current.get(no) ?? 0) + 1;
      suggestTokens.current.set(no, token);

      const m = (merchant ?? '').trim();
      const acct = acctCodeOf(code, budgetByCode.get(code));
      if (!m || !acct) {
        // 가맹점명 없음 또는 계정 없음(선택 해제 포함) → 취소만 하고 조회하지 않는다.
        timers.delete(no);
        return;
      }

      const timer = setTimeout(() => {
        timers.delete(no);
        setSuggesting((s) => ({ ...s, [no]: true }));
        fetchNoteSuggest({ merchant: m, acct })
          .then((res) => {
            if (suggestTokens.current.get(no) !== token) return; // 스테일 응답 무시.
            const note = (res.note ?? '').trim();
            if (!note) return;
            setEdits((cur) => {
              const row = cur[no];
              if (!row) return cur;
              // 수동 편집(사용자가 직접 친 적요)은 덮지 않는다.
              const isManual = row.noteSource == null && row.note.trim().length > 0;
              if (isManual) return cur;
              // 예산단위는 onChange 가 이미 세팅 — 여기선 적요·배지만 갱신한다.
              return { ...cur, [no]: { ...row, note, noteSource: 'lookup' } };
            });
          })
          .catch(() => {
            // 조용히 무시 — 기존 적요 유지.
          })
          .finally(() => {
            // 최신 요청만 로딩 표시를 내린다(뒤늦은 스테일 응답이 현재 조회를 지우지 않게).
            if (suggestTokens.current.get(no) === token) {
              setSuggesting((s) => {
                const next = { ...s };
                delete next[no];
                return next;
              });
            }
          });
      }, NOTE_SUGGEST_DEBOUNCE_MS);
      timers.set(no, timer);
    },
    [budgetByCode],
  );

  // 개입(hitl.id) 전환·언마운트 시 대기 중 추천 타이머 정리 — 새 그리드에 스테일 적용 방지.
  useEffect(() => {
    const timers = suggestTimers.current;
    const tokens = suggestTokens.current;
    return () => {
      for (const t of timers.values()) clearTimeout(t);
      timers.clear();
      tokens.clear();
    };
  }, [hitl.id]);

  const isRowValid = (no: number): boolean => {
    const e = edits[no];
    return !!e && e.budgetUnitCode !== '' && e.note.trim().length > 0;
  };

  const nonSkip = rows.filter((r) => !edits[r.no]?.skip);
  const validCount = nonSkip.filter((r) => isRowValid(r.no)).length;
  const allValid = nonSkip.length > 0 && validCount === nonSkip.length;
  const skipCount = rows.length - nonSkip.length;
  const firstInvalidNo = nonSkip.find((r) => !isRowValid(r.no))?.no ?? null;

  // 오류 내비게이션 — 첫 무효 행으로 스크롤 + 그 행 예산단위 select 에 포커스.
  const jumpToFirstInvalid = useCallback(() => {
    if (firstInvalidNo == null) return;
    const rowEl = tableWrapRef.current?.querySelector<HTMLTableRowElement>(
      `tr[data-row-no="${firstInvalidNo}"]`,
    );
    if (!rowEl) return;
    rowEl.scrollIntoView({ block: 'center' });
    rowEl.querySelector<HTMLSelectElement>('select')?.focus();
  }, [firstInvalidNo]);

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
      // 개입 학습: 프리필된 원값(r.*)과 비교해 사용자가 실제로 바꾼 필드만 표시.
      // 바꾼 것만 학습한다(프리필 그대로 수락은 학습 대상 아님 — 자기추천 되먹임 방지).
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
        budgetEdited: e.budgetUnitCode !== (r.budgetUnit?.code ?? ''),
        projectEdited: (e.projectCode || '') !== (r.project?.code ?? ''),
        noteEdited: e.note.trim() !== (r.note ?? '').trim(),
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
        <EmptyNote py={10}>정리할 거래내역이 없습니다.</EmptyNote>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <GridHeader title={hitl.title} prompt={hitl.prompt} />

      {/* 일괄 지정 — 비제외 행 전체에 같은 예산단위·프로젝트·적요를 한 번에 채운다(이후 개별 수정 가능). */}
      <BulkBar
        budgetFavs={bFavList}
        budgetMineExclFav={bMineExclFav}
        budgetAllExclFav={bAllExclFav}
        projectFavs={pFavList}
        disabled={disabled}
        onBulkBudget={(code) => {
          applyAll({ budgetUnitCode: code });
          // 일괄 지정도 동일하게 각 행 계정 맞춤 적요를 재추천(비제외 행만, 행별 보호규칙 유지).
          for (const r of rows) if (!edits[r.no]?.skip) scheduleNoteSuggest(r.no, code, r.merchant);
        }}
        onBulkProject={(code, name, wbsNo) =>
          applyAll({ projectCode: code, projectName: name, projectWbsNo: wbsNo })
        }
        onBulkNote={(note) => applyAll({ note, noteSource: null })}
      />

      {/* 출처 배지 범례 — 툴팁 없이도 배지 의미를 알 수 있게 한 줄로 상시 노출. */}
      <SourceLegend />

      <div
        ref={tableWrapRef}
        className="border-border min-h-0 flex-1 overflow-auto rounded-[var(--radius-md)] border"
      >
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
                noteSource: null,
              };
              const rowInvalid = !e.skip && !isRowValid(r.no);
              return (
                <tr
                  key={r.no}
                  data-row-no={r.no}
                  className={cn(
                    'border-border/50 border-t align-top',
                    e.skip && 'opacity-40',
                    rowInvalid && 'bg-danger/[0.04]',
                    r.error && 'bg-danger/[0.07] ring-danger/30 ring-1 ring-inset',
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

                  {/* 예산단위 combobox + ★ */}
                  <Td>
                    <div className="flex items-center gap-1.5">
                      {e.budgetSource ? <SourceBadge source={e.budgetSource} /> : null}
                      <BudgetCombobox
                        value={e.budgetUnitCode}
                        favorites={bFavList}
                        mineExclFav={bMineExclFav}
                        allExclFav={bAllExclFav}
                        selectedOption={budgetByCode.get(e.budgetUnitCode)}
                        disabled={e.skip || disabled}
                        invalid={rowInvalid && e.budgetUnitCode === ''}
                        onChange={(code) => {
                          setRow(r.no, { budgetUnitCode: code, budgetSource: null });
                          // 예산단위(=계정) 변경 → 그 계정 맞춤 적요 실시간 재추천(디바운스·보호규칙).
                          // 선택 해제(code='')여도 호출 — 대기 중 추천을 취소하고 진행 중 요청을 무효화한다.
                          scheduleNoteSuggest(r.no, code, r.merchant);
                        }}
                      />
                      <FavoriteToggle
                        active={bFav.has(e.budgetUnitCode)}
                        disabled={e.skip || disabled || e.budgetUnitCode === ''}
                        onToggle={() => {
                          const o = budgetByCode.get(e.budgetUnitCode);
                          void bFav.toggle(
                            e.budgetUnitCode,
                            o?.name ?? e.budgetUnitCode,
                            o ? { bizplanNm: o.bizplanNm ?? '', bgacctNm: o.bgacctNm ?? '' } : null,
                          );
                        }}
                      />
                    </div>
                    {r.error ? (
                      <p className="text-danger mt-1.5 flex items-start gap-1 text-[11px] leading-snug">
                        <span aria-hidden>⚠</span>
                        <span>{r.error}</span>
                      </p>
                    ) : null}
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
                      <FavoriteToggle
                        active={pFav.has(e.projectCode)}
                        disabled={e.skip || disabled || e.projectCode === ''}
                        onToggle={() =>
                          void pFav.toggle(e.projectCode, e.projectName || e.projectCode, {
                            wbsNo: e.projectWbsNo,
                            wbsNm: '',
                          })
                        }
                      />
                    </div>
                  </Td>

                  {/* 적요 — 프리필 출처 배지(학습/전사) 표시, 사용자가 바꾸면 배지 제거.
                      예산계정 변경 시엔 그 계정 맞춤 적요를 조회하는 동안 미세 스피너를 노출. */}
                  <Td>
                    <div className="flex items-center gap-1.5">
                      {suggesting[r.no] ? (
                        <Spinner
                          size={12}
                          label="적요 추천 조회 중"
                          className="text-foreground-tertiary shrink-0"
                        />
                      ) : e.noteSource ? (
                        <SourceBadge source={e.noteSource} />
                      ) : null}
                      <input
                        value={e.note}
                        onChange={(ev) => setRow(r.no, { note: ev.target.value, noteSource: null })}
                        disabled={e.skip || disabled}
                        maxLength={200}
                        placeholder="적요"
                        aria-invalid={rowInvalid && e.note.trim() === ''}
                        className={cn(
                          'border-border bg-surface text-foreground placeholder:text-muted-foreground h-8 min-w-0 flex-1 rounded-[var(--radius-sm)] border px-2 text-[11px] outline-none',
                          'focus-visible:border-accent focus-visible:ring-accent/40 focus-visible:ring-2',
                          'aria-invalid:border-danger disabled:opacity-50',
                        )}
                      />
                    </div>
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

      {/* 검증 요약 + 적용(저장 안전 게이트) */}
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
            <>
              {' '}
              ·{' '}
              <button
                type="button"
                onClick={jumpToFirstInvalid}
                title="첫 미입력 행으로 이동"
                className="text-warning cursor-pointer underline underline-offset-2 hover:opacity-80"
              >
                예산단위·적요 미입력 {nonSkip.length - validCount}행
              </button>
              <span className="text-foreground-tertiary">
                {' '}
                — 해당 행을 &lsquo;제외&rsquo;하면 나머지만 저장됩니다.
              </span>
            </>
          ) : null}
        </p>

        {/* 1클릭 제출(사용자 확정 2026-07-05: 확인 단계 제거) — 저장 규모는 버튼 옆에 상시
            표기해 '실 ERP N건 저장' 인지는 유지한다. */}
        <div className="flex flex-wrap items-center gap-2">
          {!busy && !submitted ? (
            <span className="text-foreground-tertiary text-[11px]">
              실 ERP에{' '}
              <span className="text-foreground-secondary font-semibold tabular-nums">
                {nonSkip.length}건
              </span>{' '}
              저장{skipCount > 0 ? ` · 제외 ${skipCount}건` : ''}
            </span>
          ) : null}
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
  onBulkNote,
}: {
  budgetFavs: BudgetUnitOption[];
  budgetMineExclFav: BudgetUnitOption[];
  budgetAllExclFav: BudgetUnitOption[];
  projectFavs: ProjectOption[];
  disabled: boolean;
  onBulkBudget: (code: string) => void;
  onBulkProject: (code: string, name: string, wbsNo: string) => void;
  onBulkNote: (note: string) => void;
}) {
  // 적요 일괄 입력값 — '적요 전체 적용' 클릭 시 비제외 행 전체의 적요를 이 값으로 채운다.
  const [bulkNote, setBulkNote] = useState('');
  return (
    <div className="border-border-subtle bg-muted/40 flex flex-wrap items-center gap-2 rounded-[var(--radius-md)] border px-2.5 py-2">
      <span className="text-foreground-tertiary text-[10px] font-semibold tracking-wider uppercase">
        일괄 지정
      </span>
      <BudgetCombobox
        value=""
        favorites={budgetFavs}
        mineExclFav={budgetMineExclFav}
        allExclFav={budgetAllExclFav}
        disabled={disabled}
        placeholder="예산단위 전체 적용"
        className="w-48 text-[11px]"
        onChange={(code) => {
          if (code) onBulkBudget(code);
        }}
      />
      <select
        value=""
        aria-label="프로젝트 전체 적용"
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
      <input
        value={bulkNote}
        onChange={(ev) => setBulkNote(ev.target.value)}
        onKeyDown={(ev) => {
          if (ev.key === 'Enter' && bulkNote.trim()) {
            ev.preventDefault();
            onBulkNote(bulkNote);
          }
        }}
        disabled={disabled}
        maxLength={200}
        placeholder="적요 일괄 입력"
        className="border-border bg-surface text-foreground placeholder:text-muted-foreground focus-visible:border-accent focus-visible:ring-accent/40 h-8 w-40 rounded-[var(--radius-sm)] border px-2 text-[11px] outline-none focus-visible:ring-2 disabled:opacity-50"
      />
      <Button
        size="sm"
        variant="secondary"
        className="h-8 px-2"
        disabled={disabled || !bulkNote.trim()}
        onClick={() => onBulkNote(bulkNote)}
      >
        적요 전체 적용
      </Button>
    </div>
  );
}

// ── 예산단위 combobox ────────────────────────────────────────────────

/** 예산단위 트리거 라벨 — 선택 단위 = 조합 행이라 이름·사업계획명·예산계정명을 함께 보여준다. */
function budgetLabel(o: BudgetUnitOption): string {
  return o.bgacctNm || o.bizplanNm
    ? `${o.name} · ${o.bizplanNm || '-'} · ${o.bgacctNm || '-'}`
    : `${o.name} (${o.code})`;
}

/** 검색 정규화 — 소문자화 + 공백 전부 제거(대소문자·공백 관대 부분일치). */
function normalizeQuery(s: string): string {
  return s.toLowerCase().replace(/\s+/g, '');
}

/** 이름·사업계획명·예산계정명(+코드) 어느 쪽이든 부분일치하면 매칭. */
function budgetMatches(o: BudgetUnitOption, q: string): boolean {
  if (!q) return true;
  return normalizeQuery(`${o.name} ${o.bizplanNm ?? ''} ${o.bgacctNm ?? ''} ${o.code}`).includes(q);
}

/**
 * 예산단위 검색형 combobox — ProjectCombobox 와 같은 상호작용 모델(트리거 → 팝오버 →
 * 검색 입력). 프레임에 favorites+mine+all 전체 목록이 이미 있으므로 클라이언트 필터링만
 * 한다(ERP 재검색 불필요). 그룹(자주쓰는 → 내 부서 → 전체)은 유지하되 빈 그룹은 숨긴다.
 * 키보드: ↑↓ 이동 · Enter 선택 · Esc 닫기. 트리거는 data-budget-trigger 로 식별한다.
 */
function BudgetCombobox({
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
  /** 현재 값의 옵션 — 그룹 밖(프리셀렉트) 코드여도 트리거 라벨을 표시하기 위함. */
  selectedOption?: BudgetUnitOption;
  disabled?: boolean;
  invalid?: boolean;
  placeholder?: string;
  className?: string;
  onChange: (code: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const [activeIdx, setActiveIdx] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);
  const listId = useId();

  // 바깥 클릭 시 닫기(ProjectCombobox 와 동일 패턴).
  useEffect(() => {
    if (!open) return;
    const onDoc = (ev: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(ev.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const q = normalizeQuery(text);
  // 그룹 순서 유지(자주쓰는 → 내 부서 → 전체), 필터 후 빈 그룹은 숨김.
  const groups = [
    { label: '자주쓰는', items: favorites.filter((o) => budgetMatches(o, q)) },
    { label: '내 부서', items: mineExclFav.filter((o) => budgetMatches(o, q)) },
    { label: '전체', items: allExclFav.filter((o) => budgetMatches(o, q)) },
  ].filter((g) => g.items.length > 0);
  const flat = groups.flatMap((g) => g.items);
  // 필터로 목록이 줄어도 활성 인덱스가 범위를 벗어나지 않게 클램프.
  const active = flat.length === 0 ? -1 : Math.min(activeIdx, flat.length - 1);

  // 키보드 이동 시 활성 옵션이 보이도록 스크롤.
  useEffect(() => {
    if (!open || active < 0) return;
    document.getElementById(`${listId}-opt-${active}`)?.scrollIntoView({ block: 'nearest' });
  }, [open, active, listId]);

  // 트리거 라벨 — selectedOption(그룹 밖 프리셀렉트 포함) 우선, 없으면 그룹에서 조회.
  const current =
    selectedOption ??
    (value
      ? [...favorites, ...mineExclFav, ...allExclFav].find((o) => o.code === value)
      : undefined);
  const triggerLabel = value ? (current ? budgetLabel(current) : value) : null;

  const close = () => {
    setOpen(false);
    setText('');
    setActiveIdx(0);
  };

  const pick = (code: string) => {
    onChange(code);
    close();
  };

  return (
    <div ref={wrapRef} className={cn('relative min-w-0 flex-1', className)}>
      <button
        type="button"
        data-budget-trigger
        disabled={disabled}
        aria-invalid={invalid}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => (open ? close() : setOpen(true))}
        className={cn(
          'border-border bg-surface flex h-8 w-full items-center justify-between gap-1.5 rounded-[var(--radius-sm)] border px-2 text-left text-[11px] outline-none',
          'focus-visible:border-accent focus-visible:ring-accent/40 focus-visible:ring-2',
          'aria-invalid:border-danger disabled:opacity-50',
        )}
      >
        <span
          className={cn(
            'min-w-0 truncate',
            triggerLabel ? 'text-foreground' : 'text-muted-foreground',
          )}
        >
          {triggerLabel ?? placeholder}
        </span>
        {/* 검색형 선택(돋보기) — 목록 select(꺾쇠)와 구분되는 어포던스. */}
        <RiSearchLine size={13} aria-hidden className="text-foreground-tertiary shrink-0" />
      </button>

      {open ? (
        <div className="border-border bg-surface absolute left-0 z-20 mt-1 w-[320px] rounded-[var(--radius-md)] border p-2 shadow-[var(--shadow-card)]">
          <input
            autoFocus
            role="combobox"
            aria-expanded
            aria-controls={listId}
            aria-activedescendant={active >= 0 ? `${listId}-opt-${active}` : undefined}
            value={text}
            onChange={(ev) => {
              setText(ev.target.value);
              setActiveIdx(0);
            }}
            onKeyDown={(ev) => {
              if (ev.key === 'ArrowDown') {
                ev.preventDefault();
                setActiveIdx(Math.min(active + 1, flat.length - 1));
              } else if (ev.key === 'ArrowUp') {
                ev.preventDefault();
                setActiveIdx(Math.max(active - 1, 0));
              } else if (ev.key === 'Enter') {
                ev.preventDefault();
                if (active >= 0) pick(flat[active].code);
              } else if (ev.key === 'Escape') {
                ev.preventDefault();
                close();
              }
            }}
            placeholder="이름·사업계획·예산계정 검색"
            className="border-border bg-surface text-foreground placeholder:text-muted-foreground focus-visible:border-accent focus-visible:ring-accent/40 h-8 w-full rounded-[var(--radius-sm)] border px-2 text-[11px] outline-none focus-visible:ring-2"
          />

          <div
            id={listId}
            role="listbox"
            aria-label="예산단위"
            className="mt-2 max-h-60 overflow-y-auto"
          >
            {value !== '' ? (
              <button
                type="button"
                onClick={() => pick('')}
                className="text-foreground-tertiary hover:bg-muted/60 flex w-full items-center rounded-[var(--radius-sm)] px-2 py-1.5 text-left text-[11px]"
              >
                선택 해제
              </button>
            ) : null}

            {groups.map((g, gi) => {
              // 그룹 경계를 넘는 전역(flat) 인덱스 — 키보드 활성 표시와 id 매칭에 사용.
              const offset = groups.slice(0, gi).reduce((n, x) => n + x.items.length, 0);
              return (
                <div key={g.label} role="group" aria-label={g.label}>
                  <p className="text-foreground-tertiary px-2 py-1 text-[10px] font-semibold tracking-wider uppercase">
                    {g.label}
                  </p>
                  {g.items.map((o, i) => {
                    const idx = offset + i;
                    const selected = o.code === value;
                    return (
                      <button
                        key={o.code}
                        type="button"
                        id={`${listId}-opt-${idx}`}
                        role="option"
                        aria-selected={selected}
                        onClick={() => pick(o.code)}
                        onMouseEnter={() => setActiveIdx(idx)}
                        className={cn(
                          'flex w-full flex-col items-start gap-0.5 rounded-[var(--radius-sm)] px-2 py-1.5 text-left text-[11px]',
                          idx === active && 'bg-muted/60',
                        )}
                      >
                        <span
                          className={cn(
                            'leading-snug',
                            selected ? 'text-accent font-semibold' : 'text-foreground',
                          )}
                        >
                          {o.name}
                        </span>
                        {o.bizplanNm || o.bgacctNm ? (
                          <span className="text-foreground-tertiary leading-snug">
                            {[o.bizplanNm, o.bgacctNm].filter(Boolean).join(' · ')}
                          </span>
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              );
            })}

            {flat.length === 0 ? (
              <p className="text-foreground-tertiary px-2 py-2 text-[11px]">
                일치하는 예산단위가 없습니다.
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
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
        title="검색하여 선택"
        className={cn(
          'border-border bg-surface flex h-8 w-full items-center justify-between gap-1.5 rounded-[var(--radius-sm)] border px-2 text-left text-[11px] outline-none',
          'focus-visible:border-accent focus-visible:ring-accent/40 focus-visible:ring-2 disabled:opacity-50',
        )}
      >
        <span
          className={cn('min-w-0 truncate', code ? 'text-foreground' : 'text-muted-foreground')}
        >
          {code ? name || code : '프로젝트 선택'}
        </span>
        {/* 검색형 선택(돋보기) — 목록 select(꺾쇠)와 구분되는 어포던스. */}
        <RiSearchLine size={13} aria-hidden className="text-foreground-tertiary shrink-0" />
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
  // 표시 코드 = PJT_NO. option.code 는 PJT_NO|WBS_NO 합성이라 앞부분만 쓴다.
  const codeLabel = option.code.split('|')[0] || option.code;
  return (
    <button
      type="button"
      onClick={onClick}
      className="hover:bg-muted/60 flex w-full items-center justify-between gap-2 rounded-[var(--radius-sm)] px-2 py-1.5 text-left text-[11px]"
    >
      <span className="flex min-w-0 items-center gap-1.5">
        {codeLabel ? (
          <span className="text-foreground-tertiary bg-muted/60 shrink-0 rounded-[3px] px-1 py-px font-mono text-[10px] tabular-nums">
            {codeLabel}
          </span>
        ) : null}
        <span className="text-foreground truncate">{option.name}</span>
      </span>
      {option.wbsNm ? (
        <span className="text-foreground-tertiary shrink-0 truncate">{option.wbsNm}</span>
      ) : option.wbsNo ? (
        <span className="text-foreground-tertiary shrink-0 font-mono">{option.wbsNo}</span>
      ) : null}
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
  seed: {
    label: '전사',
    title: '전사 기초자료(과거 법인카드 실적)의 이 가맹점 관례로 미리 채움',
    cls: 'bg-info/15 text-info',
  },
  lookup: {
    label: '추천',
    title: '예산계정 변경에 맞춰 실시간 재추천된 적요 — 확인 후 필요시 수정',
    cls: 'bg-warning/15 text-warning',
  },
  default: {
    label: '기본',
    title: '기본지정으로 미리 선택됨',
    cls: 'bg-muted text-foreground-tertiary',
  },
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

/** 출처 배지 범례 — 그리드 상단 한 줄. 툴팁에 의존하지 않고 배지 의미를 상시 노출한다. */
const LEGEND_ITEMS: { source: PrefillSource; desc: string }[] = [
  { source: 'ai', desc: 'AI 추천' },
  { source: 'learned', desc: '과거 내 확정(개입 학습)' },
  { source: 'seed', desc: '전사 기초자료 관례' },
  { source: 'lookup', desc: '예산계정 맞춤 재추천' },
  { source: 'default', desc: '기본지정' },
];

function SourceLegend() {
  return (
    <div className="text-foreground-tertiary flex flex-wrap items-center gap-x-3 gap-y-1 px-0.5 text-[10px]">
      <span className="font-semibold tracking-wider uppercase">배지 안내</span>
      {LEGEND_ITEMS.map(({ source, desc }) => (
        <span key={source} className="flex items-center gap-1">
          <SourceBadge source={source} />
          {desc}
        </span>
      ))}
    </div>
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
