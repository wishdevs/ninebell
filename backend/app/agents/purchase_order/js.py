"""구매발주(purchase-order) 화면 ① PUOPRQ00200 전용 JS — 읽기/조회조건 확정 단일 소스.

`e2e/purchase_order_{project_apply,checkbox_filter,bom_grid}_probe.py`(2026-08-13 라이브
읽기 프로브, 부작용 0)에서 검증된 JS 를 그대로 승격했다. 전부 읽기 또는 조회조건 확정
(프로젝트 선택·체크박스·조회 버튼 좌표)용이며 **저장·결재·행 데이터 변경 JS 는 없다**.

프로젝트 도움창은 js_lib 의 WBS 스키마 피커(PROJECT_READ_JS 등)와 필드가 다르다
(PJT_NO/PJT_NM — WBS_NO 아님, 검색 입력 #keyword — #s_search_key 아님). 그래서 이 화면
전용 JS 를 여기 두고, 피커 버튼 좌표만 js_lib.PROJECT_PICKER_BOX_JS 를 재사용한다.
"""

from __future__ import annotations

# 프로젝트 도움창 **특정** 상태 — 임의의 visible .k-window 존재 판정(구 WIN_STATE_JS)으로는
# 창 셸 출현(클릭 후 79~187ms)과 입력 준비(#keyword 접근 가능 345~449ms — 자동 사전검색
# AJAX 완료 후)를 구분하지 못해 미준비 팝업에 검색어 주입을 시도하다 시도를 낭비한다
# (2026-08-14 라이브 프로브 실측). present = #keyword 를 품은 visible k-window 존재,
# gridReady = 그 창의 결과 그리드 dewsControl 초기화 완료(= 검색 제출을 받을 준비).
POPUP_STATE_JS = r"""() => {
  const kw = document.querySelector('#keyword');
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const dlg = kw ? wins.find(w => w.contains(kw)) : null;
  let gridReady = false;
  if (dlg) {
    try {
      const el = dlg.querySelector('.dews-ui-grid');
      gridReady = !!(el && window.jQuery(el).data('dewsControl')._grid);
    } catch (e) {}
  }
  return { present: !!dlg, gridReady };
}"""

# 프로젝트 도움창 검색어 입력(#keyword — 네이티브 setter + input 이벤트). arg = q.
# ⛔ **검색에 쓰지 말 것**(2026-08-14 매트릭스 프로브 2/2 재현): 이 세터로 값을 넣으면
#   제출 방식과 무관하게(jQuery trigger·네이티브 KeyboardEvent 둘 다) 팝업이 소멸한다.
#   실타이핑(steps._type_keyword)은 두 제출 방식 모두에서 생존한다 — 갈림길은 제출이
#   아니라 **주입**이다. 이 상수는 다른 폼 입력 참고용으로만 남긴다.
SET_KEYWORD_JS = r"""(q) => {
  const i = document.querySelector('#keyword');
  if (!i) return false;
  const s = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(i), 'value').set;
  s.call(i, q); i.dispatchEvent(new Event('input', { bubbles: true })); i.focus();
  return true;
}"""

# 도움창 검색 제출 — ⚠ trusted Enter(page.keyboard.press) 금지: 이 팝업의 #keyword 는
# action/method/onsubmit 없는 <form> 안이라 trusted Enter 가 네이티브 폼 제출을 유발하고,
# SPA 가 이를 앱 소프트리셋(MainContainer 재마운트)으로 처리해 팝업 포함 화면 상태가 통째로
# **영구** 소멸한다(2026-08-14 라이브 프로브 4/4 재현 — 대기시간·그리드 준비 여부와 무관).
# untrusted 디스패치는 네이티브 기본동작(폼 제출)을 유발하지 않으므로 검색 핸들러만 탄다.
# jQuery.Event trigger 채택(DEWS/Kendo 는 jQuery 델리게이트 핸들러) — 라이브 검증 2026-08-14:
# 리셋 마커 0건, 그리드 갱신 164ms, 검색→선택→적용→F2→BOM 로드 전 경로 PASS. 네이티브
# untrusted KeyboardEvent 후보도 기능은 동작했으나 검증 중 리셋 마커 1건이 관측돼 배제.
SUBMIT_KEYWORD_JS = r"""() => {
  const i = document.querySelector('#keyword');
  if (!i || !window.jQuery) return false;
  const $ = window.jQuery;
  $(i).trigger($.Event('keydown', { keyCode: 13, which: 13 }));
  $(i).trigger($.Event('keypress', { keyCode: 13, which: 13 }));
  return true;
}"""

# #keyword 현재 값 — 실타이핑 교체가 반영됐는지 검증.
KEYWORD_VALUE_JS = r"""() => (document.querySelector('#keyword') || {}).value || ''"""

