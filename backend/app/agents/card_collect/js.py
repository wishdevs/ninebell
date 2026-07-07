"""법인카드 승인내역 정리(card-collect) — 검증된 옴니솔 JS 프리미티브 단일소스.

probe_card/probe2~6 헤드리스 실측(2026-07-01)으로 확정한 셀렉터/조작만 담는다. 셀렉터가 바뀌면
여기 한 곳만 고친다. inert 상수(page.evaluate 인자로만 사용). ⚠ 저장(F7)은 steps 에서만 게이트.
"""

from __future__ import annotations

# 코드피커/모달 공용 JS 는 nbkit 로 승격(2026-07-05). CARD_WIN(법인카드 팝업 로케이터)은
# picker_btn_js 가 쓰므로 함께 승격 — 아래 CARD_* f-string 들도 이 재수출본을 임베드한다.
from nbkit.omnisol.js_lib import (  # noqa: F401 — 하위호환 재수출(단일소스는 js_lib)
    CARD_WIN,
    MODAL_BTN_BOX_JS,
    MODALS_SNAPSHOT_JS,
    PICKER_APPLY_BTN_JS,
    PICKER_CLOSE_JS,
    PICKER_FOCUS_LAST_JS,
    PICKER_GRID_RECT_JS,
    PICKER_READ_JS,
    PICKER_READ_MULTI_JS,
    PICKER_ROWCOUNT_JS,
    PICKER_SEARCH_JS,
    PICKER_SELECT_JS,
    SET_ACCT_DATE_JS,
    VALIDATION_TOAST_JS,
    picker_btn_js,
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
# picker_btn_js·PICKER_* 공용 JS 는 nbkit.omnisol.js_lib 로 승격 — 상단 재수출 참조.

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


# PICKER_GRID_RECT_JS/PICKER_ROWCOUNT_JS/PICKER_FOCUS_LAST_JS 는 js_lib 로 승격 — 상단 재수출 참조.


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

# MODALS_SNAPSHOT_JS/MODAL_BTN_BOX_JS/VALIDATION_TOAST_JS 는 js_lib 로 승격 — 상단 재수출 참조.


# SET_ACCT_DATE_JS 는 js_lib 로 승격(2026-07-06, 출장 공용) — 상단 재수출 참조.


# '카드' 서브팝업에서 소유자(CARD_OWNR_NM) 또는 관리사원(KOR_NM)이 owner 와 정규화 일치하는
# 행만 체크(본인 카드 우선 선택, 사용자 요청 2026-07-04). 반환 {ok, n(전체), matched(체크수)}.
# matched==0 이면 호출부가 기존 전체선택으로 폴백한다(빈 소유자/공용카드 대비).
CARD_SUB_SELECT_BY_NAME_JS = """(owner) => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,'').toLowerCase();
  const key = c(owner);
  const sub = [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .filter(w=>!/법인카드/.test(String((w.querySelector('.k-window-title')||{}).innerText||'').replace(/\\s+/g,' ').trim())).slice(-1)[0];
  if (!sub) return { ok:false, reason:'no-sub' };
  try {
    const g = window.jQuery(sub.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    if (n <= 0) return { ok:true, n:0, matched:0 };
    const rows = ds.getJsonRows(0, n-1);
    try { g.checkAll(false); } catch(e) {}
    let matched = 0;
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i] || {};
      if (key && (c(r.CARD_OWNR_NM) === key || c(r.KOR_NM) === key)) {
        g.setChecked ? g.setChecked(i, true) : g.checkRow && g.checkRow(i, true);
        matched++;
      }
    }
    let checked=-1; try { checked=(g.getCheckedRows()||[]).length; } catch(e){}
    return { ok:true, n, matched, checked };
  } catch(e) { return { ok:false, err:String(e).slice(0,60) }; }
}"""


# '카드' 서브팝업(법인카드가 아닌 k-window)이 열려 있는지 — 적용 후 닫힘 폴링용.
CARD_SUB_EXISTS_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  return [...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)
    .some(w => !/법인카드/.test(c((w.querySelector('.k-window-title')||{}).innerText)) &&
               /카드/.test(c((w.querySelector('.k-window-title')||{}).innerText)));
}"""
