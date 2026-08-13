'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { RiInformationLine, RiPlayLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { SectionCard } from '@/components/ui/section-card';
import { fetchCatalog, fetchFavorites } from '@/lib/api/me-codes';
import { CatalogCombobox, type ComboOption, projectCodeLabel } from './catalog-combobox';
import type { PreRunFormProps } from './index';

/**
 * 구매발주 실행 전 폼 — 대상 프로젝트를 먼저 고르고 실행한다.
 *
 * 프로젝트 선택 UI·데이터는 법인카드/출장 계열이 쓰는 **기존 카탈로그**(GET /me/catalog?kind=project,
 * 자주쓰는 = GET /me/favorites?kind=project)를 그대로 재사용한다.
 *
 * 백엔드 계약:
 *   params["purchase_order"] = { project_no, project_name, keyword }
 *   - project_no  = 카탈로그 extra.pjtNo(= 옴니솔 도움창 PJT_NO). 카탈로그 code 는
 *                   'PJT_NO|WBS_NO' 합성이라 앞부분만 쓴다.
 *   - keyword     = ERP 도움창 검색어. 프로젝트명의 콤마 앞 토큰(프로브로 검증된 경로).
 *   - project_name= 표시·검증용 전체 이름.
 *
 * 카탈로그는 WBS 행 단위라 한 프로젝트가 여러 행으로 나온다 → PJT_NO 기준으로 접어 1건으로 본다.
 * 스냅샷이 낡을 수 있으므로(동기화 시점 표기) 카탈로그에 없는 프로젝트는 '직접 입력'으로 실행한다.
 */

/** 카탈로그 검색 요청 건수 — WBS 행 단위라 PJT_NO 로 접으면 크게 줄어들어 넉넉히 받는다. */
const SEARCH_LIMIT = 60;

const STALE_CATALOG_HINT = '최근 프로젝트는 카탈로그 동기화 후 표시됩니다.';

/** 카탈로그 항목/즐겨찾기 공통 입력 shape(둘 다 code·name·extra.pjtNo 를 가진다). */
interface ProjectRow {
  code: string;
  name: string;
  extra: { pjtNo?: string } | null;
  isDefault?: boolean;
}

/** WBS 행(2254, 2254-01…)을 PJT_NO 기준으로 접어 프로젝트 1건으로 만든다. 옵션 code = PJT_NO. */
function toProjectOptions(rows: readonly ProjectRow[]): ComboOption[] {
  const byPjtNo = new Map<string, ComboOption>();
  for (const row of rows) {
    const pjtNo = projectCodeLabel(row.code, row.extra?.pjtNo ?? undefined);
    if (!pjtNo || byPjtNo.has(pjtNo)) continue;
    byPjtNo.set(pjtNo, {
      code: pjtNo,
      name: row.name,
      codeLabel: pjtNo,
      isDefault: row.isDefault,
    });
  }
  return [...byPjtNo.values()];
}

/** ERP 도움창 검색어 = 프로젝트명의 콤마 앞 토큰('CX85-137, 12CH PROCESS' → 'CX85-137'). */
function deriveKeyword(projectName: string): string {
  return (projectName.split(',')[0] ?? '').trim();
}

/** ISO 타임스탬프 → 'YYYY-MM-DD'(표시용). 형식이 아니면 null. */
function formatSyncedAt(iso: string | null): string | null {
  if (!iso) return null;
  const m = /^(\d{4}-\d{2}-\d{2})/.exec(iso);
  return m ? m[1] : null;
}

function asString(v: unknown): string {
  return typeof v === 'string' ? v : '';
}

interface Seed {
  manual: boolean;
  project: { code: string; name: string };
  keyword: string;
  projectNo: string;
}

/** 마지막 제출 params → 폼 초기값 복원(종료 후 값 수정 재실행). 카탈로그 선택이었는지는
 *  keyword 가 이름에서 파생된 값과 같은지로 판별한다 — 다르면 직접 입력으로 되살린다. */
