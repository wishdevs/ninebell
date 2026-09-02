'use client';

import { Fragment, useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { RiCheckLine, RiErrorWarningLine, RiSearchLine, RiTableLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { EmptyNote } from '@/components/ui/empty-note';
import { FavoriteToggle } from '@/components/ui/favorite-toggle';
import { Spinner } from '@/components/ui/spinner';
import { ComboPanel, isDesktopViewport, useOutsideClose } from '@/components/live/combo-popover';
import {
  cardOwnerOf,
  groupRowsByOwner,
  OwnerBar,
  OwnerGroupHeaderRow,
  OwnerGroupSectionHeader,
  type OwnerGroup,
} from '@/components/live/grid-owner-filter';
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
  /** 부가세구분 — '과세' 또는 '불공'. 자동 분류 기본값, 사용자가 토글로 덮어쓸 수 있다. */
  vat: string;
}

/** 표시 정렬 — 승인 → 거래시간(날짜+시각) 오름차순. no(제출키)는 행마다 유지되어 제출엔 영향 없다. */
function sortGridRows(rows: readonly LiveGridRow[]): LiveGridRow[] {
  return [...rows].sort(
    (a, b) =>
      (a.approved ?? '').localeCompare(b.approved ?? '') ||
      (a.date ?? '').localeCompare(b.date ?? '') ||
      (a.time ?? '').localeCompare(b.time ?? ''),
  );
}

/** 예산계정명이 불공(매입세액 불공제) 계정인지 — 백엔드 app/agents/card_collect/vat.py 미러.
 * (판)/(제)/공통·공백·하이픈을 흡수해 '복리후생비-업무'↔'(판)복리후생비-업무' 등을 묶는다. */
function normAcctName(s?: string): string {
  return (s ?? '')
    .replace(/\(판\)|\(제\)|\(공통\)/g, '')
    .replace(/[\s()[\]{}·・,./\-_]+/g, '')
    .toLowerCase();
}
// 정확일치(특정 세부계정) — 복리후생비-'업무'만 불공('석식' 아님).
// ⚠ 백엔드 _NONDEDUCTIBLE_ACCTS 와 항목이 같아야 한다 — backend/tests/test_fe_be_mirror_parity.py 가 대조.
const NONDEDUCTIBLE_ACCTS = new Set(
  ['복리후생비-업무', '여비교통비-해외출장', '여비교통비-기타', '차량유지비-유류', '차량유지비-관리', '기부금'].map(
    normAcctName,
  ),
);
// 접대비 계열(접대비·국내/해외·해외접대비 등, 어순 무관) → 부분일치로 전부 불공.
const NONDEDUCTIBLE_CONTAINS = [normAcctName('접대비')];
function isNondeductibleAcct(bgacctNm?: string): boolean {
  const n = normAcctName(bgacctNm);
  if (n.length === 0) return false;
  if (NONDEDUCTIBLE_CONTAINS.some((sub) => n.includes(sub))) return true;
  return NONDEDUCTIBLE_ACCTS.has(n);
}

/** 계정 불공 사유를 뺀 부가세구분 기준값 — 계정을 비-불공으로 바꿀 때 복원용.
 * 가맹점 AI 판정(불공)·원본 비과세면 불공 유지, 그 외(원본 과세)면 과세로 되돌린다. */
function baseVat(rawVatType?: string, aiVat?: string): string {
  if ((aiVat ?? '').trim() === '불공') return '불공';
  return (rawVatType ?? '').trim() === '과세' ? '과세' : '불공';
}

/** 부가세구분 편집형 배지 — 과세(파랑)/불공(주황) 색 구분, 클릭 시 토글.
 * 카드내역 원본(rawVatType)이 '과세'인데 불공으로 처리되면(재분류) 그 맥락을 캡션으로 명시한다
 * — "왜 과세인데 불공이지?"를 사용자가 이해·검증하게. 툴팁엔 원본값과 사유. */
function VatBadge({
  value,
  rawVatType,
  disabled,
  onChange,
}: {
  value: string;
  rawVatType?: string;
  disabled?: boolean;
  onChange: (v: string) => void;
}) {
  const nd = value === '불공';
  const rawTaxable = (rawVatType ?? '').trim() === '과세';
  // 카드내역=과세 인데 불공 처리 = 재분류(불공제 계정·통행료/우체국/유류 등). 맥락을 드러낸다.
  const reclassified = nd && rawTaxable;
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onChange(nd ? '과세' : '불공')}
      title={
        reclassified
          ? `카드내역 부가세구분은 '과세'이지만 매입세액 불공제 대상이라 '불공'으로 처리합니다. 클릭해 과세/불공 전환`
          : `부가세구분 — 카드내역 원본 '${rawVatType || '—'}'. 클릭해 과세/불공 전환`
      }
      className={cn(
        // 모바일 카드에선 토글 히트영역을 40px 로 — md+ 테이블은 기존 밀도 유지.
        'shrink-0 rounded-[var(--radius-sm)] px-2 py-0.5 text-[11px] font-semibold tracking-wide transition-colors disabled:cursor-not-allowed disabled:opacity-60 max-md:min-h-10 max-md:px-3',
        nd
          ? 'bg-warning/15 text-warning hover:bg-warning/25'
          : 'bg-info/15 text-info hover:bg-info/25',
      )}
    >
      {/* 재분류(원본 과세 → 불공)는 전이를 한 배지에 표기 — 스캔 시 '→' 있는 행만 재분류로 인지. */}
      {reclassified ? '과세 → 불공' : nd ? '불공' : '과세'}
    </button>
  );
}

