"""출장(해외/정산서) 결의서입력 — detail 그리드 셀 조작 JS 프리미티브 단일소스.

프로브(trip_probe*, 2026-07-06)로 확정한 셀렉터/조작만 담는다. 코드 셀 에디터 오픈·돋보기·
피커 검색/선택/적용은 nbkit(OPEN_DETAIL_CELL_EDITOR_JS·DETAIL_EDITOR_MAGNIFIER_JS·PICKER_*)를
그대로 재사용하므로 여기엔 **금액/적요 setValue 직접 세팅**과 **셀 재독(검증)** JS 만 둔다.
inert 상수(page.evaluate 인자로만 사용). ⚠ 저장(F7)은 steps 저장 게이트에서만.
"""

from __future__ import annotations

# detail 그리드(index 1) 마지막 행의 한 필드를 setValue 로 직접 세팅 + 표시값 재독.
# 공급가액(SPPRC_AMT)·적요(NOTE_DC)는 피커 없이 setValue 로 동작(프로브 P7 실측, 표시 '12,345').
# 인자 {field, value}. 반환 {ok, row, after, display} | {ok:false, reason}.
SET_DETAIL_CELL_JS = """({ field, value }) => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
    const n = g.getDataSource().getRowCount();
    if (n < 1) return { ok: false, reason: 'detail 행 없음' };
    const row = Math.max(0, n - 1);
    g.setValue(row, field, value);
    const disp = (g.getDisplayValuesOfRow ? g.getDisplayValuesOfRow(row) : {}) || {};
    return { ok: true, row, after: String(g.getValue(row, field)), display: String(disp[field] != null ? disp[field] : '') };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 120) }; }
}"""

# detail 그리드(index 1) 마지막 행의 지정 필드들 원시값 재독 — 코드피커 적용/금액 세팅 후
# 셀 반영 검증용(적용 판정은 모달 닫힘이 아니라 셀 반영으로). 인자 fields[]. 반환 {ok, row, values}.
READ_DETAIL_CELL_JS = """(fields) => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
    const n = g.getDataSource().getRowCount();
    if (n < 1) return { ok: false, reason: 'detail 행 없음' };
    const row = Math.max(0, n - 1);
    const values = {};
    for (const f of fields) { const v = g.getValue(row, f); values[f] = v == null ? '' : String(v); }
    return { ok: true, row, values };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 120) }; }
}"""

# detail 그리드(index 1) 마지막 행의 **날짜 셀**을 compact 'YYYYMMDD'(브라우저 로컬 Y/M/D)로 재독.
# ⚠ 날짜 셀 getValue 는 Date 객체를 반환한다 → String() 하면 'Tue Jul 07 2026 ...'(월이 영문·오프셋
#   포함)이라 숫자만 뽑는 검증이 오판한다(계산서일 반영 불일치 오류의 원인, 2026-07-07 실측). Date 는
#   getFullYear/Month/Date 로 직접 compact 화하고, 문자열/숫자면 숫자만 추려 앞 8자리를 쓴다.
#   인자 field(str). 반환 {ok, compact, raw} | {ok:false, reason}.
READ_DETAIL_DATE_JS = """(field) => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
    const n = g.getDataSource().getRowCount();
    if (n < 1) return { ok: false, reason: 'detail 행 없음' };
    const row = Math.max(0, n - 1);
    const v = g.getValue(row, field);
    let compact = '';
    if (v instanceof Date && !isNaN(v.getTime())) {
      const p = (x) => ('0' + x).slice(-2);
      compact = '' + v.getFullYear() + p(v.getMonth() + 1) + p(v.getDate());
    } else {
      compact = String(v == null ? '' : v).replace(/\\D/g, '').slice(0, 8);
    }
    return { ok: true, compact: compact, raw: String(v == null ? '' : v) };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 120) }; }
}"""

# ── 상대계정거래처 = detail 행 BFC_PARTNER_CD 직접 세팅(실측 2026-07-07) ──────────
# 하단 폼 위젯(코드피커)은 '적용'이 활성 detail 에디터에 반영돼 빈 행을 추가하는 함정 → 사용 금지.
# 대신 **detail dataSource 필드 BFC_PARTNER_CD 를 grid.setValue 로 직접 세팅**한다. 행 추가 없이
# 저장 전표에 상대계정거래처로 persist 됨을 실저장+재조회로 확인(2026-07-07). BFC_PARTNER_NM 은
# dataSource 필드가 아니라(Invalid field index) 세팅 불가·불필요(서버가 코드로 이름 파생).
# 인자 code(작성자 partner code). 반환 {ok, after, rc} | {ok:false, reason}.
SET_BFC_PARTNER_JS = """(code) => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
    const ds = g.getDataSource(); const n = ds.getRowCount();
    if (n < 1) return { ok: false, reason: 'detail 행 없음' };
    const row = Math.max(0, n - 1);
    g.setValue(row, 'BFC_PARTNER_CD', code);
    const j = ds.getJsonRows(row, row)[0] || {};
    return { ok: true, after: String(j.BFC_PARTNER_CD == null ? '' : j.BFC_PARTNER_CD), rc: ds.getRowCount() };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 120) }; }
}"""