function seedFromParams(initial: Record<string, unknown> | undefined): Seed {
  const empty: Seed = {
    manual: false,
    project: { code: '', name: '' },
    keyword: '',
    projectNo: '',
  };
  const po = initial?.purchase_order as Record<string, unknown> | undefined;
  if (!po || typeof po !== 'object') return empty;
  const name = asString(po.project_name);
  const projectNo = asString(po.project_no);
  const keyword = asString(po.keyword);
  if (name && projectNo && deriveKeyword(name) === keyword) {
    return { ...empty, project: { code: projectNo, name } };
  }
  if (!keyword && !projectNo) return empty;
  return { manual: true, project: { code: '', name: '' }, keyword: keyword || name, projectNo };
}

export function PurchaseOrderPreRunForm({ disabled, initialParams, onStart }: PreRunFormProps) {
  // 마지막 제출값 복원 — 부모가 key 로 remount 하면 초기값이 다시 시드된다.
  const seed = useMemo(() => seedFromParams(initialParams), [initialParams]);
  const [project, setProject] = useState(() => seed.project);
  // 카탈로그에 없는 프로젝트용 폴백 — 검색어(필수) + 프로젝트 번호(선택)를 직접 입력.
  const [manual, setManual] = useState(seed.manual);
  const [manualKeyword, setManualKeyword] = useState(seed.keyword);
  const [manualNo, setManualNo] = useState(seed.projectNo);

  const [favorites, setFavorites] = useState<ComboOption[]>([]);
  const [syncedAt, setSyncedAt] = useState<string | null>(null);
  // 직전 검색이 0건이었는지 — 낡은 스냅샷 안내를 띄우는 신호.
  const [emptySearch, setEmptySearch] = useState(false);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const favs = await fetchFavorites('project');
        if (alive) setFavorites(toProjectOptions(favs));
      } catch {
        /* 백엔드 미배포 — 검색만 사용 */
      }
      try {
        // 필요한 건 스냅샷 시각뿐이라 행은 1건만 받는다.
        const page = await fetchCatalog({ kind: 'project', dept: 'all', limit: 1 });
        if (alive) setSyncedAt(page.syncedAt);
      } catch {
        /* 무시 — 동기화 시각 표기만 생략 */
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const search = useCallback(async (q: string): Promise<ComboOption[]> => {
    const page = await fetchCatalog({ kind: 'project', q, dept: 'all', limit: SEARCH_LIMIT });
    if (page.syncedAt) setSyncedAt(page.syncedAt);
    const options = toProjectOptions(page.items);
    setEmptySearch(options.length === 0);
    return options;
  }, []);

  // 제출값 — 카탈로그 선택이면 이름에서 검색어를 파생하고, 직접 입력이면 입력값 그대로 쓴다.
  const keyword = manual ? manualKeyword.trim() : deriveKeyword(project.name) || project.code;
  const projectNo = manual ? manualNo.trim() : project.code;
  const projectName = manual ? keyword : project.name || keyword;
  const canSubmit = !disabled && !!keyword && (manual || !!project.code);

  const syncedLabel = formatSyncedAt(syncedAt);

  const submit = () => {
    if (!canSubmit) return;
    onStart({
      purchase_order: { project_no: projectNo, project_name: projectName, keyword },
    });
  };

  return (
    <SectionCard
      caption="실행 전 입력"
      title="구매발주 — 대상 프로젝트"
      description="발주 계획을 세울 프로젝트를 먼저 고르고 실행하세요. 선택한 프로젝트 이름으로 ERP 도움창을 검색합니다."
      density="comfortable"
    >
      <div className="border-border/60 bg-muted/30 flex gap-2 rounded-[var(--radius-md)] border p-3">
        <RiInformationLine
          size={16}
          aria-hidden
          className="text-foreground-tertiary mt-0.5 shrink-0"
        />
        <p className="text-foreground-tertiary text-xs leading-relaxed">
          프로젝트 목록은 법인카드·출장과 같은 카탈로그를 씁니다.
          {syncedLabel ? <> 카탈로그 동기화: {syncedLabel}.</> : null} 목록에 없는 최근 프로젝트는
          아래 <b>직접 입력</b>으로 실행하세요.
        </p>
      </div>

      <div className="grid gap-3 sm:max-w-lg">
        <FormField
          id="po-project"
          label="프로젝트"
          required
          hint={
            manual
              ? '직접 입력을 사용하는 동안에는 목록 선택이 잠깁니다.'
              : emptySearch
                ? STALE_CATALOG_HINT
                : '이름 일부(예: CX85)로 검색해 고르세요. WBS 는 프로젝트 단위로 묶여 표시됩니다.'
          }
        >
          <CatalogCombobox
            value={project}
            placeholder="프로젝트 선택"
            favorites={favorites}
            disabled={disabled || manual}
            search={search}
            onSelect={(o) => {
              setProject({ code: o.code, name: o.name });
              setEmptySearch(false);
            }}
            onClear={() => setProject({ code: '', name: '' })}
          />
        </FormField>

        <div>
          <button
            type="button"
            disabled={disabled}
            onClick={() => setManual((v) => !v)}
            className="text-accent hover:text-accent/80 text-xs font-semibold underline underline-offset-2 disabled:opacity-50"
          >
            {manual ? '카탈로그에서 선택하기' : '카탈로그에 없나요? 직접 입력'}
          </button>
        </div>

        {manual ? (
          <div className="border-border/60 bg-muted/20 grid gap-3 rounded-[var(--radius-md)] border p-3 sm:grid-cols-[1fr_10rem]">
            <FormField
              id="po-manual-keyword"
              label="검색어"
              required
              hint="ERP 도움창에서 이 문자열로 찾습니다."
            >
              <Input
                id="po-manual-keyword"
                value={manualKeyword}
                disabled={disabled}
                placeholder="예: CX85-137"
                onChange={(e) => setManualKeyword(e.target.value)}
              />
            </FormField>
            <FormField id="po-manual-no" label="프로젝트 번호" hint="선택 — 알면 입력.">
              <Input
                id="po-manual-no"
                inputMode="numeric"
                value={manualNo}
                disabled={disabled}
                placeholder="예: 2297"
                onChange={(e) => setManualNo(e.target.value)}
              />
            </FormField>
          </div>
        ) : null}
      </div>

      {/* 제출 요약 — 도움창에 실제로 들어갈 검색어를 미리 보여준다(이름에서 파생되므로). */}
      <div className="border-border/60 bg-muted/30 flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-md)] border px-4 py-3">
        <div className="flex flex-col gap-0.5">
          <span className="text-foreground-tertiary text-[11px] font-semibold tracking-wider uppercase">
            ERP 검색어
          </span>
          <span className="text-foreground-tertiary text-xs">
            {projectName && projectName !== keyword ? projectName : '도움창에서 이 값으로 검색'}
          </span>
        </div>
        <div className="flex flex-col items-end">
          <span className="text-foreground text-lg font-semibold">{keyword || '—'}</span>
          <span className="text-foreground-tertiary text-xs tabular-nums">
            {projectNo ? `프로젝트 번호 ${projectNo}` : '프로젝트 번호 미지정'}
          </span>
        </div>
      </div>

      <div className="flex items-center justify-end">
        <Button
          type="button"
          onClick={submit}
          disabled={!canSubmit}
          title={
            canSubmit ? undefined : '프로젝트를 고르거나 검색어를 입력하면 실행할 수 있습니다.'
          }
        >
          <RiPlayLine size={15} aria-hidden />
          실행
        </Button>
      </div>
    </SectionCard>
  );
}
