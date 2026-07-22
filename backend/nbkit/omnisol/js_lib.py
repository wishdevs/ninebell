"""옴니솔 **in-page JS 문자열 단일 소스**.

RealGrid 는 캔버스라 DOM 추출이 안 통한다 → 그리드 인스턴스를 jQuery data 로 잡아
(``$('.dews-ui-grid').data('dewsControl')._grid``) 앱 함수(getJsonRows/getDataSource)를
직접 호출한다. 그 in-page 스크립트를 여기 모아 화면 리스킨 시 한 곳만 고치게 한다
(CSS 셀렉터 상수는 :mod:`nbkit.omnisol.selectors`).

⚠ ``getJsonRows(start, end)`` 는 **end-inclusive**. 20행 = ``getJsonRows(0, 19)``.
  off-by-one 정규화는 :mod:`nbkit.grid.provider` 에서 중앙 처리한다 — 여기 JS 는 이미
  정규화된 end-inclusive 인덱스를 받는다.

섹션: [A] P1 이 쓰는 코어 · [B] P3(법인카드 대화형)가 쓰는 옴니솔 프리미티브(inert 상수).
"""

from __future__ import annotations

# ══════════════════════════════════════════════════════════════════════════════
# [A] 코어 — P1 (grid/provider·omnisol/auth·navigator·profile) 가 사용
# ══════════════════════════════════════════════════════════════════════════════

# ── 그리드 행수/행 읽기(인덱스 파라미터화) ─────────────────────────────────────
# 반환 -1 = 그리드 접근 실패(아직 미로드/인스턴스 없음), >=0 = rowCount.
ROWCOUNT_BY_INDEX_JS = (
    "(index) => { try { return window.jQuery(document.querySelectorAll('.dews-ui-grid')[index])"
    ".data('dewsControl')._grid.getDataSource().getRowCount(); } catch (e) { return -1; } }"
)

# 마스터 그리드(인덱스 0) 전용 rowCount — ninebell _ROWCOUNT_JS 와 동일(조회 폴링용).
ROWCOUNT_JS = (
    "() => { try { return [...document.querySelectorAll('.dews-ui-grid')]"
    ".map(g => window.jQuery(g).data('dewsControl'))[0]._grid.getDataSource()"
    ".getRowCount(); } catch (e) { return -1; } }"
)

# end-inclusive 인덱스로 JSON 행 읽기. arg = {index, start, end}(end 포함).
# 반환: 행 배열, 빈 범위면 [], 그리드 접근 실패면 null(호출자가 GridError 로 승격).
GET_JSON_ROWS_JS = """({ index, start, end }) => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[index]).data('dewsControl')._grid.getDataSource();
    if (end < start) return [];
    return g.getJsonRows(start, end);
  } catch (e) { return null; }
}"""

# 그리드[index] 의 현재 행 앵커링(키보드 폴백 방법B 시작점). arg = {index, itemIndex}.
# ⚠ setCurrent 는 디테일 로딩을 트리거하지 않는다 — 앵커링 전용. 로딩은 trusted 키보드로.
SET_CURRENT_BY_INDEX_JS = """({ index, itemIndex }) => {
  try {
    window.jQuery(document.querySelectorAll('.dews-ui-grid')[index]).data('dewsControl')._grid.setCurrent({ itemIndex });
    return true;
  } catch (e) { return false; }
}"""

# ── 메뉴 진입 상태 판별 ────────────────────────────────────────────────────────
# 그리드가 떴는지 / "메뉴를 찾을 수 없습니다" 권한 팝업인지. {grids, notFound, popup}.
MENU_CHECK_JS = """() => {
  const grids = document.querySelectorAll('.dews-ui-grid').length;
  const dlg = [...document.querySelectorAll('.k-window, [role=dialog], .modal')].find(x => x.offsetParent !== null);
  const popup = dlg ? (dlg.innerText || '').trim() : '';
  const notFound = /찾을 수 없|권한이 없|접근/.test(popup) && /메뉴|모듈/.test(popup);
  return { grids, notFound, popup: popup.replace(/\\n+/g, ' ').slice(0, 50) };
}"""

