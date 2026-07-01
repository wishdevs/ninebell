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
OPEN_EVDN_EDITOR_JS = """() => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
    g.setCurrent({ itemIndex: 0, fieldName: 'EVDN_TP_NM' });
    g.showEditor();
    return true;
  } catch (e) { return false; }
}"""

# showEditor 로 뜬 DOM 에디터 input 의 돋보기 클릭 좌표(input 오른쪽 +8px, 검증된 오프셋).
EVDN_EDITOR_MAGNIFIER_RECT_JS = """() => {
  const inp = [...document.querySelectorAll('input')].find(i => /gridDetail_line/.test(i.id || '') && i.offsetParent !== null);
  if (!inp) return null;
  const r = inp.getBoundingClientRect();
  return { x: r.right + 8, y: r.top + r.height / 2 };
}"""

# 증빙유형 팝업(.k-window.dialog)이 떴는지.
EVDN_POPUP_OPEN_JS = (
    "() => [...document.querySelectorAll('.k-window.dialog')].some(d => d.offsetParent !== null)"
)

# 팝업 그리드에서 지정 코드들의 옵션(코드+이름) 읽기. arg = codes[]. 반환 {ok, options?}.
EVDN_OPTIONS_JS = """(codes) => {
  try {
    const dlg = [...document.querySelectorAll('.k-window.dialog')].find(d => d.offsetParent !== null);
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
    const dlg = [...document.querySelectorAll('.k-window.dialog')].find(d => d.offsetParent !== null);
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
    const dlg = [...document.querySelectorAll('.k-window.dialog')].find(d => d.offsetParent !== null);
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
  const dlg = [...document.querySelectorAll('.k-window.dialog')].find(d => d.offsetParent !== null);
  if (!dlg) return null;
  const btn = [...dlg.querySelectorAll('button')].find(b => (b.innerText || '').trim() === '적용');
  if (!btn) return null;
  const r = btn.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# 디테일 그리드 0행 증빙 셀 값 — '적용' 반영 판정(모달 닫힘 대신 셀 반영으로).
DETAIL_EVDN_CELL_JS = """() => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
    const row = g.getDataSource().getJsonRows(0, 0)[0];
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
