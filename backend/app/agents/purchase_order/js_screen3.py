"""화면 ③ 구매발주일괄입력[나인벨](PUOORD02000) 전용 JS — 2026-08-28 헤디드 프로브
`e2e/purchase_order_screen3_ops_probe.py`(run2 전 항목 PASS)에서 승격. PROCESS.md '화면 ③ 조작 실측' 참조.

두 스코프: (1) `구매요청` 팝업(.k-window, 최근 열린 비-법인카드 창) 안의 flat 그리드[0],
(2) 메인 화면 grid[0]=마스터(거래처 1행) / grid[1]=디테일. 체크는 checkRow/checkAll/getCheckedRows 만.
"""

from __future__ import annotations

_POP = (
    "  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();\n"
    "  const p = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)\n"
    "    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];"
)


def _pop_js(params: str, body: str) -> str:
    return f"({params}) => {{\n{_POP}\n{body}\n}}"


# 팝업 존재+제목 — {present, title}.
POPUP_PRESENT_JS = _pop_js(
    "",
    "  return p ? { present: true, title: c((p.querySelector('.k-window-title')||{}).innerText) } : { present: false };",
)

# 팝업 grid[idx] 행수 — 조회 반영 대기용. -1 = 없음.
POPUP_GRID_COUNT_JS = _pop_js(
    "gridIdx",
    """  if (!p) return -1;
  const el = [...p.querySelectorAll('.dews-ui-grid')][gridIdx];
  if (!el) return -1;
  try { return window.jQuery(el).data('dewsControl')._grid.getDataSource().getRowCount(); } catch (e) { return -1; }""",
)

# 팝업 grid[idx] 전량 원시 행(getJsonRows). arg [gridIdx, limit].
POPUP_GRID_ROWS_JS = _pop_js(
    "[gridIdx, limit]",
    """  if (!p) return { ok: false, reason: 'no-popup' };
  const el = [...p.querySelectorAll('.dews-ui-grid')][gridIdx];
  if (!el) return { ok: false, reason: 'no-grid-' + gridIdx };
  try {
    const g = window.jQuery(el).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const take = Math.min(limit, n);
    const rows = take > 0 ? ds.getJsonRows(0, take - 1) : [];
    return { ok: true, rowCount: n, rows };
  } catch (e) { return { ok: false, err: String(e).slice(0, 150) }; }""",
)

# 팝업 grid[idx] 체크 전체 on/off. arg [gridIdx, on] → {ok, before, after}.
POPUP_CHECK_ALL_JS = _pop_js(
    "[gridIdx, on]",
    """  if (!p) return { ok: false, reason: 'no-popup' };
  const el = [...p.querySelectorAll('.dews-ui-grid')][gridIdx];
  if (!el) return { ok: false, reason: 'no-grid' };
  try {
    const g = window.jQuery(el).data('dewsControl')._grid;
    const before = (g.getCheckedRows() || []).length;
    g.checkAll(!!on);
    const after = (g.getCheckedRows() || []).length;
    return { ok: true, before, after };
  } catch (e) { return { ok: false, err: String(e).slice(0, 150) }; }""",
)

# 팝업 grid[idx] 지정 행 checkRow(true). arg [gridIdx, rows] → {ok, checked}.
POPUP_CHECK_ROWS_JS = _pop_js(
    "[gridIdx, rows]",
    """  if (!p) return { ok: false, reason: 'no-popup' };
  const el = [...p.querySelectorAll('.dews-ui-grid')][gridIdx];
  if (!el) return { ok: false, reason: 'no-grid' };
  try {
    const g = window.jQuery(el).data('dewsControl')._grid;
    for (const r of rows) g.checkRow(r, true);
    return { ok: true, checked: (g.getCheckedRows() || []).slice() };
  } catch (e) { return { ok: false, err: String(e).slice(0, 150) }; }""",
)

# 팝업 grid[idx] 지정 행들의 필드 값. arg [gridIdx, idxs, fields] → {idx: {field: value}}.
POPUP_FIELDS_JS = _pop_js(
    "[gridIdx, idxs, fields]",
    """  if (!p) return {};
  const el = [...p.querySelectorAll('.dews-ui-grid')][gridIdx];
  if (!el) return {};
  try {
    const ds = window.jQuery(el).data('dewsControl')._grid.getDataSource();
    const out = {};
    for (const i of idxs) {
      const row = {};
      for (const f of fields) { try { row[f] = ds.getValue(i, f); } catch (e) { row[f] = null; } }
      out[i] = row;
    }
    return out;
  } catch (e) { return {}; }""",
)