# #keyword 중심 좌표 — 실타이핑 폴백(트리플클릭 전체선택) 대상.
KEYWORD_BOX_JS = r"""() => {
  const i = document.querySelector('#keyword');
  if (!i || i.offsetParent === null) return null;
  const r = i.getBoundingClientRect();
  return { x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2) };
}"""

# ── 상단 고정 필드(D3) — 구매그룹·구매조직·구매사유 ──────────────────────────
# 코드피커는 **코드(hidden #id) + 표시(#id_text)** 쌍이다(프로브 실측 2026-08-14:
# i_purgrp_cd=1000 / i_purgrp_cd_text=나인벨). 구매사유(i_rmk_dc)는 평범한 텍스트박스.
# arg [codeIds, reasonId] → {fields: {id: {code, text}}, reason}.
HEADER_STATE_JS = r"""([codeIds, reasonId]) => {
  const val = el => (el ? el.value : null);
  const fields = {};
  for (const id of codeIds) {
    fields[id] = {
      code: val(document.querySelector('#' + id)),
      text: val(document.querySelector('#' + id + '_text')),
    };
  }
  return { fields, reason: val(document.querySelector('#' + reasonId)) };
}"""

# 폼 입력 강제 세팅(네이티브 setter + input/change + blur). arg [id, value] → {ok, after}.
# ⚠ 코드피커는 **코드만 넣으면 표시가 해석되지 않는다**(프로브 실측) — 호출부가 코드와
#   표시(#id_text)를 함께 세팅해야 한다. 그리드 setValue 금지 규율과 무관(폼 입력).
SET_INPUT_JS = r"""([id, value]) => {
  const el = document.querySelector('#' + id);
  if (!el) return { ok: false, reason: 'no-field' };
  const d = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
  d.set.call(el, value);
  for (const t of ['input', 'change']) el.dispatchEvent(new Event(t, { bubbles: true }));
  el.dispatchEvent(new FocusEvent('blur', { bubbles: true }));
  return { ok: true, after: el.value };
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
    let mvY = 0, mvN = 0, leafN = 0;
    // ds 인덱스 공간: 0=숨은 루트, 데이터 행은 1..count(경계 프로브 실측 — TREEGRID_READ_JS 참조).
    for (let i = 1; i <= count; i++) {
      // ds.getValue — 레벨과 같은 인덱스 공간(grid 쪽 getValue 는 한 행 앞섬, TREEGRID_READ_JS 참조).
      // leafN = 리프(레벨 4) 중 MV_FG='N' — '이동요청만' 뷰 판정용. 구조행(레벨 1~3)은 이동요청만
      // 뷰에서도 MV_FG='N' 이라(2026-08-28 ETRI-001 실측: 163행 = Y 132 + 구조 N 31) 리프만 센다.
      try {
        const v = ds.getValue(i, 'MV_FG');
        if (v === 'Y') mvY++;
        else if (v === 'N') { mvN++; if (ds.getLevel(i) === 4) leafN++; }
      } catch (e) {}
    }
    return { count, mvY, mvN, leafN };
  } catch (e) { return null; }
}"""

# BOM 트리그리드 전량 읽기 — ⚠ getJsonRows(범위형)는 트리그리드에서 null(플랫 전용 API, 실측).
# ⚠⚠ 인덱스 공간(2026-08-13 levelmap 프로브 실측): 트리그리드에서 `grid.getValue(i, f)` 는
#   `ds.getLevel(i)` 보다 **한 행 앞선 데이터**를 돌려준다(모듈이 첫 부품으로 밀리는 시프트의
#   원인). 레벨과 같은 인덱스 공간은 **ds.getValue(i, f)**(= ds.getJsonRow(i)) — 반드시 ds 로
#   읽는다. 지정 필드만 읽어 페이로드를 제한한다. arg = fields(string[]).
# 레벨(0-idx, ds 정합 실측): 0=루트 / 1=프로젝트(라벨 행) / 2=장비 / 3=SET(발주단위 선택 단위)
# / 4=부품(리프). — 이전 '0=프로젝트/1=장비/2=구조행' 매핑은 시프트된 g.getValue 로 만든 오독.
# ⚠ 루프 경계(2026-08-13 경계 프로브 실측): ds 인덱스 0 은 **숨은 루트**(필드 undefined)이고
#   데이터 행은 1..count 다 — ds.getLevel(count)==4, ds.getValue(count,'ITEM_CD') 가 마지막
#   부품(CX85-137 에선 'CM0SP-ZRVB-M002-0' BUFFER Z-ROBOT R)을 돌려준다. 0..count-1 로 돌면
#   마지막 부품 1행이 떨어져 리프 337→336 으로 준다(모듈15 parts 2→1).
TREEGRID_READ_JS = r"""(fields) => {
  try {
    const el = document.querySelector('.dews-ui-treegrid');
    if (!el) return { ok: false, reason: 'no-treegrid' };
    const g = window.jQuery(el).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const count = ds.getRowCount();
    const rows = [];
    for (let i = 1; i <= count; i++) {
      let level = -1;
      try { level = ds.getLevel(i); } catch (e) {}
      const row = { i, level };
      for (const f of fields) {
        try { row[f] = ds.getValue(i, f); } catch (e) { row[f] = null; }
      }
      rows.push(row);
    }
    return { ok: true, count, rows };
  } catch (e) { return { ok: false, err: String(e).slice(0, 150) }; }
}"""


