"""전표조회승인(GLDDOC00700) 화면 고유 in-page JS 상수 — voucher_receivable 프로브 이식.

이 화면 고유 위젯(dews MultiCodePicker/CodePicker/PeriodPicker + 조회결과 마스터그리드 +
결제(결재)창=별도 팝업 Page)을 잡는 JS 만 여기 둔다. 범용 JS(드롭다운 세팅·rowcount·모달
스냅샷)는 ``nbkit.omnisol.js_lib`` 를, CSS 셀렉터(BTN_LOOKUP 등)는 ``nbkit.omnisol.selectors``
를 재사용한다(리스킨 시 한 곳만 고침). 값/좌표는 e2e/voucher_receivable_probe.py 3회 그린 실측.

⚠ CHILD_TOP_BUTTONS_JS 는 **읽기 전용**(좌표·텍스트 반환)이다 — 상신/보관 버튼을 클릭하는
   JS 는 이 파일에 없다(절대 안전: 결제창에서 상신/보관 클릭 금지).
"""

from __future__ import annotations

# 라벨 텍스트로 그 필드의 '검색(돋보기)' dews-multicodepicker-button 좌표를 찾는다.
# 같은 li 안 두 번째 버튼(1=화살표 드롭다운, 2=돋보기). 반환 {x, y}(중앙좌표) 또는 null.
# ⚠ 방어: 라벨이 optional-area(패널 접힘) 안에 있으면 버튼은 DOM엔 있지만 rect 가 0×0/숨김
#   이라 — 그런 경우 (0,0) 같은 오판 좌표 대신 **null** 을 돌려준다(호출자가 "찾음"으로
#   오판해 빗나간 좌표를 클릭하는 것을 소스에서 차단).
FIELD_SEARCH_BTN_RECT_JS = r"""(label) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const lbl = [...document.querySelectorAll('label')].find(e => c(e.innerText) === label);
  if (!lbl) return null;
  const li = lbl.closest('li');
  const btns = [...li.querySelectorAll('.dews-multicodepicker-button')];
  const btn = btns[1] || btns[0];
  if (!btn) return null;
  const r = btn.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0 || btn.offsetParent === null) return null;
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# 라벨의 돋보기 버튼이 **실제로 클릭 가능한 크기로 렌더**돼 있는지(패널이 접혀 0×0 이 아닌지)
# 확인한다. optional-area 필드(전표유형)가 다른 필드 조작 중간에 재접히는 레이스(실측: D2 순회
# 5단계 뒤 재접힘 관찰)를 감지하기 위한 것 — FIELD_SEARCH_BTN_RECT_JS 단독으로는 접힌 버튼도
# {x:0,y:0} 같은 값을 돌려줘 "찾음"으로 오판할 수 있다. 반환 bool.
FIELD_LABEL_VISIBLE_JS = r"""(label) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const lbl = [...document.querySelectorAll('label')].find(e => c(e.innerText) === label);
  if (!lbl) return false;
  const li = lbl.closest('li');
  const btns = [...li.querySelectorAll('.dews-multicodepicker-button')];
  const btn = btns[1] || btns[0];
  if (!btn) return false;
  const r = btn.getBoundingClientRect();
  return r.width > 0 && r.height > 0 && btn.offsetParent !== null;
}"""

# 최상단 k-window 팝업의 RealGrid 에서 지정 필드값과 일치하는 행을 checkRow.
# arg = [targets(문자열 배열), fieldName]. 반환 {ok, idxs:[{t,idx,code}], n}. 무매칭 target 은 빠짐.
POPUP_CHECK_ROWS_JS = r"""([targets, fieldName]) => {
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const dlg = wins[wins.length - 1];
  if (!dlg) return { ok: false, reason: 'no-popup' };
  const g = window.jQuery(dlg.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
  const ds = g.getDataSource();
  const n = ds.getRowCount();
  const rows = ds.getJsonRows(0, n - 1);
  const idxs = [];
  for (const t of targets) {
    const idx = rows.findIndex(r => String(r[fieldName]).trim() === t);
    if (idx >= 0) { g.checkRow(idx, true); idxs.push({ t, idx, code: rows[idx][fieldName.replace('_NM', '_CD')] }); }
  }
  return { ok: true, idxs, n };
}"""

# 팝업의 checkAll(작성부서 전체선택 전용 — checkbox 컬럼 헤더 체크와 동일 효과). 반환 {ok, n}.
POPUP_CHECK_ALL_JS = r"""() => {
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const dlg = wins[wins.length - 1];
  if (!dlg) return { ok: false };
  const g = window.jQuery(dlg.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
  g.checkAll();
  return { ok: true, n: g.getDataSource().getRowCount() };
}"""

# 최상단 k-window 팝업의 '적용' 버튼 좌표. 반환 {x, y} 또는 null.
POPUP_APPLY_BTN_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const dlg = wins[wins.length - 1];
  if (!dlg) return null;
  const b = [...dlg.querySelectorAll('button')].find(x => c(x.innerText) === '적용');
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# 조회조건 패널 확장(▲/▼) 토글 좌표(전표유형 필드가 optional-area 라 펼쳐야 보임). {x, y} 또는 null.
# ⚠ 첫 매치(document.querySelector)만 잡는다 — 화면에 확장 토글이 **여러 개**일 수 있어(도메인
#   전문가 실측, 2026-07-21) 이 토글이 항상 전표유형을 드러낸다는 보장이 없다. set_query 진입
#   시 1회 워밍(no-op 안전)용으로만 쓰고, 전표유형처럼 특정 필드를 드러내야 할 때는
#   EXPAND_TOGGLE_RECTS_JS(복수) + ensure_field_visible(결과검증형)을 쓸 것.
EXPAND_TOGGLE_RECT_JS = r"""() => {
  const b = document.querySelector('.dews-condition-panel-expand-button');
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# 화면에 보이는 **모든** 조회조건 확장 토글 좌표를 좌→우 순으로 반환(빈 배열 가능). 하위 패널마다
# 각자 확장 버튼을 가질 수 있어(도메인전문가 실측), 어느 토글이 목표 필드를 드러내는지 미리 알
# 수 없다 — ensure_field_visible 이 하나씩 결과검증형으로 시도한다.
EXPAND_TOGGLE_RECTS_JS = r"""() => {
  const btns = [...document.querySelectorAll('.dews-condition-panel-expand-button')]
    .filter(b => b.offsetParent !== null);
  const rects = btns.map(b => {
    const r = b.getBoundingClientRect();
    return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
  });
  rects.sort((a, b) => a.x - b.x);
  return rects;
}"""

# 필드 표시값(멀티코드피커 text input) 읽기 — 검증/로깅용. 반환 문자열 또는 null.
FIELD_DISPLAY_JS = r"""(label) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const lbl = [...document.querySelectorAll('label')].find(e => c(e.innerText) === label);
  if (!lbl) return null;
  const li = lbl.closest('li');
  const inp = li.querySelector('.dews-multicodepicker-text, .dews-codepicker-text');
  return inp ? inp.value : null;
}"""

# 회계일 periodpicker 를 당월(1일~말일)로 세팅하는 앱 API(setMonth). ⚠ YYYYMMDD 타이핑 아님.
SET_PERIOD_THIS_MONTH_JS = (
    "() => { try { window.jQuery(document.querySelector('#s_period'))"
    ".data('dewsControl').setMonth(); return true; } catch (e) { return false; } }"
)

# 작성자 multicodepicker 기본선택을 비우는 앱 API(clear).
CLEAR_WRITER_JS = (
    "() => { try { window.jQuery(document.querySelector('#s_wrt_emp_no'))"
    ".data('dewsControl').clear(); return true; } catch (e) { return false; } }"
)

# 결과 마스터 그리드(index 0) 컬럼+rowcount+상위 N행 덤프. arg=limit. 반환 {ok, n, cols, sample}.
MASTER_DUMP_JS = r"""(limit) => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[0]).data('dewsControl')._grid;
    const cols = g.getColumns().map(c => ({ field: c.fieldName, header: (c.header && c.header.text) || c.name }));
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const take = Math.min(n, limit || 5);
    const rows = take > 0 ? ds.getJsonRows(0, take - 1) : [];
    return { ok: true, n, cols, sample: rows };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 140) }; }
}"""

# 마스터 그리드 idx 행의 키(DOCU_NO) 읽기. arg=idx. 반환 문자열 또는 null.
READ_ROW_KEY_JS = r"""(idx) => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[0]).data('dewsControl')._grid;
    const rows = g.getDataSource().getJsonRows(idx, idx);
    return rows && rows[0] ? rows[0].DOCU_NO : null;
  } catch (e) { return null; }
}"""

# 마스터 그리드 idx 행 선택 — setCurrent(하이라이트/디테일 연동) + checkRow(결재 대상 인식 필수).
# D4 실측: checkRow 없이 setCurrent 만으론 결재 버튼이 대상을 인식하지 못한다. arg=idx. 반환 bool.
CHECK_ROW_JS = r"""(idx) => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[0]).data('dewsControl')._grid;
    g.setCurrent({ itemIndex: idx, fieldName: g.getColumns()[1].fieldName });
    g.checkRow(idx, true);
    return true;
  } catch (e) { return false; }
}"""

# 마스터 그리드 전체 체크 해제 — 배치 순회에서 직전 대상 행의 체크가 남아 결재가 여러 문서를
# 잡는 것을 막는다(대상 행 체크 직전에 호출해 정확히 한 행만 체크된 상태로 결재). arg 없음. 반환 bool.
UNCHECK_ALL_JS = r"""() => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[0]).data('dewsControl')._grid;
    g.checkAll(false);
    return true;
  } catch (e) { return false; }
}"""

# D7(배치 순회 정합성) — 마스터 그리드에서 현재 **체크된** 행 인덱스 목록. 결제(결재) 버튼을
# 누르기 직전 "정확히 1행만 체크"인지 검증하는 용도(읽기전용). RealGrid 버전에 따라 체크 API가
# 다를 수 있어 `getCheckedRows()` 를 우선 시도하고 없으면 `getRowState` 스캔으로 폴백한다.
# arg 없음. 반환 {ok, method, rows:[idx,...]} 또는 {ok:false, reason}.
CHECKED_ROW_INDEXES_JS = r"""() => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[0]).data('dewsControl')._grid;
    if (typeof g.getCheckedRows === 'function') {
      return { ok: true, method: 'getCheckedRows', rows: g.getCheckedRows() };
    }
    const n = g.getDataSource().getRowCount();
    const rows = [];
    for (let i = 0; i < n; i++) {
      const st = g.getRowState ? g.getRowState(i) : null;
      if (st && st.checked) rows.push(i);
    }
    return { ok: true, method: 'getRowState-scan', rows };
  } catch (e) {
    return { ok: false, reason: String(e).slice(0, 140) };
  }
}"""

# 결제(결재) 버튼 좌표 — button.main-button.approval, innerText '결재'. 반환 {x, y} 또는 null.
# ⚠ 방어(2026-07-21 배치 라이브 실측: 1건째 성공 후 2건째 결제창 미출현 관찰): 버튼이 DOM엔
#   있어도 일시적으로 숨김/0크기(자식창 닫힘 직후 전환 애니메이션 등)일 수 있다 — 그런 경우
#   좌표 대신 null 을 돌려줘 호출자가 "찾음"으로 오판하지 않게 한다(FIELD_SEARCH_BTN_RECT_JS
#   와 동일 패턴).
APPROVAL_BTN_RECT_JS = r"""() => {
  const b = document.querySelector('button.main-button.approval');
  if (!b) return null;
  const r = b.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0 || b.offsetParent === null) return null;
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# D7 반복 견고화 — 근본원인 확정(도메인전문가 + 2026-07-21 읽기전용 진단 2건):
#   1. e2e/voucher_receivable_open_approval_diag.py: check_row(setCurrent)가 디테일 그리드
#      재조회를 트리거해 `.dews-loading-bg` 오버레이가 잠깐 뜨는데, 이때 결재 버튼을 클릭하면
#      좌표는 버튼 위여도 **오버레이가 클릭을 가로챈다**(elementFromPoint 실측: 버튼 대신
#      dews-loading-bg DIV 반환 → window.open 미호출).
#   2. e2e/voucher_receivable_parent_loading_diag.py: **결제창을 닫으면**(close_child) 본창이
#      별도 후처리를 하며 `.dews-loading-container`(자식: `.dews-loading-img`/`.dews-loading-text`)
#      스피너가 뜬다(실측: close 직후 t=0.0s 부터 t≈0.6s 까지 visible). 도메인전문가 확정:
#      "그 로딩이 끝나기 전에 다음 행을 체크하고 결제를 다시 호출해서 안 되는 것" — 이게 2건째
#      결제창 미출현의 진짜 근본원인.
# 두 케이스 모두 커버하도록 알려진 dews/kendo 로딩류 셀렉터를 전부 체크한다(그중 하나라도
# 보이면 true). k-loading-mask/k-loading/dews-loading 은 도메인전문가가 제시한 후보 —
# 라이브에서 미확인이어도 querySelector 가 null 이면 그냥 넘어가 무해하다. 반환 bool.
LOADING_OVERLAY_VISIBLE_JS = r"""() => {
  const sels = [
    '.dews-loading-bg', '.dews-loading-container',
    '.k-loading-mask', '.k-loading', '.dews-loading',
  ];
  for (const sel of sels) {
    const el = document.querySelector(sel);
    if (!el) continue;
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0 && el.offsetParent !== null) return true;
  }
  return false;
}"""

# 결제창(전자결재 팝업, 별도 Page) 상단 버튼(미리보기/보관/상신) 텍스트·좌표 — 리프노드 탐색.
# ⚠ 읽기 전용: 렌더완료 판정(버튼 텍스트 표출)에만 쓴다. 상신/보관은 절대 클릭하지 않는다.
CHILD_TOP_BUTTONS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const targets = ['상신', '미리보기', '보관'];
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    if (el.children.length > 0) continue;
    const t = c(el.innerText || el.textContent || '');
    if (targets.includes(t)) {
      const r = el.getBoundingClientRect();
      out.push({ text: t, x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2), visible: el.offsetParent !== null });
    }
  }
  return out;
}"""

# D7(배치 순회 정합성) — 결제창(자식 Page, EAP)에 실제로 표시된 전표번호를 읽는다. 결제창이
# 대상 행과 다른 문서를 열었는지(행/팝업 어긋남) 대조하는 용도. ⚠ 읽기 전용.
# EAP 폼의 '전표번호' 셀 셀렉터/클래스가 미확정이라(리스킨 취약) 좌표/클래스에 의존하지 않고
# **리프 텍스트노드 전량을 정규식으로 스캔**한다(실측 포맷: 'FI'+숫자8자리 이상, 예
# FI2026070100000010). 반환: 매치된 고유 문자열 배열 — 0개=못 찾음(모호), 1개=확정,
# 2개+=모호(다른 곳에 같은 패턴이 더 있음 — 하드 실패 근거로 쓰지 않는다).
CHILD_DOCU_NO_JS = r"""() => {
  const re = /\bFI\d{8,}\b/;
  const out = new Set();
  for (const el of document.querySelectorAll('*')) {
    if (el.children.length > 0) continue;
    const t = (el.innerText || el.textContent || '').trim();
    const m = t.match(re);
    if (m) out.add(m[0]);
  }
  return [...out];
}"""
