"""법인카드 승인내역 정리(card-collect) — 검증된 옴니솔 JS 프리미티브 단일소스.

probe_card/probe2~6 헤드리스 실측(2026-07-01)으로 확정한 셀렉터/조작만 담는다. 셀렉터가 바뀌면
여기 한 곳만 고친다. inert 상수(page.evaluate 인자로만 사용). ⚠ 저장(F7)은 steps 에서만 게이트.
"""

from __future__ import annotations

# 법인카드 거래내역 조회 팝업(k-window 제목=법인카드) 로케이터 식(다른 JS에 임베드).
CARD_WIN = (
    "[...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)"
    ".find(w=>/법인카드/.test(((w.querySelector('.k-window-title')||{}).innerText)||''))"
)

# ── 카드번호 전체선택(돋보기 → '카드' 서브팝업 → checkAll → 적용) ─────────────────
# 카드번호 멀티코드피커의 돋보기(icon-search) 버튼 중심좌표.
CARD_SEARCH_BTN_JS = f"""() => {{
  const win = {CARD_WIN}; if (!win) return null;
  const btn = [...win.querySelectorAll('.dews-multicodepicker-button')].filter(b => b.offsetParent!==null)
    .find(b => b.querySelector('.icon-search'));
  if (!btn) return null; const r = btn.getBoundingClientRect();
  return {{ x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2) }};
}}"""

# '카드' 서브팝업(법인카드 아님, 최근 열린 k-window) 그리드 전체체크. 반환 {ok,n}.
CARD_SUB_SELECT_ALL_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const sub = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];
  if (!sub) return { ok:false, reason:'no-sub' };
  try { const g = window.jQuery(sub.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const n = g.getDataSource().getRowCount(); if (n>0) g.checkAll(true);
    let checked=-1; try { checked=(g.getCheckedRows()||[]).length; } catch(e){}
    return { ok:true, n, checked };
  } catch(e) { return { ok:false, err:String(e).slice(0,60) }; }
}"""

# '카드' 서브팝업의 '적용' 버튼 중심좌표.
CARD_SUB_APPLY_BTN_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const sub = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];
  if (!sub) return null;
  const b = [...sub.querySelectorAll('button')].filter(x=>x.offsetParent!==null).find(x=>/적용/.test(c(x.innerText)));
  if (!b) return null; const r = b.getBoundingClientRect();
  return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2), text:c(b.innerText) };
}"""

# ── 승인일(dews-periodpicker) ─────────────────────────────────────────────────
# 인자 [start,end] (YYYY-MM-DD). value 직접 세팅 + input/change/blur.
PERIOD_SET_JS = """([start, end]) => {
  const setVal = (id, v) => { const el = document.getElementById(id); if (!el) return null;
    const d = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value'); d.set.call(el, v);
    ['input','change','blur'].forEach(t => el.dispatchEvent(new Event(t, { bubbles:true }))); return el.value; };
  return { start: setVal('period_startinput', start), end: setVal('period_endinput', end) };
}"""

# ── 조회 ──────────────────────────────────────────────────────────────────────
QUERY_BTN_JS = f"""() => {{
  const win = {CARD_WIN}; if (!win) return null;
  const b = [...win.querySelectorAll('button')].find(x => (x.innerText||'').trim() === '조회');
  if (!b) return null; const r = b.getBoundingClientRect();
  return {{ x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2) }};
}}"""

# 거래내역 그리드 행 수.
ROWCOUNT_JS = f"""() => {{
  const win = {CARD_WIN}; if (!win) return -1;
  try {{ const g = window.jQuery(win.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    return g.getDataSource().getRowCount(); }} catch(e) {{ return -1; }}
}}"""

# 거래내역 행 읽기(인자 limit). 날짜는 YYYY-MM-DD 문자열화(datetime 직렬화 회피).
READ_ROWS_JS = f"""(limit) => {{
  const win = {CARD_WIN}; if (!win) return {{ rows:-1, reason:'no-win' }};
  try {{
    const g = window.jQuery(win.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const n = g.getDataSource().getRowCount();
    const v = (i,f) => {{ try {{ const x=g.getValue(i,f); if(x==null) return null;
      if (x instanceof Date) return x.toISOString().slice(0,10); return String(x); }} catch(e) {{ return null; }} }};
    const out = [];
    for (let i=0; i<Math.min(n, limit||n); i++) out.push({{
      i, TRAN_DT:v(i,'TRAN_DT'), TRAN_NM:v(i,'TRAN_NM'), TRAN_AMT:v(i,'TRAN_AMT'),
      FINPRODUCT_NM:v(i,'FINPRODUCT_NM'), NOTE_DC:v(i,'NOTE_DC') }});
    return {{ rows:n, list: out }};
  }} catch(e) {{ return {{ rows:-1, err:String(e).slice(0,80) }}; }}
}}"""

