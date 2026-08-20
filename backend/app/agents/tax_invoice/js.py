"""세금계산서 고유 in-page JS — 프로브 검증분 승격(단일 소스).

`e2e/tax_invoice_write_probe.py`(2026-08-19 완전 사이클 PASS)·`e2e/tax_invoice_split_probe.py`
에서 검증된 JS 를 프로덕션으로 승격했다. 공용 프리미티브(피커·모달·그리드 리더)는
`nbkit.omnisol.js_lib` 를 그대로 쓴다 — 여기는 세금계산서 고유(분할처리 팝업·전자세금계산서
팝업·메인 detail 행 인덱스 지정)만 둔다.

⚠ split_probe 의 `DISTRIBUTION_GRID_DUMP_JS` 는 버그(wrapper 를 dewsControl 로 가정)라
  승격하지 않는다 — 분할 그리드 접근은 전부 '분할처리' 타이틀 팝업 스코프의 `.dews-ui-grid`
  자손으로 잡는다(쓰기 프로브 실측 수정분).
"""

from __future__ import annotations

# 보이는 버튼을 텍스트 완전일치로 찾는다(비용분할/추가/삭제/차액반영/적용 — split_probe 검증).
BUTTON_BY_TEXT_JS = """(text) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  return [...document.querySelectorAll('button')]
    .filter(b => b.offsetParent !== null && c(b.innerText) === text)
    .map(b => { const r = b.getBoundingClientRect();
      return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2),
        id: b.id || null, cls: (b.className||'').toString().slice(0,90),
        disabled: !!b.disabled, text: c(b.innerText) }; });
}"""

# 최상단 k-window 팝업의 제목·입력·그리드(컬럼+행) 범용 덤프(split_probe 검증).
INVOICE_POPUP_DUMP_JS = """(limit) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const dlg = wins[wins.length - 1];
  if (!dlg) return { ok: false, reason: 'no-popup' };
  const title = c((dlg.querySelector('.k-window-title')||{}).innerText);
  const inputs = [...dlg.querySelectorAll('input')].filter(i => i.offsetParent !== null).map(i => ({
    id: i.id || null, type: i.type || '', value: c(i.value).slice(0, 30) }));
  let grid = null;
  try {
    const g = window.jQuery(dlg.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const cols = (g.getColumns ? g.getColumns() : []).map(cc => ({
      field: cc.fieldName || cc.name || cc.field || null,
      header: (cc.header && (cc.header.text || cc.header.caption)) || cc.caption || cc.title || null,
      visible: cc.visible !== false }));
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const take = Math.min(n, limit || 50);
    const rows = take > 0 ? ds.getJsonRows(0, take - 1) : [];
    grid = { n, cols, rows };
  } catch (e) { grid = { err: String(e).slice(0, 140) }; }
  return { ok: true, title, inputs, grid };
}"""

# 보이는 k-window 팝업 제목 목록 — 특정 팝업(분할처리/전자세금계산서) 출현 폴링용.
VISIBLE_POPUP_TITLES_JS = """() => [...document.querySelectorAll('.k-window')]
  .filter(w => w.offsetParent !== null)
  .map(w => (w.querySelector('.k-window-title')||{}).innerText || '')"""

# 분할처리 팝업 그리드 셀 에디터 오픈 — 팝업을 '분할처리' 타이틀로 찾고 자손 grid 를 잡는다.
OPEN_DIST_CELL_EDITOR_JS = """({ rowIndex, fieldName }) => {
  try {
    const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
    const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
    const dlg = wins.find(w => /분할처리/.test(c((w.querySelector('.k-window-title')||{}).innerText||'')));
    if (!dlg) return { ok: false, reason: 'no-분할처리-popup' };
    const gridEl = dlg.querySelector('.dews-ui-grid');
    if (!gridEl) return { ok: false, reason: 'no-grid-el' };
    const g = window.jQuery(gridEl).data('dewsControl')._grid;
    const n = g.getDataSource().getRowCount();
    if (n < 1) return { ok: false, reason: 'no-rows' };
    const idx = (rowIndex == null) ? Math.max(0, n - 1) : rowIndex;
    if (idx < 0 || idx >= n) return { ok: false, reason: 'row-out-of-range(' + idx + '/' + n + ')' };
    g.setCurrent({ itemIndex: idx, fieldName });
    g.showEditor();
    return { ok: true, idx, rows: n };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 150) }; }
}"""