# ── (미사용·이력 보존) 상대계정거래처 하단 폼 코드피커 위젯 ─────────────────────────
# 프로브(trip_counter_field, 2026-07-06): 행 채움 후 문서 하단(뷰포트 1000px 아래, Y~1113)에
# '상대계정거래처' 라벨 + 코드피커가 렌더된다. id 없음(input id='undefined_text', 버튼 wrapper
# 없음) → **라벨 기준 좌표 로케이트**. 뷰포트 아래라 클릭 전 스크롤 필수. 적용은 본 거래처
# (PARTNER)를 덮지 않고 상대계정 필드에만 반영된다(P8의 BFC_PARTNER 셀과 다른 실필드).

# '상대계정거래처' 라벨을 뷰포트 중앙으로 스크롤. 반환 true/false(라벨 존재).
COUNTER_SCROLL_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const lbl = [...document.querySelectorAll('label,span,div,td')].find(e => e.offsetParent!==null && c(e.innerText)==='상대계정거래처');
  if (!lbl) return false;
  lbl.scrollIntoView({ block: 'center' });
  return true;
}"""

# '상대계정거래처' 라벨 같은 행 오른쪽 코드피커 버튼 중심좌표(스크롤 후 호출). {x,y} | null.
COUNTER_PICKER_BOX_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const lbl = [...document.querySelectorAll('label,span,div,td')].find(e => e.offsetParent!==null && c(e.innerText)==='상대계정거래처');
  if (!lbl) return null;
  const lr = lbl.getBoundingClientRect();
  const btns = [...document.querySelectorAll('button.dews-codepicker-button')].filter(b=>b.offsetParent!==null);
  let best=null, bd=1e9;
  for (const b of btns){ const r=b.getBoundingClientRect(); if (Math.abs(r.top-lr.top)<18 && r.left>lr.left){ const dx=r.left-lr.left; if(dx<bd){bd=dx;best=b;} } }
  if(!best) return null;
  const r=best.getBoundingClientRect();
  return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2) };
}"""

# 상대계정거래처 입력값 재독(같은 행 오른쪽 text input 값들) — 적용 반영 검증용. 반환 string[].
COUNTER_INPUT_VAL_JS = """() => {
  const c = s => String(s==null?'':s).replace(/\\s+/g,' ').trim();
  const lbl = [...document.querySelectorAll('label,span,div,td')].find(e => e.offsetParent!==null && c(e.innerText)==='상대계정거래처');
  if (!lbl) return [];
  const lr = lbl.getBoundingClientRect();
  return [...document.querySelectorAll('input')].filter(i=>i.offsetParent!==null && Math.abs(i.getBoundingClientRect().top-lr.top)<18 && i.getBoundingClientRect().left>lr.left).map(i=>c(i.value)).filter(Boolean);
}"""

# detail 그리드를 뷰포트로 되돌림 — 상대계정 스크롤 후 다음 행 detail(캔버스 돋보기) 조작 복구.
RESET_SCROLL_TO_DETAIL_JS = """() => {
  const g = document.querySelectorAll('.dews-ui-grid')[1];
  if (g) g.scrollIntoView({ block: 'center' });
  return !!g;
}"""


# 마스터(결의서, grid 0) 상세합계금액(DETAIL_SUM_AMT) 직접 세팅 + 재독 검증. 인자 total(int).
# ⚠ setValue 는 ERP 합계 재계산 핸들러를 발화하지 않아, 행별 금액 setValue 후에도 마스터 합계가
#   stale(마지막 F3 이전 행들만 반영 → 마지막 detail 행 누락, 실측 2026-07-07). 전 행 채운 뒤
#   총액을 마스터에 직접 세팅해 저장값을 정합시킨다. 반환 {ok, after} | {ok:false, reason}.
SET_MASTER_TOTAL_JS = """(total) => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[0]).data('dewsControl')._grid;
    const ds = g.getDataSource();
    if (ds.getRowCount() < 1) return { ok: false, reason: '마스터 행 없음' };
    ds.setValue(0, 'DETAIL_SUM_AMT', total);
    return { ok: true, after: String(g.getValue(0, 'DETAIL_SUM_AMT')) };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 120) }; }
}"""

# detail 그리드(index 1) 마스터 합계/문서금액 자동계산 확인 — SPPRC_AMT 세팅 후 TOTAL_AMT/
# ABDOCU_AMT 가 파생되는지(저장 전) 관찰용. 마스터(0) + detail 마지막 행 금액 컬럼을 함께 읽는다.
READ_AMOUNT_FIELDS_JS = """() => {
  const out = { ok: true };
  try {
    const md = window.jQuery(document.querySelectorAll('.dews-ui-grid')[0]).data('dewsControl')._grid;
    const mds = md.getDataSource();
    if (mds.getRowCount() > 0) {
      const m = {};
      for (const f of ['ABDOCU_AMT', 'TOTAL_AMT', 'SPPRC_AMT']) { const v = md.getValue(0, f); if (v != null) m[f] = String(v); }
      out.master = m;
    }
  } catch (e) { out.master_err = String(e).slice(0, 80); }
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[1]).data('dewsControl')._grid;
    const n = g.getDataSource().getRowCount();
    const row = Math.max(0, n - 1);
    const d = {};
    for (const f of ['SPPRC_AMT', 'SPPRC_AMT2', 'TOTAL_AMT', 'ABDOCU_AMT', 'VAT_AMT']) {
      const v = g.getValue(row, f); if (v != null) d[f] = String(v);
    }
    out.detail = d; out.detail_rows = n;
  } catch (e) { out.detail_err = String(e).slice(0, 80); }
  return out;
}"""
