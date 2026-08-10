'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { RiErrorWarningLine, RiPlayLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { DatePicker } from '@/components/ui/date-picker';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { SectionCard } from '@/components/ui/section-card';
import { fetchCatalog, fetchFavorites, fetchTripDefaults } from '@/lib/api/me-codes';
import { CatalogCombobox, type ComboOption, projectCodeLabel } from './catalog-combobox';
import type { PreRunFormProps } from './index';

// 합리적 상한(오타·단위 실수 방지) — 학자금 금액(공급가액) 1억 원.
const MAX_AMOUNT = 100_000_000;

/** 로컬 오늘(UTC 오프셋으로 하루 밀리지 않게 로컬 기준 yyyy-mm-dd). */
function todayLocal(): string {
  const d = new Date();
  const off = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - off).toISOString().slice(0, 10);
}

/** 양의 정수 + 상한 검증(빈값·소수·NaN·초과는 무효). ERP 금액은 정수다. */
function isPositiveIntWithin(value: string, max: number): boolean {
  const n = Number(value);
  return Number.isInteger(n) && n > 0 && n <= max;
}

/**
 * 금액을 한글 원화 표기로(억·만 단위). 예: 500000 → "50만원", 1234567 → "123만 4,567원".
 * 숫자 표기(정확값) 보조용 — 읽기 편하게 만/억 단위로 끊어 보여준다. 0 이하·비수는 빈 문자열.
 */
function toKoreanWon(amount: number): string {
  if (!Number.isFinite(amount) || amount <= 0) return '';
  const EOK = 100_000_000;
  const MAN = 10_000;
  let rest = Math.floor(amount);
  const eok = Math.floor(rest / EOK);
  rest %= EOK;
  const man = Math.floor(rest / MAN);
  rest %= MAN;
  const parts: string[] = [];
  if (eok) parts.push(`${eok.toLocaleString('ko-KR')}억`);
  if (man) parts.push(`${man.toLocaleString('ko-KR')}만`);
  if (rest) parts.push(rest.toLocaleString('ko-KR'));
  return `${parts.join(' ')}원`;
}

/** 프로젝트 선택값(code+name) — 콤보박스가 두 값을 함께 세팅/해제한다. */
interface ProjectPick {
  code: string;
  name: string;
}

/** 마지막 제출 params(초기값 복원용)를 폼 초기값으로 되돌린다. 없으면 빈 결과. */
function seedFromParams(initial: Record<string, unknown> | undefined): {
  evidenceDate?: string;
  baseAmount?: string;
  project?: ProjectPick;
} {
  const hj = initial?.hakjagum as Record<string, unknown> | undefined;
  if (!hj || typeof hj !== 'object') return {};
  const project = (hj.project ?? {}) as { code?: string; name?: string };
  return {
    evidenceDate: typeof hj.evidenceDate === 'string' ? hj.evidenceDate : undefined,
    baseAmount: hj.baseAmount != null ? String(hj.baseAmount) : undefined,
    project: project.code ? { code: project.code, name: project.name ?? '' } : undefined,
  };
}