# ── 적요(행별 인라인) ───────────────────────────────────────────────────────────
# 인자 [rowIndex, text]. 그리드 NOTE_DC 셀에 setValue. 반환 {ok, after}.
NOTE_SET_JS = f"""([row, text]) => {{
  const win = {CARD_WIN}; if (!win) return {{ ok:false, reason:'no-win' }};
  try {{ const g = window.jQuery(win.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    g.setValue(row, 'NOTE_DC', text);
    return {{ ok:true, after:String(g.getValue(row, 'NOTE_DC')) }};
  }} catch(e) {{ return {{ ok:false, err:String(e).slice(0,60) }}; }}
}}"""

# 그리드 특정 행만 체크(일괄적용 대상 = 그 행 1건). 인자 rowIndex. 반환 {ok, checked}.
CHECK_ONLY_ROW_JS = f"""(row) => {{
  const win = {CARD_WIN}; if (!win) return {{ ok:false, reason:'no-win' }};
  try {{ const g = window.jQuery(win.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    try {{ g.checkAll(false); }} catch(e) {{}}
    g.setChecked ? g.setChecked(row, true) : g.checkRow && g.checkRow(row, true);
    g.setCurrent && g.setCurrent({{ itemIndex: row, fieldName: 'NOTE_DC' }});
    let checked=-1; try {{ checked=(g.getCheckedRows()||[]).length; }} catch(e) {{}}
    return {{ ok:true, checked }};
  }} catch(e) {{ return {{ ok:false, err:String(e).slice(0,60) }}; }}
}}"""

# ── 코드피커(예산단위 bg_cd / 계정 acct_cd / 프로젝트 pjt_cd) ─────────────────────
# 버튼 좌표(인자 field id). 반환 {x,y} | null.
def picker_btn_js(field_id: str) -> str:
    return f"""() => {{
      const win = {CARD_WIN}; if (!win) return null;
      const wr = win.querySelector('#{field_id}-wrapper'); if (!wr) return null;
      const b = wr.querySelector('.dews-codepicker-button'); if (!b) return null;
      const r = b.getBoundingClientRect();
      return {{ x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2) }};
    }}"""

# 코드피커 팝업(최근 열린 non-법인카드 k-window) keyword 검색 세팅. 인자 q.
PICKER_SEARCH_JS = """(q) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const p = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];
  if (!p) return { ok:false, reason:'no-pop' };
  const kw = p.querySelector('#keyword') || [...p.querySelectorAll('input')].filter(i=>i.offsetParent!==null).pop();
  if (!kw) return { ok:false, reason:'no-keyword' };
  const d = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value'); d.set.call(kw, q);
  ['input','change'].forEach(t => kw.dispatchEvent(new Event(t, { bubbles:true })));
  return { ok:true };
}"""

# 코드피커 팝업 옵션 읽기(인자 [codeField,nameField,limit]). 반환 {rows, options:[{code,name}]}.
PICKER_READ_JS = """([codeField, nameField, limit]) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const p = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];
  if (!p) return { rows:-1, reason:'no-pop' };
  try { const g = window.jQuery(p.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const n = g.getDataSource().getRowCount(); const out = [];
    for (let i=0; i<Math.min(n, limit||n); i++) out.push({
      i, code: String(g.getValue(i, codeField)), name: String(g.getValue(i, nameField)) });
    return { rows:n, options: out };
  } catch(e) { return { rows:-1, err:String(e).slice(0,60) }; }
}"""

# 코드피커 팝업 행 선택(인자 rowIndex). setCurrent + setSelection.
PICKER_SELECT_JS = """(row) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const p = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];
  if (!p) return { ok:false, reason:'no-pop' };
  try { const g = window.jQuery(p.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    g.setCurrent({ itemIndex: row, fieldName: g.getColumns()[1].fieldName });
    g.setSelection({ startRow: row, endRow: row, startColumn: 0, endColumn: 0 });
    return { ok:true };
  } catch(e) { return { ok:false, err:String(e).slice(0,60) }; }
}"""

# 코드피커 팝업 '적용/확인' 버튼 좌표.
PICKER_APPLY_BTN_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const p = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];
  if (!p) return null;
  const b = [...p.querySelectorAll('button')].filter(x=>x.offsetParent!==null).find(x=>/적용|확인|선택/.test(c(x.innerText)));
  if (!b) return null; const r = b.getBoundingClientRect();
  return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2), text:c(b.innerText) };
}"""

# ── 일괄적용 / 저장(F7) 버튼(법인카드 팝업) ───────────────────────────────────────
# ⚠ 저장은 steps 에서 SAVE 게이트가 열렸을 때만 클릭한다.
def card_button_box_js(text: str) -> str:
    return f"""() => {{
      const win = {CARD_WIN}; if (!win) return null;
      const b = [...win.querySelectorAll('button')].filter(x=>x.offsetParent!==null)
        .find(x => (x.innerText||'').trim() === {text!r});
      if (!b) return null; const r = b.getBoundingClientRect();
      return {{ x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2) }};
    }}"""