# 팝업 하단 '적용'(button.confirm.ok) 중앙 좌표 — 팝업 스코프(다른 k-window 의 동명 버튼 오클릭 방지).
POPUP_BOTTOM_APPLY_BOX_JS = _pop_js(
    "",
    """  if (!p) return null;
  const b = [...p.querySelectorAll('button.confirm.ok, button.dews-ui-button.confirm.ok')].find(x => x.offsetParent !== null);
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return { x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2) };""",
)

# ── 메인 화면(팝업 밖) — grid[0] 마스터 / grid[1] 디테일 ─────────────────────────
MAIN_GRID_COUNT_JS = r"""(gridIdx) => {
  const el = document.querySelectorAll('.dews-ui-grid')[gridIdx];
  if (!el) return -1;
  try { return window.jQuery(el).data('dewsControl')._grid.getDataSource().getRowCount(); } catch (e) { return -1; }
}"""

MAIN_GRID_ROWS_JS = r"""([gridIdx, limit]) => {
  const el = document.querySelectorAll('.dews-ui-grid')[gridIdx];
  if (!el) return { ok: false, reason: 'no-grid-' + gridIdx };
  try {
    const g = window.jQuery(el).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const take = Math.min(limit, n);
    const rows = take > 0 ? ds.getJsonRows(0, take - 1) : [];
    return { ok: true, rowCount: n, rows };
  } catch (e) { return { ok: false, err: String(e).slice(0, 150) }; }
}"""

MAIN_CHECK_ALL_JS = r"""([gridIdx, on]) => {
  const el = document.querySelectorAll('.dews-ui-grid')[gridIdx];
  if (!el) return { ok: false, reason: 'no-grid' };
  try {
    const g = window.jQuery(el).data('dewsControl')._grid;
    const before = (g.getCheckedRows() || []).length;
    g.checkAll(!!on);
    const after = (g.getCheckedRows() || []).length;
    return { ok: true, before, after };
  } catch (e) { return { ok: false, err: String(e).slice(0, 150) }; }
}"""

MAIN_FIELDS_JS = r"""([gridIdx, idxs, fields]) => {
  const el = document.querySelectorAll('.dews-ui-grid')[gridIdx];
  if (!el) return {};
  try {
    const ds = window.jQuery(el).data('dewsControl')._grid.getDataSource();
    const out = {};
    for (const i of idxs) {
      const row = {};
      for (const f of fields) { try { row[f] = ds.getValue(i, f); } catch (e) { row[f] = null; } }
      out[i] = row;
    }
    return out;
  } catch (e) { return {}; }
}"""

# grid[idx] 캔버스 rect — 마스터 행 실클릭 좌표 계산(헤더 ~30px + 행 32px, 프로브 실측).
MAIN_GRID_RECT_JS = r"""(gridIdx) => {
  const el = document.querySelectorAll('.dews-ui-grid')[gridIdx];
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
}"""

# grid[idx] 현재 행(itemIndex) — 실클릭이 의도한 행을 잡았는지 독립 확인(2026-08-28 실측: 헤더 높이
# 추정 오차로 1행 클릭이 5행 선택). 반환 int | -1.
MAIN_CURRENT_ROW_JS = r"""(gridIdx) => {
  const el = document.querySelectorAll('.dews-ui-grid')[gridIdx];
  if (!el) return -1;
  try {
    const cur = window.jQuery(el).data('dewsControl')._grid.getCurrent() || {};
    const i = cur.itemIndex ?? cur.dataRow ?? -1;
    return typeof i === 'number' ? i : -1;
  } catch (e) { return -1; }
}"""

# 마스터 grid[0] 셀 에디터 오픈(setCurrent+showEditor) — RMK_DC 인라인 편집. arg [itemIndex, fieldName].
MAIN_OPEN_EDITOR_JS = r"""([itemIndex, fieldName]) => {
  const el = document.querySelectorAll('.dews-ui-grid')[0];
  if (!el) return { ok: false, reason: 'no-grid' };
  try {
    const g = window.jQuery(el).data('dewsControl')._grid;
    g.setCurrent({ itemIndex, fieldName });
    g.showEditor();
    return { ok: true };
  } catch (e) { return { ok: false, err: String(e).slice(0, 150) }; }
}"""

# 마스터 인라인 에디터 오버레이(input id 가 '_mstGrid_line' 로 끝나는 보이는 input) 좌표/값.
MAIN_EDITOR_INPUT_JS = r"""() => {
  for (const i of document.querySelectorAll('input')) {
    if (i.offsetParent === null || !/_mstGrid_line$/.test(i.id || '')) continue;
    const r = i.getBoundingClientRect();
    if (r.width <= 1) continue;
    return { id: i.id, value: i.value, x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2), w: Math.round(r.width) };
  }
  return null;
}"""
