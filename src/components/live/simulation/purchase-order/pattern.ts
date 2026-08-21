/**
 * 구매발주 계획서 — 발주 패턴 v2(발주그룹) 기반 발주단위 자동 편성.
 *
 * 계획서가 열릴 때 BOM 모듈을 패턴 그룹에 매칭해 발주단위를 미리 묶는다. **그룹 1개 =
 * 발주단위 1건**이고, EFEM 과 PROCESS 는 같은 공장이라도 발주가 따로 묶인다. 매칭되지 않은
 * 모듈은 풀에 남아 기존 수동 묶기로 처리하며, 사유(unmatched)는 계획서 배너로 노출한다.
 *
 * 매칭은 장비(machine) 단위로 훑는다 — 규격에 'EFEM-'/'Process-' 접두가 없는 BOM(MISC-ESR3
 * 실측 2026-08-14)을 장비명 발주묶음 판별로 잇기 위해 machine 컨텍스트가 필요하다.
 *
 * 전부 순수 함수다 — 유일한 부작용은 newOrderUnit(모듈 id 시퀀스)이며, 초기 시드 1회만
 * 호출된다(usePlanState 의 useState 초기화).
 */

import { PJT_PLACEHOLDER, bundleKey, type PatternGroup } from '@/lib/purchase/order-patterns';
import { newOrderUnit, type BomModule, type OrderUnit, type PlanBom } from './model';

/**
 * 미매칭 사유 — 배너 문구가 갈린다.
 * `no-pattern` = 어느 그룹에도 등록되지 않은 규격, `bundle-unknown` = 접미로는 등록돼 있으나
 * 장비명에서 발주묶음(EFEM/PROCESS)을 유일하게 판별하지 못한 경우(사용자 확정: 폴백 없음).
 */
export type UnmatchedReason = 'no-pattern' | 'bundle-unknown';

export interface UnmatchedModule {
  /** BOM 모듈 itemCode — 라벨은 배너가 bom.moduleMap 으로 찾는다. */
  code: string;
  reason: UnmatchedReason;
}

export interface MatchResult {
  units: OrderUnit[];
  unmatched: UnmatchedModule[];
}

/** 매칭 키 정규화 — 대소문자·연속 공백 차이를 흡수한다. */
function norm(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, ' ');
}

// ── 매칭 인덱스 ──────────────────────────────────────────────────────────────

interface PatternIndex {
  /**
   * norm(규격) → 등록 그룹들. 같은 규격이 여러 발주묶음에 등록될 수 있어(예: 'T Axis Assy'
   * 를 EFEM·PROCESS 양쪽에 교정 등록) 값이 배열이다 — 복수면 장비명으로 가른다.
   */
  exact: Map<string, PatternGroup[]>;
  /** bundleKey → norm(접미) → 그룹. 접미 = 규격에서 발주묶음 접두를 벗긴 나머지. */
  suffix: Map<string, Map<string, PatternGroup>>;
  /** 장비명 판별 후보 — 등록된 bundleKey 집합(등장 순). */
  bundles: string[];
}

/** 규격에서 발주묶음 접두('EFEM-'·'Process ')를 벗긴 나머지 — 접두가 없으면 규격 그대로. */
function suffixOf(spec: string, bundle: string): string {
  const key = bundleKey(bundle);
  const text = spec.trim();
  if (!key || text.length <= key.length + 1) return spec;
  if (text.slice(0, key.length).toUpperCase() !== key) return spec;
  const sep = text[key.length];
  return sep === '-' || sep === ' ' ? text.slice(key.length + 1) : spec;
}

function buildIndex(groups: readonly PatternGroup[]): PatternIndex {
  const exact = new Map<string, PatternGroup[]>();
  const suffix = new Map<string, Map<string, PatternGroup>>();
  const bundles: string[] = [];
  for (const group of groups) {
    const key = bundleKey(group.bundle);
    if (key && !bundles.includes(key)) bundles.push(key);
    let bySuffix = suffix.get(key);
    if (!bySuffix) {
      bySuffix = new Map();
      suffix.set(key, bySuffix);
    }
    for (const module of group.modules) {
      const spec = norm(module.spec);
      const registered = exact.get(spec);
      if (!registered) exact.set(spec, [group]);
      else if (!registered.includes(group)) registered.push(group);
      // 접미 중복은 첫 등록이 이긴다 — 타 그룹 간 중복은 검증기가 저장 단계에서 거부하고,
      // 같은 그룹 안 중복(무접두 규격 교정 등록)은 어느 쪽이 이겨도 같은 그룹이다.
      const key2 = norm(suffixOf(module.spec, group.bundle));
      if (key2 && !bySuffix.has(key2)) bySuffix.set(key2, group);
    }
  }
  return { exact, suffix, bundles };
}

