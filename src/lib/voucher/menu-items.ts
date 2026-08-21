/**
 * 메뉴 필터 항목 — 유형별 전표조회 승인(voucher-by-type)의 메뉴(MENU_NM) 필터 마스터 목록.
 *
 * 목록 자체는 **관리자가 에이전트 관리에서 추가/삭제**하는 공유 데이터
 * (agent.settings.menu_items)이고, 실행 전 폼은 이 목록에서 체크만 해
 * params.voucher.menu_filters(라벨 목록)로 보낸다 — ERP 대조 값은 label 이다.
 * 백엔드 `app/services/agent_settings.py`(MENU_ITEMS_KEY·DEFAULT_MENU_ITEMS·MAX_MENU_ITEMS)의 미러.
 */

/** 메뉴 필터 한 행 — 백엔드 menu_items 행과 동일 형태. */
export interface VoucherMenuItem {
  id: string;
  label: string;
  /** 실행 전 폼에서 초기 체크될지 여부(관리자가 정하는 기본값). */
  defaultSelected: boolean;
}

/** 설정 키(백엔드와 동일). */
export const MENU_ITEMS_KEY = 'menu_items';

/** 등록 가능한 최대 항목 수(백엔드 MAX_MENU_ITEMS 미러). */
export const MAX_MENU_ITEMS = 20;

/** 저장값이 없을 때의 기본 메뉴 항목(백엔드 DEFAULT_MENU_ITEMS 미러 — id 까지 동일). */
export const DEFAULT_MENU_ITEMS: readonly VoucherMenuItem[] = [
  { id: 'sales-entry', label: '매출등록', defaultSelected: true },
  { id: 'sales-cancel', label: '매출취소', defaultSelected: true },
  { id: 'export-cost', label: '수출비용입력[나인벨]', defaultSelected: false },
];

type Settings = Record<string, unknown>;

/**
 * 실효 설정에서 메뉴 항목 목록을 읽는다 — 부재·비배열은 기본 3종. 개별 행 파손(id/label 누락,
 * id 중복)은 그 행만 건너뛰고, 남는 행이 없으면 기본 3종으로 폴백한다.
 */
export function menuItemsFromSettings(settings: Settings | undefined): VoucherMenuItem[] {
  const raw = settings?.[MENU_ITEMS_KEY];
  if (!Array.isArray(raw)) return DEFAULT_MENU_ITEMS.map((m) => ({ ...m }));
  const items: VoucherMenuItem[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== 'object') continue;
    const { id, label, defaultSelected } = entry as Record<string, unknown>;
    if (typeof id !== 'string' || !id || typeof label !== 'string' || !label) continue;
    if (items.some((it) => it.id === id)) continue;
    items.push({ id, label, defaultSelected: defaultSelected === true });
  }
  return items.length > 0 ? items : DEFAULT_MENU_ITEMS.map((m) => ({ ...m }));
}

let idSeq = 0;
/** 새 메뉴 항목 id — 안정 식별자(라벨과 무관). 기존 id 와 겹치지 않게 접두 + 시퀀스. */
export function newMenuItemId(): string {
  idSeq += 1;
  return `m${Date.now().toString(36)}${idSeq}`;
}