# ══════════════════════════════════════════════════════════════════════════════
# Phase B — 쓰기 경로(2026-08-28 개방). 근거: e2e/purchase_order_screen1_dryrun_probe.py
# (2026-08-26 드라이런 5회, PROCESS.md '화면 ① 쓰기 경로 실측').
# ⚠ 체크 API 는 **ds(데이터 행) 공간**의 checkRow/getCheckedRows 만 쓴다 — checkItem 계열은
#   아이템 인덱스 공간이라 ds 행을 넘기면 다음 발주단위까지 딸려온다(실측 10→99행).
# ══════════════════════════════════════════════════════════════════════════════
_TREEGRID_PREAMBLE = (
    "const el = document.querySelector('.dews-ui-treegrid');"
    "if (!el) return { ok: false, reason: 'no-treegrid' };"
    "const g = window.jQuery(el).data('dewsControl')._grid;"
)

# 전체 선택/해제 — grid.checkAll(bool). 반환 {ok, before, after}.
TREEGRID_CHECK_ALL_JS = r"""(on) => {
  try {
    %s
    const before = (g.getCheckedRows() || []).length;
    g.checkAll(!!on);
    const after = (g.getCheckedRows() || []).length;
    return { ok: true, before, after };
  } catch (e) { return { ok: false, err: String(e).slice(0, 150) }; }
}""" % _TREEGRID_PREAMBLE

# ds 행 목록을 checkRow(row, true) 로 체크(자손 자동 전파) 후 현재 체크 집합을 돌려준다.
# arg = [rows]. 반환 {ok, checked:[ds행…]}.
TREEGRID_CHECK_ROWS_JS = r"""(rows) => {
  try {
    %s
    for (const r of rows) g.checkRow(r, true);
    const checked = (g.getCheckedRows() || []).slice();
    return { ok: true, checked };
  } catch (e) { return { ok: false, err: String(e).slice(0, 150) }; }
}""" % _TREEGRID_PREAMBLE

# 현재 체크된 ds 행 목록(읽기 전용). 반환 {ok, checked}.
TREEGRID_CHECKED_ROWS_JS = r"""() => {
  try {
    %s
    return { ok: true, checked: (g.getCheckedRows() || []).slice() };
  } catch (e) { return { ok: false, err: String(e).slice(0, 150) }; }
}""" % _TREEGRID_PREAMBLE

# 지정 ds 행들의 한 필드 값 — 적용([적용]) 반영 독립 확인용. arg = [rows, field]. 반환 {row: value}.
TREEGRID_FIELD_JS = r"""([idxs, f]) => {
  try {
    const el = document.querySelector('.dews-ui-treegrid');
    const ds = window.jQuery(el).data('dewsControl')._grid.getDataSource();
    const out = {};
    for (const i of idxs) { try { out[i] = ds.getValue(i, f); } catch (e) { out[i] = null; } }
    return out;
  } catch (e) { return {}; }
}"""