/** 장비명에서 발주묶음 판별 — 유일하게 포함된 bundleKey. 0개·2개 이상이면 판별 실패. */
function bundleOf(machineName: string, bundles: readonly string[]): string | undefined {
  const haystack = machineName.toUpperCase();
  const hits = bundles.filter((b) => haystack.includes(b));
  return hits.length === 1 ? hits[0] : undefined;
}

type ModuleMatch = { group: PatternGroup } | { reason: UnmatchedReason };

/**
 * 모듈 1건의 그룹 매칭 — ① 정확(규격 → 품명) ② 접미(장비명 발주묶음 판별 후) ③ 미매칭.
 *
 * ⚠ 실측(2026-08-13)상 ERP 규격이 'Process-Frame Assy' 쪽이지만, name/spec 이 뒤집혀 오는
 *   BOM 관측도 있어 두 필드를 모두 패턴 규격과 대조한다(v1 방침 유지).
 */
function matchModule(module: BomModule, machineName: string, index: PatternIndex): ModuleMatch {
  const keys = [norm(module.spec), norm(module.name)].filter(Boolean);
  const bundle = bundleOf(machineName, index.bundles);

  for (const key of keys) {
    const hit = index.exact.get(key);
    if (!hit) continue;
    if (hit.length === 1) return { group: hit[0] };
    // 같은 규격이 여러 발주묶음에 등록됐다 — 장비명으로 가르고, 못 가르면 미매칭.
    const narrowed = bundle ? hit.filter((g) => bundleKey(g.bundle) === bundle) : [];
    return narrowed.length === 1 ? { group: narrowed[0] } : { reason: 'bundle-unknown' };
  }

  if (bundle) {
    const bySuffix = index.suffix.get(bundle);
    for (const key of keys) {
      const group = bySuffix?.get(key);
      if (group) return { group };
    }
    return { reason: 'no-pattern' };
  }
  // 판별 실패 — 어느 묶음엔가 접미로 등록된 규격이면 원인이 장비명 판별이고, 아니면 미등록이다.
  const registered = keys.some((key) => [...index.suffix.values()].some((m) => m.has(key)));
  return { reason: registered ? 'bundle-unknown' : 'no-pattern' };
}

// ── 초기 발주단위 시드 ──────────────────────────────────────────────────────

/** 패턴 구매사유에서 프로젝트 치환자를 걷어낸 조각 — 입력란에 그대로 들어가는 값. */
function reasonFragment(reason: string): string {
  return reason.split(PJT_PLACEHOLDER).join(' ').replace(/\s+/g, ' ').trim();
}

/**
 * 패턴으로 편성한 초기 발주단위 — 패턴이 없거나 매칭 0이면 빈 배열(기존 수동 묶기 그대로).
 *
 * 단위 순서·seq(1..N)는 **그룹 배열 순서**를 따르고, 단위 안의 모듈 순서는 BOM 순서를 따른다.
 * 각 단위는 그룹 규칙 스냅샷(patternRule)을 물고 가며, 이후 납기 재시드·예외 해석은 전부
 * 그 스냅샷만 본다(패턴 설정을 다시 읽지 않는다 — model.ts vendorDefaultsOf 참조).
 */
export function matchPatternUnits(bom: PlanBom, groups: readonly PatternGroup[]): MatchResult {
  if (groups.length === 0) return { units: [], unmatched: [] };

  const index = buildIndex(groups);
  const byGroup = new Map<string, string[]>();
  const unmatched: UnmatchedModule[] = [];

  for (const machine of bom.machines) {
    for (const module of machine.modules) {
      const result = matchModule(module, machine.name, index);
      if ('reason' in result) {
        unmatched.push({ code: module.itemCode, reason: result.reason });
        continue;
      }
      const codes = byGroup.get(result.group.id);
      if (codes) codes.push(module.itemCode);
      else byGroup.set(result.group.id, [module.itemCode]);
    }
  }

  const units = groups
    .filter((g) => byGroup.has(g.id))
    .map((group, i) => ({
      ...newOrderUnit(i + 1, byGroup.get(group.id) ?? [], reasonFragment(group.reason)),
      patternRule: {
        groupId: group.id,
        groupName: group.name,
        bundle: group.bundle,
        due: group.due,
        exceptions: group.exceptions,
      },
    }));

  return { units, unmatched };
}