/** edits 에 아직 없는 행의 렌더 폴백 — 테이블·모바일 카드가 같은 값을 쓴다. */
const EMPTY_EDIT: RowEdit = {
  budgetUnitCode: '',
  projectCode: '',
  projectName: '',
  projectWbsNo: '',
  note: '',
  skip: false,
  budgetSource: null,
  projectSource: null,
  noteSource: null,
  vat: '과세',
};

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
        vat: r.vat === '불공' ? '불공' : '과세',
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

/** 전체 컬럼 수 = 번호 + 읽기 컬럼 + 예산계정·프로젝트·적요·제외 — 그룹 헤더 행 colSpan 용. */
const GRID_COL_COUNT = TX_COLUMNS.length + 5;

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
  // 표시용: 정렬(승인·거래시간) 후 소유자(카드명 괄호 이름)별 그룹. 제출/편집은 no 키 기반이라
  // 원본 rows 순서·필터와 무관 — 필터/그룹핑은 렌더 전용이다.
  const ownerGroups = groupRowsByOwner(sortGridRows(rows));
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
  // 선택한 사용자 — '' = 전체. **보기와 처리 범위를 함께** 정한다(사용자 확정 2026-08-13):
  // 고른 사용자의 행만 화면에 보이고, 저장도 그 범위 안에서만 일어난다.
  const [owner, setOwner] = useState('');
  // 예산계정 맞춤 적요 조회 중인 행(미세 로딩 표시). 행 no → 조회 중 여부.
  const [suggesting, setSuggesting] = useState<Record<number, boolean>>({});
  const tableWrapRef = useRef<HTMLDivElement>(null);
  // 테이블(md+)과 카드 스택(md 미만)을 모두 담는 루트 — 행 스크롤 이동이 보이는 쪽을 찾는 기준.
  const rootRef = useRef<HTMLDivElement>(null);

  // md 기준으로 테이블/카드 중 한쪽만 마운트 — CSS 숨김만으로는 두 골격이 모두 살아 있어
  // 40행 기준 행 편집 컨트롤이 2배(콤보 ~80개)가 된다. 첫 렌더(SSR·hydration)는 null 로
  // 두 골격을 모두 렌더해 기존 CSS 분기(max-md:hidden/md:hidden)에 맡긴다(불일치 방지).
  const [isDesktopLayout, setIsDesktopLayout] = useState<boolean | null>(null);
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 768px)');
    const sync = () => setIsDesktopLayout(mq.matches);
    sync();
    mq.addEventListener('change', sync);
    return () => mq.removeEventListener('change', sync);
  }, []);
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
    setOwner('');
    bFav.reset(hitl.budgetUnits?.favorites ?? []);
    pFav.reset(hitl.projects?.favorites ?? []);
    void bFav.loadIds();
    void pFav.loadIds();
  }, [hitl.id, hitl.rows, hitl.budgetUnits, hitl.projects, bFav, pFav]);

  // 그리드 도착(HITL) 시 첫 행 예산단위 콤보박스 트리거로 포커스 — 키보드 진입·40행 이동 개선.
  // (BudgetSelect→BudgetCombobox 교체로 select 가 사라져 data-budget-trigger 로 식별)
  // md 미만은 자동 포커스 생략(가상 키보드·스크롤 점프 방지), md+ 는 preventScroll 로
  // 가로 스크롤 래퍼가 편집 컬럼 쪽으로 점프하던 것을 막는다.
  useEffect(() => {
    if (!isDesktopViewport()) return;
    const trigger = tableWrapRef.current?.querySelector<HTMLButtonElement>(
      'tbody tr [data-budget-trigger]',
    );
    trigger?.focus({ preventScroll: true });
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

  // ── 보기 축 ── owner='' 면 전체. 가려도 검증·저장 대상은 그대로다
  // (저장에서 빼는 축은 아래 '처리 대상' — 행별 '제외' 체크가 단일 소스).
  const visibleGroups = owner ? ownerGroups.filter((g) => g.owner === owner) : ownerGroups;
  // 그룹 첫 행 앞에 헤더 행을 끼워 넣기 위한 매핑 — 행 렌더 블록 구조를 바꾸지 않기 위한 평탄화.
  const headerBeforeNo = new Map<number, OwnerGroup>();
  for (const g of visibleGroups) if (g.rows[0]) headerBeforeNo.set(g.rows[0].no, g);
  const displayRows = visibleGroups.flatMap((g) => g.rows);

  // 범위 안에서 행별 '제외'를 묶어 켜고 끄는 단축 — 그룹헤더 토글이 유일한 사용처다.
  const setSkipForRows = useCallback((nos: readonly number[], skip: boolean) => {
    setEdits((prev) => {
      const next = { ...prev };
      for (const no of nos) next[no] = { ...next[no], skip };
      return next;
    });
  }, []);

  const setRow = useCallback((no: number, patch: Partial<RowEdit>) => {
    setEdits((prev) => ({ ...prev, [no]: { ...prev[no], ...patch } }));
  }, []);

  /** 일괄 지정 — **현재 처리 범위(선택한 사용자) 안**의 비제외 행에만 적용한다. */
  const applyAll = (patch: Partial<RowEdit>) => {
    setEdits((prev) => {
      const next = { ...prev };
      for (const r of displayRows) if (!next[r.no]?.skip) next[r.no] = { ...next[r.no], ...patch };
      return next;
    });
  };

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
      const opt = budgetByCode.get(code);
      const acct = acctCodeOf(code, opt);
      // 계정 이름(bgacctNm) — 미학습 조합에서 AI 가 계정 맞춤 적요를 생성하는 근거로 함께 넘긴다.
      const acctName = (opt?.bgacctNm ?? '').trim();
      if (!m || !acct) {
        // 가맹점명 없음 또는 계정 없음(선택 해제 포함) → 취소만 하고 조회하지 않는다.
        timers.delete(no);
        return;
      }

      const timer = setTimeout(() => {
        timers.delete(no);
        setSuggesting((s) => ({ ...s, [no]: true }));
        fetchNoteSuggest({ merchant: m, acct, acctName })
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
              // 미학습 조합의 AI 생성은 'ai' 배지, 결정적 재추천은 'lookup' 배지로 구분.
              const src: PrefillSource = res.source === 'ai' ? 'ai' : 'lookup';
              return { ...cur, [no]: { ...row, note, noteSource: src } };
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

  // 처리 대상 = **선택한 사용자 범위 안** + 행별 '제외' 미체크(사용자 확정 2026-08-13:
  // 사용자를 고르면 그 사용자만 처리한다). 범위 밖 행은 edits 를 건드리지 않고 제출 시
  // skip 으로 나가므로, 전체로 되돌리면 원래 제외 상태가 그대로 살아난다.
  const inScope = (r: LiveGridRow): boolean => !owner || cardOwnerOf(r.card) === owner;
  const isSkipped = (r: LiveGridRow): boolean => !!edits[r.no]?.skip || !inScope(r);

  const nonSkip = rows.filter((r) => !isSkipped(r));
  const validCount = nonSkip.filter((r) => isRowValid(r.no)).length;
  const allValid = nonSkip.length > 0 && validCount === nonSkip.length;
  const skipCount = rows.length - nonSkip.length;
  // 범위 밖은 검증 대상이 아니므로 첫 무효 행은 언제나 현재 화면 안에 있다.
  const firstInvalidNo = nonSkip.find((r) => !isRowValid(r.no))?.no ?? null;

  const scrollToRow = useCallback((no: number) => {
    // 같은 행이 테이블(md+)·카드(md 미만) 양쪽 DOM 에 있으므로 보이는 쪽(offsetParent 有)만 잡는다.
    const rowEl = Array.from(
      rootRef.current?.querySelectorAll<HTMLElement>(`[data-row-no="${no}"]`) ?? [],
    ).find((el) => el.offsetParent !== null);
    if (!rowEl) return;
    rowEl.scrollIntoView({ block: 'center' });
    rowEl.querySelector<HTMLButtonElement>('[data-budget-trigger]')?.focus({ preventScroll: true });
  }, []);

  // 오류 내비게이션 — 첫 무효 행으로 스크롤 + 그 행 예산단위 트리거에 포커스.
  // (범위 밖 행은 검증하지 않으므로 대상은 항상 현재 화면에 렌더돼 있다.)
  const jumpToFirstInvalid = useCallback(() => {
    if (firstInvalidNo == null) return;
    scrollToRow(firstInvalidNo);
  }, [firstInvalidNo, scrollToRow]);

  /** 행 편집 컨트롤 3종(예산계정·프로젝트·적요) — md+ 테이블 셀과 md 미만 카드가 같은
   * JSX·핸들러를 공유한다(상태·로직 단일 소스, 렌더 골격만 분기). */
  const rowEditors = (r: LiveGridRow, e: RowEdit, rowInvalid: boolean) => ({
    budget: (
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
            // 계정 변경 시 부가세구분 재도출 — 불공 계정이면 불공, 아니면 원본(가맹점 AI·
            // VAT_TP) 기준으로 복원한다. 예: 해외출장(불공)→사무용품비로 바꾸면 다시 과세로.
            const vat = isNondeductibleAcct(budgetByCode.get(code)?.bgacctNm)
              ? '불공'
              : baseVat(r.vatType, r.vatDeduction);
            setRow(r.no, { budgetUnitCode: code, budgetSource: null, vat });
            // 예산단위(=계정) 변경 → 그 계정 맞춤 적요 실시간 재추천(디바운스·보호규칙).
            // 선택 해제(code='')여도 호출 — 대기 중 추천을 취소하고 진행 중 요청을 무효화한다.
            scheduleNoteSuggest(r.no, code, r.merchant);
          }}
        />
        <FavoriteToggle
          className="max-md:size-11"
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
    ),
    project: (
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
          className="max-md:size-11"
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
    ),
    note: (
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
            'border-border bg-surface text-foreground placeholder:text-muted-foreground h-8 min-w-0 flex-1 rounded-[var(--radius-sm)] border px-2 text-[11px] outline-none max-md:min-h-11',
            'focus-visible:border-accent focus-visible:ring-accent/40 focus-visible:ring-2',
            'aria-invalid:border-danger disabled:opacity-50',
          )}
        />
      </div>
    ),
  });

  async function submit() {
    if (!allValid || disabled) return;
    setBusy(true);
    setError(null);
    const payload: GridRowSubmit[] = rows.map((r) => {
      const e = edits[r.no];
      // 범위 밖(다른 사용자) 행도 skip 으로 내려 이번 실행에서 처리되지 않게 한다.
      if (isSkipped(r)) {
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
        vat: e.vat === '불공' ? '불공' : '과세',
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
    <div ref={rootRef} className="flex h-full min-h-0 flex-col gap-3">
      <GridHeader title={hitl.title} prompt={hitl.prompt} />

      {/* 재개입 공지 — 직전 저장(F7)이 왜 실패했고 무엇을 고칠지. 계정 불일치는 아래 행별로도
          표시되지만, 필수값 미입력·일반 오류는 여기서만 뜬다(여러 줄 사유+조치). */}
      {hitl.notice ? (
        <div className="border-danger/30 bg-danger/10 text-danger flex shrink-0 items-start gap-2.5 rounded-[var(--radius-md)] border px-3 py-2.5">
          <RiErrorWarningLine size={16} aria-hidden className="mt-0.5 shrink-0" />
          <p className="text-[length:var(--text-body-sm)] leading-relaxed whitespace-pre-line">
            {hitl.notice}
          </p>
        </div>
      ) : null}

      {/* 일괄 지정 — **처리 범위 안**의 비제외 행에 같은 예산단위·프로젝트·적요를 한 번에
          채운다(이후 개별 수정 가능). 사용자를 고르면 그 사용자 행만 대상이 된다. */}
      <BulkBar
        budgetFavs={bFavList}
        budgetMineExclFav={bMineExclFav}
        budgetAllExclFav={bAllExclFav}
        projectFavs={pFavList}
        disabled={disabled}
        onBulkBudget={(code) => {
          // 일괄 지정도 부가세구분 재도출 — 불공 계정이면 전부 불공, 아니면 각 행 원본 기준으로 복원
          // (행마다 원본 VAT_TP·가맹점 AI 가 달라 행별 계산). budgetUnitCode 는 공통.
          const nd = isNondeductibleAcct(budgetByCode.get(code)?.bgacctNm);
          setEdits((prev) => {
            const next = { ...prev };
            // 처리 범위(선택한 사용자) 안의 비제외 행만 — 범위 밖은 이번에 저장하지 않는다.
            for (const r of displayRows) {
              if (next[r.no]?.skip) continue;
              next[r.no] = {
                ...next[r.no],
                budgetUnitCode: code,
                vat: nd ? '불공' : baseVat(r.vatType, r.vatDeduction),
              };
            }
            return next;
          });
          // 일괄 지정도 동일하게 각 행 계정 맞춤 적요를 재추천(비제외 행만, 행별 보호규칙 유지).
          for (const r of displayRows)
            if (!edits[r.no]?.skip) scheduleNoteSuggest(r.no, code, r.merchant);
        }}
        onBulkProject={(code, name, wbsNo) =>
          applyAll({ projectCode: code, projectName: name, projectWbsNo: wbsNo })
        }
        onBulkNote={(note) => applyAll({ note, noteSource: null })}
      />

      {/* 사용자(카드 소유자) 선택 — **보기와 처리 범위를 함께** 정한다. 고른 사용자의 행만
          보이고 저장도 그 범위뿐이며, 범위 안에서 행별 '제외'로 더 뺄 수 있다. */}
      <OwnerBar
        groups={ownerGroups}
        owner={owner}
        totalCount={rows.length}
        scopedCount={nonSkip.length}
        manualExcludedCount={displayRows.filter((r) => edits[r.no]?.skip).length}
        onOwnerChange={setOwner}
      />

      {/* 출처 배지 범례 — 툴팁 없이도 배지 의미를 알 수 있게 한 줄로 상시 노출. */}
      <SourceLegend />

      {/* md+ — 실 테이블(가로 스크롤 폴백). md 미만은 아래 카드 스택이 대신한다. */}
      {isDesktopLayout !== false && (
        <div
          ref={tableWrapRef}
          className="border-border min-h-0 flex-1 overflow-auto rounded-[var(--radius-md)] border max-md:hidden"
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
                <Th className="min-w-[220px]">예산계정</Th>
                <Th className="min-w-[220px]">프로젝트</Th>
                <Th className="min-w-[180px]">적요</Th>
                <Th className="w-14 text-center">제외</Th>
              </tr>
            </thead>
            <tbody>
              {displayRows.map((r) => {
                const e = edits[r.no] ?? EMPTY_EDIT;
                const rowInvalid = !e.skip && !isRowValid(r.no);
                const editors = rowEditors(r, e, rowInvalid);
                const rowTr = (
                  <tr
                    key={r.no}
                    data-row-no={r.no}
                    className={cn(
                      // 셀 수직 중앙 정렬 — 읽기 컬럼(텍스트)과 입력 컬럼(콤보/배지) 높이 차이로 어긋나 보이던 것 교정.
                      'border-border/50 border-t align-middle',
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
                        {c.key === 'vatType' ? (
                          // 부가세구분 = 과세/불공(편집형 배지). 원시 VAT_TP 대신 분류값을 보여주고 토글한다.
                          <VatBadge
                            value={e.vat}
                            rawVatType={r.vatType}
                            disabled={e.skip || disabled}
                            onChange={(v) => setRow(r.no, { vat: v })}
                          />
                        ) : (
                          (r[c.key] ?? '')
                        )}
                      </Td>
                    ))}

                    {/* 예산단위 combobox + ★ */}
                    <Td>
                      {editors.budget}
                      {r.error ? (
                        <p className="text-danger mt-1.5 flex items-start gap-1 text-[11px] leading-snug">
                          <span aria-hidden>⚠</span>
                          <span>{r.error}</span>
                        </p>
                      ) : null}
                    </Td>

                    {/* 프로젝트 combobox + ★ */}
                    <Td>{editors.project}</Td>

                    {/* 적요 — 프리필 출처 배지(학습/전사) 표시, 사용자가 바꾸면 배지 제거.
                      예산계정 변경 시엔 그 계정 맞춤 적요를 조회하는 동안 미세 스피너를 노출. */}
                    <Td>{editors.note}</Td>

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
                // 소유자 그룹 첫 행 앞에 그룹 헤더 행(소유자 · 건수 · 금액 합)을 끼워 넣는다.
                const group = headerBeforeNo.get(r.no);
                return group ? (
                  <Fragment key={r.no}>
                    <OwnerGroupHeaderRow
                      group={group}
                      colSpan={GRID_COL_COUNT}
                      includedCount={group.rows.filter((gr) => !edits[gr.no]?.skip).length}
                      disabled={disabled}
                      onToggleAll={(include) =>
                        setSkipForRows(
                          group.rows.map((gr) => gr.no),
                          !include,
                        )
                      }
                    />
                    {rowTr}
                  </Fragment>
                ) : (
                  rowTr
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* md 미만 — 행당 카드 스택(소유자 그룹 섹션 헤더 + 카드). 테이블과 편집 상태·검증을
          공유하며 렌더 골격만 다르다(로직 단일 소스 = edits/rowEditors). */}
      {isDesktopLayout !== true && (
        <div className="flex min-h-0 flex-col gap-4 md:hidden">
          {visibleGroups.map((group) => (
            <section key={group.owner} className="flex flex-col gap-2">
              <OwnerGroupSectionHeader
                group={group}
                includedCount={group.rows.filter((gr) => !edits[gr.no]?.skip).length}
                disabled={disabled}
                onToggleAll={(include) =>
                  setSkipForRows(
                    group.rows.map((gr) => gr.no),
                    !include,
                  )
                }
              />
              {group.rows.map((r) => {
                const e = edits[r.no] ?? EMPTY_EDIT;
                const rowInvalid = !e.skip && !isRowValid(r.no);
                const editors = rowEditors(r, e, rowInvalid);
                // 카드내역=과세 인데 불공 처리 = 재분류. 툴팁을 못 보는 터치에선 사유를 인라인 노출.
                const reclassified = e.vat === '불공' && (r.vatType ?? '').trim() === '과세';
                return (
                  <div
                    key={r.no}
                    data-row-no={r.no}
                    className={cn(
                      // 행 상태 = 카드 보더/배경(테이블 행 상태 표현에 상응).
                      'border-border flex flex-col gap-2.5 rounded-[var(--radius-md)] border p-3',
                      e.skip && 'opacity-40',
                      rowInvalid && 'border-danger/30 bg-danger/[0.04]',
                      r.error && 'border-danger/40 bg-danger/[0.07]',
                    )}
                  >
                    {/* 카드 헤더 — 가맹점 + 승인액 */}
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-foreground min-w-0 truncate text-[13px] font-semibold">
                        {r.merchant || '(가맹점 미상)'}
                      </span>
                      <span className="text-foreground shrink-0 text-[13px] font-semibold tabular-nums">
                        {r.amount ?? ''}
                      </span>
                    </div>

                    {/* 보조행 — 행 식별 정보 + 부가세 배지 */}
                    <div className="text-foreground-tertiary flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
                      <span className="tabular-nums">#{r.no}</span>
                      {r.card ? <span className="min-w-0 truncate">{r.card}</span> : null}
                      <span className="tabular-nums">
                        {[r.date, r.time].filter(Boolean).join(' ')}
                      </span>
                      {r.approved ? <span>{r.approved}</span> : null}
                      <VatBadge
                        value={e.vat}
                        rawVatType={r.vatType}
                        disabled={e.skip || disabled}
                        onChange={(v) => setRow(r.no, { vat: v })}
                      />
                    </div>
                    {reclassified ? (
                      <p className="text-warning text-[11px] leading-snug">
                        카드내역은 &lsquo;과세&rsquo;이지만 매입세액 불공제 대상이라
                        &lsquo;불공&rsquo;으로 처리합니다.
                      </p>
                    ) : null}
                    {r.error ? (
                      <p className="text-danger flex items-start gap-1 text-[11px] leading-snug">
                        <span aria-hidden>⚠</span>
                        <span>{r.error}</span>
                      </p>
                    ) : null}

                    {/* 본문 — 인라인 라벨 + 편집 컨트롤 세로 스택 */}
                    <div className="flex flex-col gap-2">
                      <CardField label="예산계정">{editors.budget}</CardField>
                      <CardField label="프로젝트">{editors.project}</CardField>
                      <CardField label="적요">{editors.note}</CardField>
                      {/* 제외 — 행 전체 label 로 히트영역 44px 확보. */}
                      <label
                        className={cn(
                          'border-border bg-muted/30 flex min-h-11 cursor-pointer items-center justify-between gap-2 rounded-[var(--radius-sm)] border px-3',
                          disabled && 'cursor-not-allowed opacity-60',
                        )}
                      >
                        <span className="text-foreground-secondary text-[11px]">
                          이 행 제외(저장 안 함)
                        </span>
                        <input
                          type="checkbox"
                          checked={e.skip}
                          disabled={disabled}
                          onChange={(ev) => setRow(r.no, { skip: ev.target.checked })}
                          aria-label={`${r.no}행 제외`}
                          className="accent-accent size-4 disabled:cursor-not-allowed"
                        />
                      </label>
                    </div>
                  </div>
                );
              })}
            </section>
          ))}
        </div>
      )}

      {/* 검증 요약 + 적용(저장 안전 게이트) — md 미만에선 페이지 스크롤(dashboard-shell) 기준
          하단 고정 바(패널 p-4 를 -m 으로 메워 가장자리까지). 조상 overflow 는 live-side-panel
          이 lg 미만에서 풀어 준다. */}
      <div
        className={cn(
          'flex flex-col gap-3',
          // -mb 없이 bottom-0 — 음수 하단 마진이 있으면 sticky 고정 위치가 그만큼 스크롤포트
          // 밖으로 밀린다(실측 828>812). 스크롤 끝에서 패널 p-4 만큼 위에 뜨는 것은 감수.
          'max-md:border-border max-md:bg-surface/95 max-md:sticky max-md:bottom-0 max-md:z-20 max-md:-mx-4 max-md:rounded-[var(--radius-md)] max-md:border max-md:px-4 max-md:pt-3 max-md:pb-[max(1rem,env(safe-area-inset-bottom))] max-md:backdrop-blur',
        )}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-foreground-secondary text-[11px]">
            {nonSkip.length}행 중{' '}
            <span
              className={cn(
                'font-semibold tabular-nums',
                allValid ? 'text-success' : 'text-warning',
              )}
            >
              {validCount}행
            </span>{' '}
            입력 완료
            {owner ? (
              // 범위 고지 — 이번 저장은 이 사용자 행만 대상이다(나머지는 처리되지 않는다).
              <span className="text-foreground-tertiary"> — {owner} 행만 처리</span>
            ) : null}
            {nonSkip.length - validCount > 0 ? (
              <>
                {' '}
                ·{' '}
                <button
                  type="button"
                  onClick={jumpToFirstInvalid}
                  title="첫 미입력 행으로 이동"
                  // 모바일은 -m/p 로 히트영역만 확장(시각 크기 유지).
                  className="text-warning cursor-pointer underline underline-offset-2 hover:opacity-80 max-md:-my-2 max-md:inline-block max-md:py-2"
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
            <Button
              size="sm"
              className="max-md:h-11 max-md:flex-1"
              onClick={() => void submit()}
              disabled={!allValid || disabled}
            >
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
    </div>
  );
}

/** 모바일 카드의 라벨+컨트롤 한 행 — 인라인 라벨(고정폭) 뒤에 편집 컨트롤. */
function CardField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-foreground-tertiary w-12 shrink-0 text-[11px]">{label}</span>
      <div className="min-w-0 flex-1">{children}</div>
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
        className="w-48 text-[11px] max-md:w-full"
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
        className="border-border bg-surface text-foreground focus-visible:border-accent focus-visible:ring-accent/40 h-8 w-48 rounded-[var(--radius-sm)] border px-2 text-[11px] outline-none focus-visible:ring-2 disabled:opacity-50 max-md:h-10 max-md:w-full"
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
        className="border-border bg-surface text-foreground placeholder:text-muted-foreground focus-visible:border-accent focus-visible:ring-accent/40 h-8 w-40 rounded-[var(--radius-sm)] border px-2 text-[11px] outline-none focus-visible:ring-2 disabled:opacity-50 max-md:h-10 max-md:w-full"
      />
      <Button
        size="sm"
        variant="secondary"
        className="h-8 px-2 max-md:h-10 max-md:w-full"
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

  // 바깥 pointerdown 시 닫기(ProjectCombobox 와 동일 패턴).
  useOutsideClose(open, wrapRef, () => setOpen(false));

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
          'border-border bg-surface flex h-8 w-full items-center justify-between gap-1.5 rounded-[var(--radius-sm)] border px-2 text-left text-[11px] outline-none max-md:min-h-11',
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
        <ComboPanel onClose={close} className="md:w-[min(320px,calc(100vw-2rem))]">
          <input
            autoFocus={isDesktopViewport()}
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
            className="border-border bg-surface text-foreground placeholder:text-muted-foreground focus-visible:border-accent focus-visible:ring-accent/40 h-8 w-full shrink-0 rounded-[var(--radius-sm)] border px-2 text-[11px] outline-none focus-visible:ring-2"
          />

          <div
            id={listId}
            role="listbox"
            aria-label="예산단위"
            className="mt-2 min-h-0 flex-1 overflow-y-auto overscroll-contain md:max-h-60 md:flex-none"
          >
            {value !== '' ? (
              <button
                type="button"
                onClick={() => pick('')}
                className="text-foreground-tertiary hover:bg-muted/60 flex w-full items-center rounded-[var(--radius-sm)] px-2 py-1.5 text-left text-[11px] max-md:py-2.5"
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
                          'flex w-full flex-col items-start gap-0.5 rounded-[var(--radius-sm)] px-2 py-1.5 text-left text-[11px] max-md:py-2.5',
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
        </ComboPanel>
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

  // 바깥 pointerdown 시 닫기.
  useOutsideClose(open, wrapRef, () => setOpen(false));

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
          'border-border bg-surface flex h-8 w-full items-center justify-between gap-1.5 rounded-[var(--radius-sm)] border px-2 text-left text-[11px] outline-none max-md:min-h-11',
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
        <ComboPanel onClose={() => setOpen(false)} className="md:w-[min(280px,calc(100vw-2rem))]">
          <div className="flex shrink-0 items-center gap-1.5">
            <input
              autoFocus={isDesktopViewport()}
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
              className="h-8 shrink-0 px-2 max-md:h-11"
              disabled={!text.trim() || searching}
              onClick={() => void runSearch()}
            >
              {searching ? <Spinner size={13} /> : <RiSearchLine size={13} aria-hidden />}
              검색
            </Button>
          </div>

          <div className="mt-2 min-h-0 flex-1 overflow-y-auto overscroll-contain md:max-h-52 md:flex-none">
            {code ? (
              <button
                type="button"
                onClick={() => {
                  onClear();
                  setOpen(false);
                }}
                className="text-foreground-tertiary hover:bg-muted/60 flex w-full items-center rounded-[var(--radius-sm)] px-2 py-1.5 text-left text-[11px] max-md:py-2.5"
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
        </ComboPanel>
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
      className="hover:bg-muted/60 flex w-full items-center justify-between gap-2 rounded-[var(--radius-sm)] px-2 py-1.5 text-left text-[11px] max-md:py-2.5"
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

/**
 * 출처 배지 — **AI · 학습 2종만** 노출한다(사용자 확정 2026-08-13: 5종은 너무 복잡).
 *
 * 백엔드 출처값(ai/learned/seed/lookup/mirror/default/dict)을 두 묶음으로 접는다:
 *   AI  = ai(AI 추천) · lookup(예산계정 변경에 맞춘 적요 재추천) — **모델이 고른 값, 확인 필요**
 *   학습 = learned(과거 내 확정) · seed(전사 기초자료 관례) — **과거 실적에서 나온 값**
 * 나머지(default 기본지정 · mirror 승인취소 상계 · dict 사전 해석)는 **배지 없음** —
 * 근거가 있는 값만 표시해 시선을 아낀다. 세부 출처는 배지 툴팁에 그대로 남는다.
 */
const SOURCE_BADGE: Partial<Record<PrefillSource, { group: 'ai' | 'learned'; title: string }>> = {
  ai: { group: 'ai', title: 'AI 추천으로 미리 선택됨 — 확인 후 필요시 수정' },
  lookup: {
    group: 'ai',
    title: '예산계정 변경에 맞춰 실시간 재추천된 적요 — 확인 후 필요시 수정',
  },
  learned: {
    group: 'learned',
    title: '과거 이 가맹점에 확정했던 선택으로 미리 채움(개입 학습)',
  },
  seed: {
    group: 'learned',
    title: '전사 기초자료(과거 법인카드 실적)의 이 가맹점 관례로 미리 채움',
  },
};

const BADGE_GROUP: Record<'ai' | 'learned', { label: string; cls: string }> = {
  ai: { label: 'AI', cls: 'bg-accent/15 text-accent' },
  learned: { label: '학습', cls: 'bg-success/15 text-success' },
};

/** 두 묶음에 속하지 않는 출처(기본지정·상계·사전)는 아무것도 렌더하지 않는다. */
function SourceBadge({ source }: { source: PrefillSource }) {
  const meta = SOURCE_BADGE[source];
  if (!meta) return null;
  const g = BADGE_GROUP[meta.group];
  return (
    <span
      title={meta.title}
      className={cn(
        'shrink-0 rounded-[var(--radius-sm)] px-1.5 py-0.5 text-[9px] font-semibold tracking-wide',
        g.cls,
      )}
    >
      {g.label}
    </span>
  );
}

/** 출처 배지 범례 — 그리드 상단 한 줄. 툴팁에 의존하지 않고 배지 의미를 상시 노출한다. */
const LEGEND_ITEMS: { source: PrefillSource; desc: string }[] = [
  { source: 'ai', desc: 'AI 추천 — 확인 필요' },
  { source: 'learned', desc: '과거 확정·실적 기반' },
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
      <span className="text-foreground-tertiary">배지 없음 — 기본지정</span>
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