# 보이는 확인 다이얼로그(k-window/k-dialog) 목록 — {title,text,buttons}. 프로젝트 도움창 제외는
# 호출자가 한다.
DIALOGS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window, .k-dialog, [role=alertdialog]')]
    .filter(w => w.offsetParent !== null);
  return wins.map(w => ({
    title: c((w.querySelector('.k-window-title')||{}).innerText),
    text: c(w.innerText).slice(0, 200),
    buttons: [...w.querySelectorAll('button')].filter(b => b.offsetParent !== null).map(b => c(b.innerText)),
  }));
}"""

# 보이는 다이얼로그 안의 버튼(텍스트 정확 일치) 중앙 좌표. 반환 {x,y} | null.
DIALOG_BTN_BOX_JS = r"""(btnText) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window, .k-dialog, [role=alertdialog]')]
    .filter(w => w.offsetParent !== null);
  for (const w of wins) {
    const b = [...w.querySelectorAll('button')].find(x => x.offsetParent !== null && c(x.innerText) === btnText);
    if (b) { const r = b.getBoundingClientRect(); return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2) }; }
  }
  return null;
}"""

# 요소 id 로 중앙 좌표 — 필터행 `[적용]` 6종은 rowText 로 구분 불가라 **버튼 id 필수**(실측).
# 반환 {x,y,disabled} | null(미존재/숨김).
BOX_BY_ID_JS = r"""(id) => {
  const b = document.getElementById(id);
  if (!b || b.offsetParent === null) return null;
  const r = b.getBoundingClientRect();
  return { x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2), disabled: !!b.disabled };
}"""

# 필터행/상단 코드피커 돋보기 — `<id>-wrapper .dews-codepicker-button`(document 스코프,
# codepicker._open_picker 는 card_collect 모달 전용이라 안 먹는다 — 실측). 반환 {x,y} | null.
PICKER_OPEN_BOX_JS = r"""(id) => {
  const w = document.getElementById(id + '-wrapper');
  const b = w ? w.querySelector('.dews-codepicker-button') : null;
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return { x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2) };
}"""

# 입력 값 읽기(코드피커는 `<id>_text` 표시 우선). 반환 string | null.
INPUT_VALUE_JS = r"""(id) => {
  const e = document.getElementById(id + '_text') || document.getElementById(id);
  return e ? (e.value ?? null) : null;
}"""

# 셀렉터 중앙 좌표(보이는 것만). 반환 {x,y,disabled} | null.
BOX_BY_SELECTOR_JS = r"""(sel) => {
  const b = document.querySelector(sel);
  if (!b || b.offsetParent === null) return null;
  const r = b.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return null;
  return { x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2), disabled: !!b.disabled };
}"""

# 화면에 보이는 번호 후보 — 접두(IRQ/PRQ 등)+숫자 패턴을 input 값·텍스트에서 전부 수집.
# 저장 성공 신호 = 상단에 자동 발급되는 이동요청번호(IRQ…)/구매요청번호(PRQ…)(시연 ✅).
# 저장 전 스냅샷과 diff 해 **새로 나타난 번호**를 저장 결과로 삼는다. arg = prefix. 반환 string[].
FIND_NUMBERS_JS = r"""(prefix) => {
  const re = new RegExp('\\b' + prefix + '\\d{6,}\\b', 'g');
  const out = new Set();
  for (const e of document.querySelectorAll('input')) {
    const v = String(e.value || '');
    for (const m of v.match(re) || []) out.add(m);
  }
  for (const m of (document.body.innerText || '').match(re) || []) out.add(m);
  return [...out];
}"""

# 성공 스낵바 문구('자료가 정상적으로 저장되었습니다.' — 시연 ✅) 또는 경고 스낵바 수집.
SNACKBARS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const out = [];
  for (const el of document.querySelectorAll('.dews-ui-snackbar')) {
    if (el.offsetParent === null) continue;
    out.push({ text: c(el.innerText), cls: el.className });
  }
  return out;
}"""

# ── 화면 ② 구매요청처리(PUOPRQ00300) — 마스터 그리드(.dews-ui-grid[0]) ─────────────
# 요청번호 컬럼 PURREQ_NO · 결재상태 ATHZ_ST_NM · 결재상신코드 GWDOCU_NO(2026-08-25 랜딩 실측).
# 전량 읽기(플랫 그리드 — getJsonRows). 반환 {ok, rows:[{i, PURREQ_NO, ATHZ_ST_NM, GWDOCU_NO, KOR_NM}]}.
REQ_MASTER_ROWS_JS = r"""() => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[0]).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const rows = [];
    for (let i = 0; i < n; i++) {
      const r = {};
      for (const f of ['PURREQ_NO', 'ATHZ_ST_NM', 'GWDOCU_NO', 'KOR_NM', 'PURREQ_DT']) {
        try { r[f] = ds.getValue(i, f); } catch (e) { r[f] = null; }
      }
      r.i = i;
      rows.push(r);
    }
    return { ok: true, count: n, rows };
  } catch (e) { return { ok: false, err: String(e).slice(0, 150) }; }
}"""

# 마스터 행 선택 — setCurrent + checkRow(voucher CHECK_ROW_JS 와 동일 규율). 다른 행 체크는
# 먼저 전부 해제해 정확히 1행만 체크된 상태로 결재를 연다. arg = idx. 반환 bool.
REQ_SELECT_ROW_JS = r"""(idx) => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[0]).data('dewsControl')._grid;
    try { g.checkAll(false); } catch (e) {}
    g.setCurrent({ itemIndex: idx, fieldName: g.getColumns()[1].fieldName });
    g.checkRow(idx, true);
    return true;
  } catch (e) { return false; }
}"""