# 분할처리 팝업 코드피커 셀의 돋보기 오버레이(텍스트/피커 공용 `_grid_line` 재사용 관례).
DIST_EDITOR_MAGNIFIER_JS = """() => {
  const inp = document.getElementById('GLDDOC00300_DISTRIBUTION_grid_line');
  if (!inp || inp.offsetParent === null) return null;
  const r = inp.getBoundingClientRect();
  return { x: Math.round(r.right + 8), y: Math.round(r.top + r.height / 2), id: inp.id };
}"""

# 분할처리 팝업 rowIndex 행의 체크박스 열 좌표(좌측 끝 x+15 — 행 삭제 전 체크용, 녹화 관례).
DIST_ROW_CHECKBOX_RECT_JS = """(rowIndex) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const dlg = wins.find(w => /분할처리/.test(c((w.querySelector('.k-window-title')||{}).innerText||'')));
  if (!dlg) return null;
  const gridEl = dlg.querySelector('.dews-ui-grid');
  if (!gridEl) return null;
  const gr = gridEl.getBoundingClientRect();
  return { x: Math.round(gr.x + 15), y: Math.round(gr.y + 30 + rowIndex * 32 + 16) };
}"""

# 분할처리 팝업 그리드 행수 — '추가' 성공 판정(행수 증가)의 전용 리더.
DIST_ROWCOUNT_JS = """() => {
  try {
    const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
    const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
    const dlg = wins.find(w => /분할처리/.test(c((w.querySelector('.k-window-title')||{}).innerText||'')));
    if (!dlg) return -2;
    const gridEl = dlg.querySelector('.dews-ui-grid');
    if (!gridEl) return -3;
    return window.jQuery(gridEl).data('dewsControl')._grid.getDataSource().getRowCount();
  } catch (e) { return -1; }
}"""

# 분할처리 팝업 rowIndex 행의 일반 셀 좌표(x+150) — 차액반영 전 대상 행 **실클릭** 선택용
# (합성 이벤트로는 트리거 미발화 — 실클릭만 인식, 쓰기 프로브 attempt⑤ 검증).
DIST_ROW_RECT_JS = """(rowIndex) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const dlg = wins.find(w => /분할처리/.test(c((w.querySelector('.k-window-title')||{}).innerText||'')));
  if (!dlg) return null;
  const gridEl = dlg.querySelector('.dews-ui-grid');
  if (!gridEl) return null;
  const gr = gridEl.getBoundingClientRect();
  return { x: Math.round(gr.x + 150), y: Math.round(gr.y + 30 + rowIndex * 32 + 16) };
}"""

# 지정한 창(팝업/모달) **안에서** 라벨 정확일치 버튼을 찾아 **요소 클릭**한다.
# ⚠ 좌표 클릭 금지 지점 전용 — 전역 좌표 클릭은 창이 겹치면 **본창(결의서입력) 버튼**을 때린다.
#   실측(2026-08-19): 사용자 헤디드 관찰 "본창의 조회와 모달창의 조회가 따로 있는데 본창을
#   누르고 있다" + A/B 진단(게이트 '선택' 창 잔존, 좌표 클릭이 팝업 조회를 실행하지 못함).
#   창은 제목(titleHints) 또는 본문 문구(textHint)로 지정하고, 최상단부터 역순 탐색한다.
CLICK_WINDOW_BUTTON_JS = """({ titleHints, textHint, label }) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const titles = wins.map(w => c((w.querySelector('.k-window-title')||{}).innerText));
  let idx = -1;
  for (let i = wins.length - 1; i >= 0; i--) {
    const byTitle = (titleHints || []).some(h => titles[i].indexOf(h) >= 0);
    const byText = textHint ? c(wins[i].innerText).indexOf(textHint) >= 0 : false;
    if (byTitle || byText) { idx = i; break; }
  }
  if (idx < 0) return { ok: false, reason: 'no-window', titles };
  const dlg = wins[idx];
  const buttons = [...dlg.querySelectorAll('button')].filter(b => b.offsetParent !== null);
  const labels = buttons.map(b => c(b.innerText)).filter(Boolean);
  const target = buttons.find(b => c(b.innerText) === label);
  if (!target) return { ok: false, reason: 'no-button', titles, buttons: labels };
  target.click();
  return { ok: true, title: titles[idx], label, buttons: labels };
}"""