# ── 프로필(이름·부서·사용자유형) best-effort 추출 ──────────────────────────────
AVATAR_CLICK_JS = (
    "() => { const a = document.querySelector('img[src*=profile_circle]') "
    "|| [...document.querySelectorAll('header img, img[alt]')].pop(); if (a) a.click(); }"
)

PROFILE_JS = r"""() => {
  const out = { display_name: "", department: "", user_types: [] };
  const clean = s => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  // '/' 포함 전체 부서명 포착(예 '인사/기획팀'). '/'가 빠지면 접두부(인사)가 잘린다.
  const deptRe = /([가-힣A-Za-z0-9][가-힣A-Za-z0-9/]*(?:팀|부서|부|실|본부|센터|그룹|사업부|TF))/;
  const sel = [...document.querySelectorAll('select')]
    .find(s => [...s.options].some(o => /사용자/.test(o.text || '')));
  if (sel) out.user_types = [...sel.options].map(o => (o.text || '').trim()).filter(Boolean);
  // 1) 전용 엘리먼트(.dept-name) — 가장 정확(슬래시 포함 전체 부서명, 실측 확인).
  const deptEl = document.querySelector('.user-info .dept-name, .dept-name');
  if (deptEl) out.department = clean(deptEl.innerText || deptEl.textContent).slice(0, 60);
  // 2) 폴백: 사용자유형 select 근처 패널에서 부서 토큰 탐색.
  if (!out.department && sel) {
    let node = sel.closest('.user-info, .user-info-change, .k-window, [role=dialog]') || sel.parentElement;
    for (let i = 0; i < 5 && node; i++) {
      const m = clean(node.innerText).match(deptRe);
      if (m) { out.department = m[1]; break; }
      node = node.parentElement;
    }
  }
  // 3) 최종 폴백: 본문 전체 첫 매치(정확도 낮음 — 위 두 경로 실패 시에만).
  if (!out.department) {
    const body = document.body ? clean(document.body.innerText) : '';
    const m = body.match(deptRe);
    if (m) out.department = m[1];
  }
  const nameEl = document.querySelector(
    '[class*="user"] [class*="name"], .user-name, .username, header [class*="name"]'
  );
  if (nameEl) out.display_name = ((nameEl.innerText || nameEl.textContent) || '').trim().slice(0, 40);
  return out;
}"""

# ── 사용자유형 전환(실클릭 좌표만 반환; 실제 클릭은 page.mouse) ────────────────
# ⚠ JS .click()/위젯 .value() 는 더존 변경적용 핸들러를 못 깨운다 → 좌표 실클릭 필수.
UT_DROPDOWN_BOX_JS = (
    "() => { const d=[...document.querySelectorAll('.k-dropdown')].find(e=>e.offsetParent!==null"
    " && /사용자/.test(e.innerText||'')); if(!d) return null; const r=d.getBoundingClientRect();"
    " return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)}; }"
)
UT_OPTION_BOX_JS = (
    "(target) => { const li=[...document.querySelectorAll('li.k-item, .k-list li, ul[role=listbox] li')]"
    ".find(e=>e.offsetParent!==null && new RegExp(target+'사용자').test(e.innerText||''));"
    " if(!li) return null; const r=li.getBoundingClientRect();"
    " return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)}; }"
)
UT_APPLY_BOX_JS = (
    "() => { const a=[...document.querySelectorAll('button.apply, button')].find(e=>e.offsetParent!==null"
    " && (e.innerText||'').trim()==='변경적용'); if(!a) return null; const r=a.getBoundingClientRect();"
    " return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)}; }"
)
UT_DISPLAY_JS = (
    "() => { const d=[...document.querySelectorAll('.k-dropdown')].find(e=>e.offsetParent!==null"
    " && /사용자/.test(e.innerText||'')); return d?(d.innerText||'').trim():''; }"
)
# 현재 사용자유형 읽기(전환 안 함) — 숨은 native select 의 선택 옵션 텍스트.
USER_TYPE_READ_JS = """() => {
  const sel = [...document.querySelectorAll('select')].find(s => [...s.options].some(o => /사용자/.test(o.text)));
  return sel ? sel.options[sel.selectedIndex].text.trim() : '?';
}"""

