"""구매발주(purchase-order) 화면 ① PUOPRQ00200 전용 JS — 읽기/조회조건 확정 단일 소스.

`e2e/purchase_order_{project_apply,checkbox_filter,bom_grid}_probe.py`(2026-08-13 라이브
읽기 프로브, 부작용 0)에서 검증된 JS 를 그대로 승격했다. 전부 읽기 또는 조회조건 확정
(프로젝트 선택·체크박스·조회 버튼 좌표)용이며 **저장·결재·행 데이터 변경 JS 는 없다**.

프로젝트 도움창은 js_lib 의 WBS 스키마 피커(PROJECT_READ_JS 등)와 필드가 다르다
(PJT_NO/PJT_NM — WBS_NO 아님, 검색 입력 #keyword — #s_search_key 아님). 그래서 이 화면
전용 JS 를 여기 두고, 피커 버튼 좌표만 js_lib.PROJECT_PICKER_BOX_JS 를 재사용한다.
"""

from __future__ import annotations

# 화면에 떠 있는 k-window(팝업) 타이틀 목록 — 도움창 열림/소멸 판정(프로브 실측: 같은 팝업
# 인스턴스 2회째 검색 시 간헐 소멸 → 열림 상태를 매번 이걸로 확인한다).
WIN_STATE_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  return wins.map(w => ({ title: c((w.querySelector('.k-window-title')||{}).innerText) }));
}"""

# 프로젝트 도움창 검색어 입력(#keyword — 네이티브 setter + input 이벤트). arg = q.
SET_KEYWORD_JS = r"""(q) => {
  const i = document.querySelector('#keyword');
  if (!i) return false;
  const s = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(i), 'value').set;
  s.call(i, q); i.dispatchEvent(new Event('input', { bubbles: true })); i.focus();
  return true;
}"""

# 도움창 결과 그리드(플랫 .dews-ui-grid) 상위 limit 행 — PJT_NO/PJT_NM + 담당·기간·상태.
# arg = limit. 프로브 READ_POPUP_GRID_JS 에 개입 카드 description 용 필드를 추가한 판.
READ_POPUP_GRID_JS = r"""(limit) => {
  const wins = [...document.querySelectorAll('.k-window')].filter(d => d.offsetParent !== null);
  const dlg = wins[wins.length - 1];
  if (!dlg) return { ok: false, reason: 'no-window' };
  const gridEl = dlg.querySelector('.dews-ui-grid');
  if (!gridEl) return { ok: false, reason: 'no-grid' };
  try {
    const g = window.jQuery(gridEl).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const take = Math.min(limit, n);
    const rows = take > 0 ? ds.getJsonRows(0, take - 1) : [];
    const clean = v => (v == null || v === 'null') ? '' : String(v).trim();
    return { ok: true, rowCount: n, rows: rows.map(r => ({
      PJT_NO: clean(r.PJT_NO), PJT_NM: clean(r.PJT_NM),
      START_DT: clean(r.START_DT), END_DT: clean(r.END_DT),
      RSPNBER_EMP_NM: clean(r.RSPNBER_EMP_NM), PJT_ST_NM: clean(r.PJT_ST_NM),
    })) };
  } catch (e) { return { ok: false, err: String(e).slice(0, 100) }; }
}"""

# 도움창 결과에서 PJT_NO 행 선택(setCurrent+setSelection, fieldName='PJT_NM') — 프로브 검증
# 2/2(CX85-137=2297·ZJ90-130=2261). arg = pjtNo.
SELECT_ROW_JS = r"""(pjtNo) => {
  const wins = [...document.querySelectorAll('.k-window')].filter(d => d.offsetParent !== null);
  const dlg = wins[wins.length - 1];
  if (!dlg) return { ok: false, reason: 'no-window' };
  try {
    const g = window.jQuery(dlg.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const rows = ds.getJsonRows(0, ds.getRowCount() - 1);
    const i = rows.findIndex(r => String(r.PJT_NO) === String(pjtNo));
    if (i < 0) return { ok: false, reason: 'not-found', have: rows.map(r => r.PJT_NO) };
    g.setCurrent({ itemIndex: i, fieldName: 'PJT_NM' });
    g.setSelection({ startRow: i, endRow: i, startColumn: 0, endColumn: 0 });
    return { ok: true, name: rows[i].PJT_NM };
  } catch (e) { return { ok: false, err: String(e).slice(0, 100) }; }
}"""

# 도움창 '적용' 버튼 좌표 — 실클릭용(적용 = 조회조건 확정, 데이터 생성 아님).
APPLY_BTN_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window')].filter(d => d.offsetParent !== null);
  const dlg = wins[wins.length - 1];
  if (!dlg) return null;
  const btn = [...dlg.querySelectorAll('button')].find(b => b.offsetParent !== null && c(b.innerText) === '적용');
  if (!btn) return null;
  const r = btn.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# 조회(F2) 버튼 좌표(button.main-button.lookup) — 이 화면은 조회 확인 다이얼로그가 없다
# (프로브 5회 실측 정정 — '초기화: 예' 문구 미발생).
LOOKUP_BTN_JS = r"""() => {
  const b = document.querySelector('button.main-button.lookup');
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# 라벨 기준 체크박스 rect+checked — 구매요청/이동요청 공용.
# ⚠ 실측(2026-08-13): 두 체크박스는 같은 <span> 에 나란해 li/div 스코프 탐색은 항상 첫 번째
#   (#s_pu_chk)만 잡는 버그다 — **label[for] 직결로만** 찾는다(구매요청=#s_pu_chk,
#   이동요청=#s_move_chk). arg = label.
CHECKBOX_RECT_JS = r"""(label) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const lbl = [...document.querySelectorAll('label[for]')].find(e => e.offsetParent !== null && c(e.innerText) === label);
  if (!lbl) return null;
  const cb = document.getElementById(lbl.getAttribute('for'));
  if (!cb) return null;
  const r = cb.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2), checked: cb.checked, id: cb.id };
}"""

# BOM 트리그리드(.dews-ui-treegrid) 행수 — 조회(F2) 후 로드 폴링용. 미존재 -1.
TREEGRID_COUNT_JS = r"""() => {
  try {
    const el = document.querySelector('.dews-ui-treegrid');
    if (!el) return -1;
    return window.jQuery(el).data('dewsControl')._grid.getDataSource().getRowCount();
  } catch (e) { return -1; }
}"""

# BOM 트리그리드 필터 시그니처 {count, mvY} — mvY = MV_FG='Y' 행수(체크박스 프로브 실측:
# 무필터 410행/mvY 56, 구매요청만 354행/mvY 0). '구매요청만' 조회(F2)의 stale-grid 판정용 —
# 직전 무필터 결과가 남아 있으면 행수가 우연히 같아도 mvY(내용)로 구별된다. 미존재/예외 null.
TREEGRID_MV_SIG_JS = r"""() => {
  try {
    const el = document.querySelector('.dews-ui-treegrid');
    if (!el) return null;
    const g = window.jQuery(el).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const count = ds.getRowCount();
    let mvY = 0;
    for (let i = 0; i < count; i++) {
      try { if (g.getValue(i, 'MV_FG') === 'Y') mvY++; } catch (e) {}
    }
    return { count, mvY };
  } catch (e) { return null; }
}"""

# BOM 트리그리드 전량 읽기 — ⚠ getJsonRows 는 트리그리드에서 null(플랫 전용 API, 실측).
# `getLevel(i)` + `getValue(i, field)` 루프가 유일한 경로(410행 실측 성공). 지정 필드만 읽어
# 페이로드를 제한한다(전량 42열 × 400행은 불필요). arg = fields(string[]).
# 레벨(0-idx): 0=프로젝트 / 1=장비 / 2=모듈(구조) / 3=SET(발주단위 선택 단위) / 4=부품(리프).
TREEGRID_READ_JS = r"""(fields) => {
  try {
    const el = document.querySelector('.dews-ui-treegrid');
    if (!el) return { ok: false, reason: 'no-treegrid' };
    const g = window.jQuery(el).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const count = ds.getRowCount();
    const rows = [];
    for (let i = 0; i < count; i++) {
      let level = -1;
      try { level = ds.getLevel(i); } catch (e) {}
      const row = { i, level };
      for (const f of fields) {
        try { row[f] = g.getValue(i, f); } catch (e) { row[f] = null; }
      }
      rows.push(row);
    }
    return { ok: true, count, rows };
  } catch (e) { return { ok: false, err: String(e).slice(0, 150) }; }
}"""