# 전자세금계산서 팝업 조회기간 세팅 — decoy 없는 DOM input(native setter + input/change 발화,
# split_probe 실측 검증). 날짜는 'YYYY-MM-DD'.
SET_INVOICE_PERIOD_JS = """({ from, to }) => {
  const set = (id, val) => { const i = document.getElementById(id); if (!i) return false;
    const d = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
    d.set.call(i, val); i.dispatchEvent(new Event('input', {bubbles:true}));
    i.dispatchEvent(new Event('change', {bubbles:true})); return true; };
  return { start: set('period_startinput', from), end: set('period_endinput', to) };
}"""

# **제목으로 지정한** 팝업의 상태 덤프(제목·입력·버튼 좌표·그리드) — 전자세금계산서 팝업 전용.
# ⚠ 종전에는 '마지막 보이는 k-window = 대상 팝업'으로 가정했는데, 실런(2026-08-19 b4eb0ea3)에서
#   팝업은 열려 있었지만(제목 탐색·기간 input 은 찾힘) 다른 창이 그 뒤에 있어 조회 버튼 탐색이
#   0건이 됐다. 분할처리 팝업 JS 들과 같은 '제목 스코프' 패턴으로 통일한다. 안 찾히면 보이는
#   창 제목 전량을 실어 돌려준다(다음 실런이 스스로 원인을 말하게).
POPUP_BY_TITLE_STATE_JS = """({ hints, limit }) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const titles = wins.map(w => c((w.querySelector('.k-window-title')||{}).innerText));
  const hs = hints || [];
  let idx = -1;
  for (let i = wins.length - 1; i >= 0; i--) {  // 최상단부터 제목 일치 탐색.
    if (hs.some(h => titles[i].indexOf(h) >= 0)) { idx = i; break; }
  }
  if (idx < 0) return { ok: false, reason: 'no-popup', titles };
  const dlg = wins[idx];
  const inputs = [...dlg.querySelectorAll('input')].filter(i => i.offsetParent !== null).map(i => ({
    id: i.id || null, value: c(i.value).slice(0, 30) }));
  const buttons = [...dlg.querySelectorAll('button')].filter(b => b.offsetParent !== null)
    .map(b => { const r = b.getBoundingClientRect();
      return { text: c(b.innerText), x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2) }; })
    .filter(b => b.text);
  // ⚠ 그리드는 **전량 열거**한다(첫 그리드 가정 금지) — 조건영역 등 빈 그리드가 앞에 있으면
  //   첫 그리드만 읽던 코드는 영원히 0행을 본다(진단 스크립트 POPUP_FULL_DIAG_JS 승격).
  const gridEls = [...dlg.querySelectorAll('.dews-ui-grid')];
  const cap = (limit === 0) ? 0 : (limit || 50);  // limit:0 = 행수만(로딩 폴링용 경량 읽기).
  const grids = gridEls.map((el, gi) => {
    try {
      const g = window.jQuery(el).data('dewsControl')._grid;
      const ds = g.getDataSource();
      const n = ds.getRowCount();
      const take = Math.min(n, cap);
      return { gridIndex: gi, elId: el.id || null, n,
        rows: take > 0 ? ds.getJsonRows(0, take - 1) : [] };
    } catch (e) { return { gridIndex: gi, elId: el.id || null, err: String(e).slice(0, 140) }; }
  });
  return { ok: true, title: titles[idx], topmost: idx === wins.length - 1, titles,
    windowCount: wins.length, inputs, buttons, gridCount: gridEls.length, grids };
}"""

# '진행 상황' 프로그레스(분할 적용 비동기 커밋) 표시 여부 — 사라질 때까지 대기용(쓰기 프로브
# 최종라운드: 커밋 미완 상태의 F7 은 팬텀 저장이 된다).
PROGRESS_VISIBLE_JS = """() => [...document.querySelectorAll('*')].some(e => e.offsetParent!==null
  && /진행\\s*상황/.test((e.innerText||'').slice(0,20)))"""

# 화면 제목('결의서입력') 중립 영역 좌표 — 분할 적용 후 포커스 리셋 클릭용(쓰기 프로브 이식).
NEUTRAL_HEADER_BOX_JS = """() => { const h = [...document.querySelectorAll('*')].find(e => e.offsetParent!==null
  && (e.innerText||'').trim()==='결의서입력'); if(!h) return null;
  const r = h.getBoundingClientRect(); return {x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2)}; }"""