# ── 공장(플랜트) 확인 — 조회 폼 값 또는 타이틀에 '나인벨' 포함 여부 ──────────────
PLANT_CHECK_JS = (
    "() => { const inp = [...document.querySelectorAll('input')].map(i => i.value)"
    ".filter(v => /나인벨/.test(v))[0];"
    " const t = /나인벨/.test(document.title) ? document.title.trim() : null;"
    " const v = inp || t; return { ok: !!v, plant: v || '?' }; }"
)


def collect_master_detail_js(service_url: str) -> str:
    """마스터(getJsonRows end-inclusive) + 디테일($.ajax 병렬) 수집 JS 생성.

    arg = limit(수집할 마스터 수). ``take = min(limit, total)`` 로 클램프하고
    ``getJsonRows(0, take-1)`` 로 off-by-one 을 회피한다(collection-strategies §핵심발견).
    디테일은 행당 1요청 고정이라 마스터별 ``$.ajax`` 를 병렬 발사(앱이 인증 JWT 자동주입 →
    네트워크 가로채기 아님). 반환 ``{ total, masters, details:[{no, rows}] }``.
    """
    return (
        "async (limit) => {\n"
        "  const ctrls = [...document.querySelectorAll('.dews-ui-grid')].map(g => window.jQuery(g).data('dewsControl'));\n"
        "  const dp = ctrls[0]._grid.getDataSource();\n"
        "  const total = dp.getRowCount();\n"
        "  const take = Math.max(0, Math.min(limit, total));\n"
        "  const masters = take ? dp.getJsonRows(0, take - 1) : [];\n"
        f"  const url = {service_url!r};\n"
        "  const details = await Promise.all(masters.map(m =>\n"
        "    Promise.resolve(window.jQuery.ajax({ url, type: 'GET', data: { _uidParent: m._uid, invtrx_rsv_no: m.INVTRX_RSV_NO, close_yn: 'N' } }))\n"
        "      .then(r => ({ no: m.INVTRX_RSV_NO, rows: (r && r.data) || [] }))\n"
        "      .catch(() => ({ no: m.INVTRX_RSV_NO, rows: [] }))\n"
        "  ));\n"
        "  return { total, masters, details };\n"
        "}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# [B] P3 옴니솔 프리미티브 — 법인카드 대화형(결의서입력) 화면 접근용 inert 상수.
#     P1 은 실행하지 않는다. P3 가 nbkit 위에서 조합해 쓰도록 여기 단일 소스로 둔다.
# ══════════════════════════════════════════════════════════════════════════════

# 결의구분 Kendo dropdownlist(#s_abdocu_fg_cd) 를 옵션 텍스트로 설정(+change 발화).
# arg = 옵션 텍스트(예 '카드'). 반환 {ok, val?} / {ok:false, found?:false}.
KENDO_SET_DROPDOWN_BY_TEXT_JS = """({ selector, text }) => {
  const sel = document.querySelector(selector);
  if (!sel) return { ok: false };
  const opt = [...sel.options].find(o => o.text.trim() === text);
  if (!opt) return { ok: false, found: false };
  const w = window.jQuery(sel).data('kendoDropDownList');
  if (w) { w.value(opt.value); w.trigger('change'); }
  else { sel.value = opt.value; sel.dispatchEvent(new Event('change', { bubbles: true })); }
  return { ok: true, val: opt.value };
}"""

# 디테일 그리드(인덱스 1) 증빙 셀 에디터 열기: setCurrent + showEditor(캔버스 → DOM 오버레이).
# ⚠ 항상 '마지막 행'을 연다 — F3 신규 행은 맨 아래에 추가된다(실측). itemIndex 0 고정이던
#   시절, 2패스 플로우에서 기존(1차 적용) 행의 증빙을 열어 불공(02)이 과세 행에 덮어써지는
#   실전 사고가 있었다(2026-07-02). 반환 {ok, idx, rows} | false.
OPEN_EVDN_EDITOR_JS = """() => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
    const n = g.getDataSource().getRowCount();
    const idx = Math.max(0, n - 1);
    g.setCurrent({ itemIndex: idx, fieldName: 'EVDN_TP_NM' });
    g.showEditor();
    return { ok: true, idx: idx, rows: n };
  } catch (e) { return false; }
}"""

# showEditor 로 뜬 DOM 에디터 input 의 돋보기 클릭 좌표(input 오른쪽 +8px, 검증된 오프셋).
EVDN_EDITOR_MAGNIFIER_RECT_JS = """() => {
  const inp = [...document.querySelectorAll('input')].find(i => /gridDetail_line/.test(i.id || '') && i.offsetParent !== null);
  if (!inp) return null;
  const r = inp.getBoundingClientRect();
  return { x: r.right + 8, y: r.top + r.height / 2 };
}"""

# 디테일 그리드(인덱스 1) 마지막 행의 **임의 필드** 셀 에디터 열기 — OPEN_EVDN_EDITOR_JS 를
# fieldName 파라미터화한 일반형(거래처 PARTNER_CD·예산 BG_CD·프로젝트 PJT_CD·상대계정
# BFC_PARTNER_CD 셀에 공용). 항상 '마지막 행'(F3 신규 행은 맨 아래) 을 연다. arg=fieldName.
# 반환 {ok, idx, rows} | {ok:false, reason}. (증빙 셀은 기존 OPEN_EVDN_EDITOR_JS 유지.)
OPEN_DETAIL_CELL_EDITOR_JS = """(fieldName) => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
    const n = g.getDataSource().getRowCount();
    const idx = Math.max(0, n - 1);
    g.setCurrent({ itemIndex: idx, fieldName });
    g.showEditor();
    return { ok: true, idx: idx, rows: n };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 120) }; }
}"""

# showEditor 로 뜬 detail 그리드 에디터 input 의 돋보기 좌표(input 오른쪽 +8px). EVDN 전용
# (/gridDetail_line/) 보다 넓은 매칭(프로브 trip_probe2 검증: /gridDetail_line|gridDetail|_editor/)
# + 폴백(그리드[1] 영역 위 보이는 input). 코드 셀(거래처/예산/프로젝트/상대계정) 공용.
DETAIL_EDITOR_MAGNIFIER_JS = """() => {
  const inp = [...document.querySelectorAll('input')].find(i =>
    /gridDetail_line|gridDetail|_editor/.test(i.id || '') && i.offsetParent !== null);
  if (inp) {
    const r = inp.getBoundingClientRect();
    return { x: r.right + 8, y: r.top + r.height / 2, id: inp.id || '(no-id)', via: 'gridDetail' };
  }
  const g = document.querySelectorAll('.dews-ui-grid')[1];
  const gr = g ? g.getBoundingClientRect() : null;
  const cand = [...document.querySelectorAll('input')].find(i => {
    if (i.offsetParent === null || !gr) return false;
    const r = i.getBoundingClientRect();
    return r.top >= gr.top - 5 && r.top <= gr.bottom + 40 && r.width > 20;
  });
  if (!cand) return null;
  const r = cand.getBoundingClientRect();
  return { x: r.right + 8, y: r.top + r.height / 2, id: cand.id || '(no-id)', via: 'fallback' };
}"""

# 마스터(결의서) 그리드 0행의 회계일(ACTG_DT) 설정 + 표시값 검증 — card 에서 승격(2026-07-06).
# ⚠ 'YYYY-MM-DD'(대시) 형식은 오류 없이 셀을 **비운다**(프로브 실측) — compact 'YYYYMMDD' 만.
# 출장(trip)·card 공용(공통 doc_steps.set_acct_date 가 사용). 인자 ymd='YYYYMMDD'.
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

# 증빙유형 팝업(.k-window.dialog)이 떴는지 — ⚠ 로그인 공지 팝업도 **동일 클래스**(k-widget
# k-window k-window-titleless dialog, notice_popup_probe 실측)라 '보이는 다이얼로그 존재'만으론
# 공지를 증빙 팝업으로 오탐한다(2026-07-22 card-chat 장애: 돋보기 클릭이 공지에 먹혔는데 열림
# 판정 → select 가 공지를 잡아 ._grid TypeError). 증빙 팝업 고유 특징인 내부 .dews-ui-grid
# 보유까지 요구한다 — 아래 EVDN_* 다이얼로그 탐색 전부 동일 규칙.
EVDN_POPUP_OPEN_JS = (
    "() => [...document.querySelectorAll('.k-window.dialog')]"
    ".some(d => d.offsetParent !== null && d.querySelector('.dews-ui-grid'))"
)

# 팝업 그리드에서 지정 코드들의 옵션(코드+이름) 읽기. arg = codes[]. 반환 {ok, options?}.
EVDN_OPTIONS_JS = """(codes) => {
  try {
    const dlg = [...document.querySelectorAll('.k-window.dialog')].find(d => d.offsetParent !== null && d.querySelector('.dews-ui-grid'));
    if (!dlg) return { ok: false };
    const pg = window.jQuery(dlg.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const ds = pg.getDataSource();
    const rows = ds.getJsonRows(0, ds.getRowCount() - 1);
    const opts = rows
      .filter(x => codes.includes(String(x.EVDN_TP_CD).trim()))
      .map(x => ({ value: String(x.EVDN_TP_CD).trim(), label: String(x.EVDN_TP_NM).trim() }));
    return { ok: true, options: opts };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 40) }; }
}"""

# 코드로 증빙유형 행 선택. arg = code(예 '01'). 반환 {ok, code?, name?}.
EVDN_SELECT_BY_CODE_JS = """(code) => {
  try {
    const dlg = [...document.querySelectorAll('.k-window.dialog')].find(d => d.offsetParent !== null && d.querySelector('.dews-ui-grid'));
    if (!dlg) return { ok: false, reason: 'no-dialog' };
    const pg = window.jQuery(dlg.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const ds = pg.getDataSource();
    const rows = ds.getJsonRows(0, ds.getRowCount() - 1);
    const i = rows.findIndex(x => String(x.EVDN_TP_CD).trim() === code);
    if (i < 0) return { ok: false, reason: 'code-not-found' };
    pg.setCurrent({ itemIndex: i, fieldName: 'EVDN_TP_NM' });
    pg.setSelection({ startRow: i, endRow: i, startColumn: 0, endColumn: 0 });
    return { ok: true, code: rows[i].EVDN_TP_CD, name: rows[i].EVDN_TP_NM };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 40) }; }
}"""

# 자유 입력(이름)으로 증빙유형 코드 매칭. arg = text. 반환 {ok, code?, name?}.
EVDN_MATCH_BY_NAME_JS = """(text) => {
  try {
    const dlg = [...document.querySelectorAll('.k-window.dialog')].find(d => d.offsetParent !== null && d.querySelector('.dews-ui-grid'));
    if (!dlg) return { ok: false };
    const pg = window.jQuery(dlg.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const ds = pg.getDataSource();
    const rows = ds.getJsonRows(0, ds.getRowCount() - 1);
    const t = (text || '').trim();
    const row = rows.find(x => String(x.EVDN_TP_NM).trim() === t)
             || rows.find(x => String(x.EVDN_TP_NM).includes(t));
    if (!row) return { ok: false };
    return { ok: true, code: String(row.EVDN_TP_CD).trim(), name: String(row.EVDN_TP_NM).trim() };
  } catch (e) { return { ok: false }; }
}"""

# 모달 '적용' 버튼 중심 좌표(실클릭용).
EVDN_APPLY_BOX_JS = """() => {
  const dlg = [...document.querySelectorAll('.k-window.dialog')].find(d => d.offsetParent !== null && d.querySelector('.dews-ui-grid'));
  if (!dlg) return null;
  const btn = [...dlg.querySelectorAll('button')].find(b => (b.innerText || '').trim() === '적용');
  if (!btn) return null;
  const r = btn.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# 디테일 그리드 0행 증빙 셀 값 — '적용' 반영 판정(모달 닫힘 대신 셀 반영으로).
# ⚠ OPEN_EVDN_EDITOR_JS 와 동일하게 '마지막 행'을 읽는다 — 증빙 선택·적용 대상 행과
#   판정 행이 어긋나면(0행 고정이던 시절) 2패스에서 적용 성공을 실패로 오판한다.
DETAIL_EVDN_CELL_JS = """() => {
  try {
    const ds = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid.getDataSource();
    const idx = Math.max(0, ds.getRowCount() - 1);
    const row = ds.getJsonRows(idx, idx)[0];
    return String((row && row.EVDN_TP_NM) || '');
  } catch (e) { return ''; }
}"""

# 추가(F3) 후 디테일 그리드 rowCount(0→1 판정).
DETAIL_ROWCOUNT_JS = (
    "() => { try { return window.jQuery(document.querySelectorAll('.dews-ui-grid')[1])"
    ".data('dewsControl')._grid.getDataSource().getRowCount(); } catch(e){ return -1; } }"
)

# ── 프로젝트(WBS) 검색형 코드피커 ─────────────────────────────────────────────
# '프로젝트' 라벨 우측 가장 가까운 코드피커 버튼 좌표.
PROJECT_PICKER_BOX_JS = """() => {
  const lbl = [...document.querySelectorAll('label,span,div,th')].find(e => e.offsetParent !== null && (e.innerText || '').trim() === '프로젝트');
  if (!lbl) return null;
  const lr = lbl.getBoundingClientRect();
  const btns = [...document.querySelectorAll('button.dews-codepicker-button')].filter(b => b.offsetParent !== null);
  let best = null, bd = 1e9;
  for (const b of btns) { const r = b.getBoundingClientRect(); if (Math.abs(r.top - lr.top) < 22 && r.left > lr.left) { const dx = r.left - lr.left; if (dx < bd) { bd = dx; best = b; } } }
  if (!best) return null;
  const r = best.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

PROJECT_POPUP_OPEN_JS = """() => [...document.querySelectorAll('.k-window')].some(w => w.offsetParent !== null && /프로젝트/.test(((w.querySelector('.k-window-title')||{}).innerText)||''))"""

# 팝업 검색어 입력(네이티브 setter 로 값 설정 + input 이벤트). arg = q.
PROJECT_SEARCH_SET_JS = """(q) => {
  const i = document.querySelector('#s_search_key');
  if (!i) return false;
  const s = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(i), 'value').set;
  s.call(i, q); i.dispatchEvent(new Event('input', { bubbles: true })); i.focus();
  return true;
}"""

# 팝업 그리드 상위 limit 행 읽기(무한스크롤 → 검색으로 좁힌 뒤 상위만). arg = limit.
PROJECT_READ_JS = """(limit) => {
  try {
    const wins = [...document.querySelectorAll('.k-window')].filter(d => d.offsetParent !== null);
    const dlg = wins[wins.length - 1];
    const g = window.jQuery(dlg.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const ds = g.getDataSource(); const n = ds.getRowCount();
    const take = Math.min(limit, n);
    const rows = take > 0 ? ds.getJsonRows(0, take - 1) : [];
    const clean = v => (v == null || v === 'null') ? '' : String(v).trim();
    return { n, options: rows.map(r => ({
      value: clean(r.WBS_NO),
      label: clean(r.VIEW_WBS_NM) || clean(r.WBS_NM) || clean(r.PJT_NM),
      description: [clean(r.PJT_NO) && ('PJT ' + clean(r.PJT_NO)), clean(r.PARTNER_NM)].filter(Boolean).join(' · '),
    })).filter(o => o.value && o.label) };
  } catch (e) { return { n: -1, options: [], err: String(e).slice(0, 30) }; }
}"""

PROJECT_SELECT_JS = """(wbsNo) => {
  try {
    const wins = [...document.querySelectorAll('.k-window')].filter(d => d.offsetParent !== null);
    const dlg = wins[wins.length - 1];
    const g = window.jQuery(dlg.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const ds = g.getDataSource(); const rows = ds.getJsonRows(0, ds.getRowCount() - 1);
    const i = rows.findIndex(x => String(x.WBS_NO) === String(wbsNo));
    if (i < 0) return { ok: false };
    g.setCurrent({ itemIndex: i, fieldName: 'WBS_NM' });
    g.setSelection({ startRow: i, endRow: i, startColumn: 0, endColumn: 0 });
    return { ok: true, name: rows[i].VIEW_WBS_NM || rows[i].WBS_NM };
  } catch (e) { return { ok: false }; }
}"""

PROJECT_APPLY_BOX_JS = """() => {
  const wins = [...document.querySelectorAll('.k-window')].filter(d => d.offsetParent !== null);
  const dlg = wins[wins.length - 1];
  if (!dlg) return null;
  const btn = [...dlg.querySelectorAll('button')].find(b => (b.innerText || '').trim() === '적용');
  if (!btn) return null;
  const r = btn.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""


# ══════════════════════════════════════════════════════════════════════════════
# ── 코드피커(dews codepicker) 공용 JS — card_collect 에서 승격(2026-07-05) ──
#    :mod:`nbkit.omnisol.codepicker` 엔진이 사용. 피커 팝업 셀렉터 규칙:
#    "최근 열린 non-법인카드 k-window"(피커 팝업은 항상 마지막에 열린다).
# ══════════════════════════════════════════════════════════════════════════════

# 법인카드 거래내역 조회 팝업(k-window 제목=법인카드) 로케이터 식(다른 JS에 임베드).
# picker_btn_js 가 카드팝업 안의 코드피커 버튼을 찾을 때 쓴다(card_collect CARD_* JS 도 공유).
CARD_WIN = (
    "[...document.querySelectorAll('.k-window')].filter(w=>w.offsetParent!==null)"
    ".find(w=>/법인카드/.test(((w.querySelector('.k-window-title')||{}).innerText)||''))"
)


# 코드피커(예산단위 bg_cd / 계정 acct_cd / 프로젝트 pjt_cd) 버튼 좌표(인자 field id).
# 반환 {x,y} | null.
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
  // 팝업별 검색창 id 상이: 예산단위/계정=#keyword, 프로젝트=#s_search_key, 거래처=#customTextBox.
  // 알려진 id 우선(card 동작 보존), 없으면 search_key/keyword/customText 접미·접두 → 첫 보이는 text input.
  const kw = p.querySelector('#keyword') || p.querySelector('#s_search_key')
    || p.querySelector('#customTextBox') || p.querySelector('[id$=search_key]')
    || p.querySelector('[id*=keyword]') || p.querySelector('[id*=customText]')
    || [...p.querySelectorAll('input')].filter(i=>i.offsetParent!==null && (i.type==='text'||!i.type))[0];
  if (!kw) return { ok:false, reason:'no-keyword' };
  const d = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value'); d.set.call(kw, q);
  ['input','change'].forEach(t => kw.dispatchEvent(new Event(t, { bubbles:true })));
  // ⚠ focus 필수 — 이후 page.keyboard.press('Enter')가 이 검색창에 도달해야 서버 재조회가 뜬다.
  // 셀 에디터(showEditor)로 연 팝업(거래처 customTextBox 등)은 포커스가 그리드 캔버스에 있어
  // focus 없이 Enter 를 누르면 검색이 트리거되지 않는다(프로브 trip_probe3 실측 2026-07-06).
  kw.focus();
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


# ── 모달/토스트 관찰 공용 JS — card_collect 에서 승격(2026-07-05) ──────────────────
# :mod:`nbkit.omnisol.modals` (차단 모달 해제)와 저장(F7) 확인 폴링이 사용.

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

# 로그인 직후 뜨는 '공지' 레이어 팝업(전 화면 차단) 감지 — 고유 앵커 #close-today-chk('하루동안
# 보지 않기' 체크박스) + #notice-dialog-close('닫기'). 팝업이 보일 때만 두 요소의 중앙 좌표를,
# 없거나 이미 닫혀 숨김이면 null 을 반환한다. ⚠ 광범위 텍스트/`.k-window.dialog` 스캔 금지(예산현황
# 등 다른 확정모달과 클래스 겹침) — 이 팝업 고유 id 로만 판정한다(2026-07-21 프로브 실측).
NOTICE_POPUP_BOXES_JS = r"""() => {
  const chk = document.querySelector('#close-today-chk');
  const btn = document.querySelector('#notice-dialog-close');
  if (!chk || !btn) return null;
  const dlg = chk.closest('.k-window') || document.querySelector('#notice-list-dialog');
  if (dlg && dlg.offsetParent === null) return null;  // 닫힌 뒤 DOM 잔존 대비
  const center = (el) => { const r = el.getBoundingClientRect();
    return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) }; };
  return { checkbox: center(chk), close: center(btn), checked: !!chk.checked };
}"""
