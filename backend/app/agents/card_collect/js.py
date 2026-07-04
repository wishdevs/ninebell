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
    // 부가세구분(VAT_TP)은 원시값이 코드('1')라 화면 라벨('과세' 등)로 읽는다(display value).
    const dv = (i,f) => {{ try {{ const o = g.getDisplayValuesOfRow(i);
      return o && o[f] != null ? String(o[f]) : v(i,f); }} catch(e) {{ return v(i,f); }} }};
    const out = [];
    // 거래시각(TRAN_TM '00:00:00')·승인여부(APRVL_YN '승인'/'승인취소')는 display value 로 읽는다.
    // APRVL_NO(승인번호)는 2패스(불공) 재조회 행 매칭 키 — 승인/취소 쌍이 같은 번호라 단독으론
    // 유니크하지 않다(프로브 실측). 매칭은 (APRVL_NO, TRAN_DT, TRAN_AMT) 복합키로 한다.
    for (let i=0; i<Math.min(n, limit||n); i++) out.push({{
      i, TRAN_DT:v(i,'TRAN_DT'), TRAN_TM:dv(i,'TRAN_TM'), TRAN_NM:v(i,'TRAN_NM'),
      TRAN_AMT:v(i,'TRAN_AMT'), SPPRC_AMT:v(i,'SPPRC_AMT'), VAT_AMT:v(i,'VAT_AMT'),
      VAT_TP:dv(i,'VAT_TP'), APRVL_YN:dv(i,'APRVL_YN'), APRVL_NO:v(i,'APRVL_NO'),
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
  // 팝업별 검색창 id 상이: 예산단위/계정=#keyword, 프로젝트=#s_search_key. 알려진 id 우선,
  // 없으면 search_key/keyword 접미·접두 → 마지막으로 첫 보이는 text input.
  const kw = p.querySelector('#keyword') || p.querySelector('#s_search_key')
    || p.querySelector('[id$=search_key]') || p.querySelector('[id*=keyword]')
    || [...p.querySelectorAll('input')].filter(i=>i.offsetParent!==null && (i.type==='text'||!i.type))[0];
  if (!kw) return { ok:false, reason:'no-keyword' };
  const d = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value'); d.set.call(kw, q);
  ['input','change'].forEach(t => kw.dispatchEvent(new Event(t, { bubbles:true })));
  return { ok:true, field: kw.id || '(no-id)' };
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

# 코드피커 팝업 다중필드 전량 읽기(인자 [fields, limit]). limit 0/null = 전량.
# getJsonRows(0, n-1) 로 로드분 전량을 읽는다(예산단위 2천여행/프로젝트 500행 캡). 반환
# {rows, options:[{i, <field>: str|null,...}]}. '법인카드' 창 제외 필터는 PICKER_READ_JS 와 동일.
PICKER_READ_MULTI_JS = """([fields, limit]) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const p = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];
  if (!p) return { rows:-1, reason:'no-pop' };
  try { const g = window.jQuery(p.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const rows = ds.getJsonRows(0, n-1);
    const cap = limit || rows.length;
    const out = rows.slice(0, Math.min(rows.length, cap)).map((r,i)=>{
      const o = { i }; for (const f of fields) o[f] = r[f]==null?null:String(r[f]); return o; });
    return { rows:n, options: out };
  } catch(e) { return { rows:-1, err:String(e).slice(0,80) }; }
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

# 코드피커 팝업 닫기(실패 경로에서 열린 채 남으면 다음 코드피커가 이 팝업을 읽어 오작동).
PICKER_CLOSE_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const p = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];
  if (!p) return false;
  const x = p.querySelector('.k-i-close, .k-window-action, [aria-label*=Close], [title*=닫기]');
  if (x) { x.click(); return true; }
  const b = [...p.querySelectorAll('button')].filter(e=>e.offsetParent!==null)
    .find(e => /닫기|취소|close/i.test(c(e.innerText)));
  if (b) { b.click(); return true; }
  return false;
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

# 일괄적용 후 뜨는 '예산현황' 확인창(제목=예산현황, grid 없음, 버튼 확인/취소)의 '확인' 클릭.
# 일괄적용 시 예산 가용성 체크 모달이 뜨며, 확인해야 draft(메모리) 반영이 완료된다.
# ⚠ draft 반영 완료일 뿐 F7 저장 아님. 미처리 시 이 창이 남아, 다음 행 코드피커의
# 'last non-법인카드 window' 셀렉터가 이 창을 읽어 검색결과 0건이 된다. 반환 {n, clicked}.
BUDGET_CONFIRM_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const w = [...document.querySelectorAll('.k-window')].filter(x => x.offsetParent!==null)
    .filter(x => !/법인카드/.test(c((x.querySelector('.k-window-title')||{}).innerText)) && !x.querySelector('.dews-ui-grid'))
    .slice(-1)[0];
  if (!w) return { n:0 };
  const b = [...w.querySelectorAll('button')].filter(x => x.offsetParent!==null).find(x => /확인|예|OK/i.test(c(x.innerText)));
  if (!b) return { n:1, clicked:null };
  b.click(); return { n:1, clicked:c(b.innerText) };
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


# 문서 전역에서 정확 텍스트 버튼 좌표(저장은 카드팝업이 아닌 결의서 본화면에 있을 수 있음, 리뷰 #10).
def document_button_box_js(text: str) -> str:
    return f"""() => {{
      const b = [...document.querySelectorAll('button')].filter(x=>x.offsetParent!==null)
        .find(x => (x.innerText||'').trim() === {text!r});
      if (!b) return null; const r = b.getBoundingClientRect();
      return {{ x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2) }};
    }}"""


# 법인카드 카드 팝업 존재 여부(닫기 검증용).
CARD_WIN_EXISTS_JS = f"""() => !!({CARD_WIN})"""


# 코드피커 팝업 그리드의 중심 좌표(휠 스크롤 로딩용). 반환 {x,y} | null.
PICKER_GRID_RECT_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const p = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];
  if (!p) return null;
  const g = p.querySelector('.dews-ui-grid'); if (!g) return null;
  const r = g.getBoundingClientRect();
  return { x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2) };
}"""

# 코드피커 팝업 그리드 행 수(스크롤 로딩 진행 판정).
PICKER_ROWCOUNT_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const p = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];
  if (!p) return -1;
  try { const g = window.jQuery(p.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    return g.getDataSource().getRowCount(); } catch(e) { return -2; }
}"""


# 코드피커 팝업 그리드 마지막 행 setCurrent + 포커스 — ArrowDown 으로 다음 페이지 로드 트리거.
# (프로브 2026-07-02: 휠은 1,318행 정체, setCurrent(끝행)+ArrowDown 은 라운드당 +500 결정적.)
PICKER_FOCUS_LAST_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const p = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .filter(w=>!/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText))).slice(-1)[0];
  if (!p) return { ok:false, reason:'no-pop' };
  try { const gridEl = p.querySelector('.dews-ui-grid');
    const g = window.jQuery(gridEl).data('dewsControl')._grid;
    const n = g.getDataSource().getRowCount();
    const cols = g.getColumns();
    const f = (cols.find(x=>x.visible) || cols[1] || cols[0]).fieldName;
    g.setCurrent({ itemIndex: n-1, fieldName: f });
    const focusable = gridEl.querySelector('[tabindex], canvas, .k-grid-content') || gridEl;
    focusable.focus && focusable.focus();
    return { ok:true, row: n-1 };
  } catch(e) { return { ok:false, err: String(e).slice(0,100) }; }
}"""


# 여러 행 체크(카드팝업 '적용' 대상 지정). 인자 indices 배열. 반환 {ok, checked}.
CHECK_ROWS_JS = f"""(indices) => {{
  const win = {CARD_WIN}; if (!win) return {{ ok:false, reason:'no-win' }};
  try {{ const g = window.jQuery(win.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    try {{ g.checkAll(false); }} catch(e) {{}}
    for (const i of indices) {{
      g.setChecked ? g.setChecked(i, true) : g.checkRow && g.checkRow(i, true);
    }}
    let checked=-1; try {{ checked=(g.getCheckedRows()||[]).length; }} catch(e) {{}}
    return {{ ok:true, checked }};
  }} catch(e) {{ return {{ ok:false, err:String(e).slice(0,60) }}; }}
}}"""

# 최상단 보이는 k-window 모달들의 (제목/본문/버튼) 관찰 — 저장/적용 확인창 폴링용.
MODALS_SNAPSHOT_JS = """() => [...document.querySelectorAll('.k-window')]
  .filter(w => w.offsetParent !== null)
  .map(w => {
    const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
    return { title: c((w.querySelector('.k-window-title')||{}).innerText),
             text: c(w.innerText).slice(0, 160),
             buttons: [...w.querySelectorAll('button')].filter(b=>b.offsetParent!==null)
               .map(b=>c(b.innerText)).filter(Boolean) };
  })"""

# 보이는 k-window 중 버튼 텍스트가 정확히 일치하는 첫 버튼 좌표. 인자 btnText.
MODAL_BTN_BOX_JS = """(btnText) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null);
  for (const w of wins.reverse()) {  // 최근(위) 모달 우선
    const b = [...w.querySelectorAll('button')].filter(x=>x.offsetParent!==null)
      .find(x => c(x.innerText) === btnText);
    if (b) { const r = b.getBoundingClientRect();
      return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2),
               title: c((w.querySelector('.k-window-title')||{}).innerText) }; }
  }
  return null;
}"""


# 저장(F7) 실패를 알리는 dews 인라인 토스트/경고 텍스트 탐지(모달 아님 → MODALS_SNAPSHOT 로는
# 안 잡힌다). 실측(2026-07-03): 필수값 누락 시 하단에 '상세그리드에 필수 값이 입력되지 않은
# 항목이 있습니다' 토스트가 뜨는데 결의번호는 blank(미저장). 실패 문구를 담은 보이는 짧은
# 요소들의 텍스트를 반환한다. 반환 [] = 실패 신호 없음.
VALIDATION_TOAST_JS = r"""() => {
  const phrases = ['필수 값','필수값','입력되지 않은','입력되지않은','저장에 실패','저장 실패',
                   '실패했습니다','확인해 주세요','확인하세요','오류가 발생'];
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const out = new Set();
  for (const el of document.querySelectorAll('div,span,p,td,li')) {
    if (el.offsetParent === null) continue;
    const t = c(el.innerText);
    if (t && t.length < 120 && phrases.some(p => t.includes(p))) out.add(t);
  }
  return [...out];
}"""


# 마스터(결의서) 그리드 0행의 회계일(ACTG_DT) 설정 + 표시값 검증. 인자 ymd='YYYYMMDD'.
# ⚠ 'YYYY-MM-DD'(대시) 형식은 오류 없이 셀을 **비운다**(프로브 실측 2026-07-04) — 컴팩트만 사용.
SET_ACCT_DATE_JS = """(ymd) => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[0]).data('dewsControl')._grid;
    const ds = g.getDataSource();
    if (ds.getRowCount() < 1) return { ok: false, reason: '결의서(마스터) 행 없음' };
    ds.setValue(0, 'ACTG_DT', ymd);
    const disp = (g.getDisplayValuesOfRow ? g.getDisplayValuesOfRow(0) : {}) || {};
    return { ok: true, display: String(disp.ACTG_DT || '') };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 120) }; }
}"""