export function HakjagumPreRunForm({ disabled, initialParams, onStart }: PreRunFormProps) {
  // 마지막 제출값 복원(실패 후 값 수정 재실행) — 부모가 key 로 remount 하면 초기값이 다시 시드된다.
  const seed = useMemo(() => seedFromParams(initialParams), [initialParams]);
  const [evidenceDate, setEvidenceDate] = useState<string>(() => seed.evidenceDate ?? todayLocal());
  const [baseAmount, setBaseAmount] = useState<string>(() => seed.baseAmount ?? '');
  const [project, setProject] = useState<ProjectPick>(() => seed.project ?? { code: '', name: '' });

  // 프로젝트 자주쓰는 + 팀 비용구분(판/제) 기본 프로젝트 — overseas 폼과 동일 규칙(D11).
  const [projectFavs, setProjectFavs] = useState<ComboOption[]>([]);
  const [favsLoaded, setFavsLoaded] = useState(false);
  const [tripDefaultProject, setTripDefaultProject] = useState<ComboOption | null | undefined>(
    undefined,
  );

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const favs = await fetchFavorites('project');
        if (alive) {
          setProjectFavs(
            favs.map((f) => ({
              code: f.code,
              name: f.name,
              codeLabel: projectCodeLabel(f.code, f.extra?.pjtNo ?? undefined),
              sub: f.extra?.wbsNm ?? f.extra?.wbsNo ?? undefined,
              isDefault: f.isDefault,
            })),
          );
        }
      } catch {
        /* 백엔드 미배포 — 검색만 사용 */
      }
      if (alive) setFavsLoaded(true);
    })();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const d = await fetchTripDefaults();
        if (!alive) return;
        const p = d.defaultProject;
        setTripDefaultProject(
          p ? { code: p.code, name: p.name, codeLabel: projectCodeLabel(p.code) } : null,
        );
      } catch {
        if (alive) setTripDefaultProject(null);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // 기본 프로젝트 = 팀 비용구분 프로젝트 우선, 없으면 기본지정(★) 즐겨찾기 폴백(overseas 와 동일).
  const projectDefault = useMemo(
    () => tripDefaultProject ?? projectFavs.find((p) => p.isDefault),
    [tripDefaultProject, projectFavs],
  );

  // 기본 프로젝트 1회 백필 — 두 비동기 소스 확정 후, 비어 있을(code 없음) 때만 채운다. ref 가드.
  const defaultsApplied = useRef(false);
  useEffect(() => {
    if (defaultsApplied.current) return;
    if (!favsLoaded || tripDefaultProject === undefined) return;
    defaultsApplied.current = true;
    if (!projectDefault) return;
    setProject((p) => (p.code ? p : { code: projectDefault.code, name: projectDefault.name }));
  }, [favsLoaded, tripDefaultProject, projectDefault]);

  const amountValid = isPositiveIntWithin(baseAmount, MAX_AMOUNT);
  const canSubmit = !disabled && !!evidenceDate.trim() && !!project.code.trim() && amountValid;

  // 최종 공급가액 미리보기 — 입력 금액 그대로 공급가액(감액 규칙 없음, 백엔드와 동일).
  const supplyPreview = amountValid ? Number(baseAmount) : null;

  const submit = () => {
    if (!canSubmit) return;
    // 백엔드 parse_hakjagum_params 계약: params["hakjagum"] = 단건 객체.
    // department·cost_type 은 서버가 세션(본인 부서·팀 비용구분)에서 주입하므로 폼은 보내지 않는다
    // (runs.py 가 클라이언트 제공 department/cost_type 을 권위키로 폐기 — overseas 와 동일).
    onStart({
      hakjagum: {
        evidenceDate,
        baseAmount: Number(baseAmount),
        project: { code: project.code, name: project.name },
      },
    });
  };

  return (
    <SectionCard
      caption="실행 전 입력"
      title="학자금신청서 결의서"
      description="회계일·학자금 금액·프로젝트만 입력하면 무개입으로 채워 저장합니다. 거래처·적요는 작성자 본인 이름으로, 예산단위(복리후생비-기타)는 소속 팀 비용구분으로 자동 지정됩니다."
      density="comfortable"
    >
      {/* 저장 비가역 주의 — F7 저장까지 자동, 상신은 직접 */}
      <div className="border-warning/40 bg-warning/5 flex gap-2 rounded-[var(--radius-md)] border p-3">
        <RiErrorWarningLine size={16} aria-hidden className="text-warning mt-0.5 shrink-0" />
        <div className="text-xs">
          <p className="text-foreground-secondary font-semibold">
            저장 비가역 주의 — 실행하면 F7 저장까지 자동으로 진행됩니다
          </p>
          <p className="text-foreground-tertiary mt-1 leading-relaxed">
            값(회계일·금액·프로젝트)을 다시 확인하세요. 저장 후 <b>상신(결재)</b>은 자동화하지
            않습니다 — ERP 에서 직접 진행하세요.
          </p>
        </div>
      </div>

      <div className="grid gap-5 sm:max-w-md">
        {/* 회계일(=계산서일 단일 날짜) */}
        <FormField
          id="hj-evidence-date"
          label="회계일"
          required
          hint="회계일자를 계산서일자로 그대로 사용합니다."
        >
          <DatePicker
            ariaLabel="회계일"
            value={evidenceDate}
            disabled={disabled}
            onChange={setEvidenceDate}
          />
        </FormField>

        {/* 학자금 금액 */}
        <FormField
          id="hj-base-amount"
          label="학자금 금액"
          required
          error={
            baseAmount && !amountValid
              ? `1 ~ ${MAX_AMOUNT.toLocaleString('ko-KR')} 정수로 입력하세요.`
              : undefined
          }
          hint={amountValid ? undefined : '지급할 학자금 금액을 직접 입력합니다.'}
        >
          <Input
            id="hj-base-amount"
            type="number"
            min={1}
            max={MAX_AMOUNT}
            step={1}
            inputMode="numeric"
            value={baseAmount}
            disabled={disabled}
            placeholder="예: 1000000"
            onChange={(e) => setBaseAmount(e.target.value)}
          />
        </FormField>

        {/* 프로젝트 */}
        <FormField id="hj-project" label="프로젝트" required>
          <CatalogCombobox
            value={project}
            placeholder="프로젝트 선택"
            favorites={projectFavs}
            disabled={disabled}
            search={async (q) => {
              const page = await fetchCatalog({ kind: 'project', q, dept: 'all', limit: 25 });
              return page.items.map((c) => ({
                code: c.code,
                name: c.name,
                codeLabel: projectCodeLabel(c.code, c.extra?.pjtNo ?? undefined),
                sub: c.extra?.wbsNm ?? c.extra?.wbsNo ?? undefined,
              }));
            }}
            onSelect={(o) => setProject({ code: o.code, name: o.name })}
            onClear={() => setProject({ code: '', name: '' })}
          />
        </FormField>
      </div>

      {/* 최종 공급가액 미리보기 — 입력 금액 그대로 공급가액(감액 규칙 없음) */}
      <div className="border-border/60 bg-muted/30 flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-md)] border px-4 py-3">
        <div className="flex flex-col gap-0.5">
          <span className="text-foreground-tertiary text-[11px] font-semibold tracking-wider uppercase">
            최종 공급가액
          </span>
          <span className="text-foreground-tertiary text-xs">입력 금액 그대로 공급가액</span>
        </div>
        <div className="flex flex-col items-end">
          <span className="text-foreground text-xl font-semibold tabular-nums">
            {supplyPreview != null ? `${supplyPreview.toLocaleString('ko-KR')}원` : '—'}
          </span>
          {supplyPreview != null ? (
            <span className="text-foreground-tertiary text-xs">{toKoreanWon(supplyPreview)}</span>
          ) : null}
        </div>
      </div>

      <div className="flex items-center justify-end">
        <Button
          type="button"
          onClick={submit}
          disabled={!canSubmit}
          title={canSubmit ? undefined : '모든 필수 입력을 완료하면 실행할 수 있습니다.'}
        >
          <RiPlayLine size={15} aria-hidden />
          실행
        </Button>
      </div>
    </SectionCard>
  );
}
