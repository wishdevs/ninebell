"""미지급금 법인카드(voucher-card) 고유 in-page JS 상수 — 프로브 이식.

카드는 공유 백본(전표조회승인 GLDDOC00700 조회+결재)을 재사용하고, 아래 3대 확장만 고유하다:
  Phase B  결의서조회승인(GLDDOC00400) **다중 메뉴 탭** — 결의구분=카드 일괄 조회 →
           ABDOCU_NO→GWDOCU_NO(결재번호) 맵 수집.
  Phase C  결제창(EAP React 앱, dews 아님) 안 **참조문서 선택** sub-flow.

셀렉터/JS 는 e2e/voucher_card_discover_probe.py + e2e/voucher_card_refdoc_verify_probe.py
(2026-07-21 프로브 확정)에서 그대로 이식했다. 범용 JS(드롭다운 세팅=KENDO_SET_DROPDOWN_BY_TEXT_JS)
는 nbkit.omnisol.js_lib 를, 공유 위젯 JS(피커 checkAll/적용·마스터그리드 등)는
app.agents.voucher_receivable.js 를 재사용한다.

⚠ 절대 안전: 참조문서 '확인'·결제창 '상신'을 클릭하는 JS 는 이 파일에 없다. REFDOC_CONFIRM_BTN_JS
   는 **좌표만 반환**하며(게이트 뒤에서만 사용), REFDOC_DOWN_BTN 은 선택목록 이동(비영속)이다.
"""

from __future__ import annotations

# ══════════════════════════════════════════════════════════════════════════════
# Phase B — 결의서조회승인(GLDDOC00400) 다중 메뉴 탭 + 조회폼
# ══════════════════════════════════════════════════════════════════════════════

# 사이드바 결의서조회승인 진입 링크(클릭 시 상단에 새 탭 생성 + 페이지 캐시).
NAV_LINK_SELECTOR = 'a.nav-text[href="/FI/GLDDOC00400"]'

# 전표조회승인 탭으로 복귀(캐시된 첫 탭). Playwright text 셀렉터.
TAB_BACK_VOUCHER_SELECTOR = 'li.tab-item:has-text("전표조회승인")'

# 결의자(#WRT_EMP_NO_C) dews multicodepicker 기본선택 비우기(clear) — 로그인 계정 소속으로
# 결과가 좁혀지지 않도록. 반환 bool.
CLEAR_WRT_EMP_JS = (
    "() => { try { window.jQuery(document.querySelector('#WRT_EMP_NO_C'))"
    ".data('dewsControl').clear(); return true; } catch (e) { return false; } }"
)

# 회계일(#PERIOD_DT_C) periodpicker 당월(1일~말일) 세팅(setMonth). ⚠ 프로브 확정 경로는 이
# 필드를 건드리지 않고 폼 기본값(당월)에 의존했다 — 이 JS 는 override(명시 당월/특정월) 시에만
# steps 에서 호출한다. 반환 bool.
SET_PERIOD_THIS_MONTH_JS = (
    "() => { try { window.jQuery(document.querySelector('#PERIOD_DT_C'))"
    ".data('dewsControl').setMonth(); return true; } catch (e) { return false; } }"
)

# 특정 월(YYYYMMDD start/end) 회계일 override — start/end 두 date input 에 직접 세팅.
# arg = {start:'YYYYMMDD', end:'YYYYMMDD'}. 반환 bool. (override 경로 — 미검증, best-effort.)
SET_PERIOD_RANGE_JS = r"""({ start, end }) => {
  try {
    const si = document.querySelector('#PERIOD_DT_C_startinput');
    const ei = document.querySelector('#PERIOD_DT_C_endinput');
    if (!si || !ei) return false;
    for (const [inp, val] of [[si, start], [ei, end]]) {
      inp.value = val;
      inp.dispatchEvent(new Event('input', { bubbles: true }));
      inp.dispatchEvent(new Event('change', { bubbles: true }));
    }
    return true;
  } catch (e) { return false; }
}"""

# 현재 **가시(offsetParent!==null)** 조회버튼 좌표 — 다중탭이라 조회버튼이 DOM에 여럿 존재하므로
# 반드시 가시로만 선택(활성 탭의 것). 반환 {x, y} 또는 null.
VISIBLE_LOOKUP_BTN_RECT_JS = r"""() => {
  const btns = [...document.querySelectorAll('button.main-button.lookup')].filter(b => b.offsetParent !== null);
  if (!btns.length) return null;
  const r = btns[0].getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# 현재 가시 마스터 그리드(활성 탭의 grid[0]) 전량 덤프 — ABDOCU_NO→GWDOCU_NO 맵 수집용.
# 다중탭이라 .dews-ui-grid 가 탭별로 여럿 → 가시로만 필터. 반환 {ok, n, rows:[{ABDOCU_NO,GWDOCU_NO,...}]}.
VISIBLE_MASTER_ROWS_JS = r"""(limit) => {
  try {
    const grids = [...document.querySelectorAll('.dews-ui-grid')].filter(el => el.offsetParent !== null);
    if (!grids.length) return { ok: false, reason: 'no-visible-grid' };
    const ctrl = window.jQuery(grids[0]).data('dewsControl');
    const g = ctrl && ctrl._grid;
    if (!g) return { ok: false, reason: 'grid-not-ready' };
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const take = Math.min(n, limit || 500);
    const rows = take > 0 ? ds.getJsonRows(0, take - 1) : [];
    return { ok: true, n, rows };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 140) }; }
}"""


# ══════════════════════════════════════════════════════════════════════════════
# Phase C — 결제창(EAP React) 안 참조문서 선택 sub-flow
# ⚠ '확인'/'상신' 클릭 JS 없음 — 좌표만(게이트 뒤).
# ══════════════════════════════════════════════════════════════════════════════

# '참조문서 선택' 버튼: DOM 텍스트가 '참 조 문 서'(글자사이 공백)라 정확 매치가 안 된다 —
# 버튼의 조상 행(row) 텍스트에서 공백 제거 후 '참조문서' 포함 여부로 찾는다(프로브 확정).
# 뷰포트 밖(y≈1635)일 수 있어 먼저 scrollIntoView 한 뒤 좌표를 재계산해야 한다.
REFDOC_SELECT_BTN_SCROLL_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const b = [...document.querySelectorAll('button')].find(b => {
    const row = b.closest('tr') || b.closest('li') || (b.parentElement && b.parentElement.parentElement);
    return row && c(row.innerText).replace(/\s+/g,'').includes('참조문서');
  });
  if (b) { b.scrollIntoView({ block: 'center' }); return true; }
  return false;
}"""

REFDOC_SELECT_BTN_RECT_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const b = [...document.querySelectorAll('button')].find(b => {
    const row = b.closest('tr') || b.closest('li') || (b.parentElement && b.parentElement.parentElement);
    return row && c(row.innerText).replace(/\s+/g,'').includes('참조문서');
  });
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# 참조문서 dialog 필터 확장 토글(접힘→확장). 확장하면 문서번호·조회 버튼이 노출된다.
REFDOC_FILTER_EXPAND_SELECTOR = "#tutorial-conditionPanel-collapse"

# 문서번호 입력란 좌표(라벨 '문서번호'의 행에서 input). 반환 {x, y} 또는 null.
# ⚠ dialog 스코프 필수(2026-07-27 실측): 전역 라벨 탐색은 dialog 밖 요소를 잡아
#   문서번호 입력·readback 이 산발적으로 실패했다(filled=False).
REFDOC_DOCNO_INPUT_RECT_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const heading = [...document.querySelectorAll('*')].find(
    el => el.children.length === 0 && c(el.innerText) === '참조문서');
  let dlg = heading;
  for (let i = 0; i < 8 && dlg; i++) {
    const r = dlg.getBoundingClientRect();
    if (r.width > 400 && r.height > 300) break;
    dlg = dlg.parentElement;
  }
  if (!dlg) return null;
  const lbl = [...dlg.querySelectorAll('*')].find(
    el => el.children.length === 0 && c(el.innerText) === '문서번호');
  if (!lbl) return null;
  const lr = lbl.getBoundingClientRect();
  const inp = [...dlg.querySelectorAll('input')]
    .filter(i => i.offsetParent !== null && i.getBoundingClientRect().width > 40)
    .filter(i => { const r = i.getBoundingClientRect();
                   return Math.abs(r.top - lr.top) < 24 && r.x >= lr.x; })
    .sort((a, b) => a.getBoundingClientRect().x - b.getBoundingClientRect().x)[0];
  if (!inp) return null;
  const r = inp.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# ⚠ dialog 스코프 필수(2026-07-27 실측): 전역 라벨 탐색은 dialog 밖 요소를 잡아
#   문서번호 입력·readback 이 산발적으로 실패했다(filled=False).
REFDOC_DOCNO_VALUE_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const heading = [...document.querySelectorAll('*')].find(
    el => el.children.length === 0 && c(el.innerText) === '참조문서');
  let dlg = heading;
  for (let i = 0; i < 8 && dlg; i++) {
    const r = dlg.getBoundingClientRect();
    if (r.width > 400 && r.height > 300) break;
    dlg = dlg.parentElement;
  }
  if (!dlg) return null;
  const lbl = [...dlg.querySelectorAll('*')].find(
    el => el.children.length === 0 && c(el.innerText) === '문서번호');
  if (!lbl) return null;
  const lr = lbl.getBoundingClientRect();
  const inp = [...dlg.querySelectorAll('input')]
    .filter(i => i.offsetParent !== null && i.getBoundingClientRect().width > 40)
    .filter(i => { const r = i.getBoundingClientRect();
                   return Math.abs(r.top - lr.top) < 24 && r.x >= lr.x; })
    .sort((a, b) => a.getBoundingClientRect().x - b.getBoundingClientRect().x)[0];
  return inp ? inp.value : null;
}"""

REFDOC_SEARCH_BTN_RECT_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const b = [...document.querySelectorAll('button')].find(b => {
    if (c(b.innerText) !== '조회' || b.disabled) return false;
    if (b.offsetParent === null) return false;
    const r = b.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  });
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# 조회 결과 참조문서 목록에서 문서번호 매치 + '조회된 데이터가 없습니다' 감지(조건 폴링용).
# 반환 {docNoMatches:[...], noDataText}. 매치 포맷: '(주)나인벨-2026-12961' 류.
REFDOC_MATCHES_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const re = /\(주\)나인벨-\d{4}-\d+/;
  const matches = new Set();
  let noDataText = null;
  for (const el of document.querySelectorAll('*')) {
    if (el.children.length > 0) continue;
    const t = c(el.innerText || el.textContent || '');
    if (!t) continue;
    const m = t.match(re);
    if (m) matches.add(m[0]);
    if (t.includes('조회된 데이터가 없습니다')) noDataText = t;
  }
  return { docNoMatches: [...matches], noDataText };
}"""

# 참조문서목록(상단 OBTListGrid)에서 문서번호(gwdocuNo)를 포함한 행을 클릭 → 선택.
# arg = gwdocuNo. 반환 bool(클릭 성공). ⚠ 목록 행 선택은 비영속(확인 전까지).
REFDOC_SELECT_ROW_JS = r"""(gwdocuNo) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const needle = c(gwdocuNo);
  if (!needle) return false;
  const rows = [...document.querySelectorAll('[class*=row], [class*=Row], tr')]
    .filter(r => r.offsetParent !== null && c(r.innerText).includes(needle));
  if (!rows.length) return false;
  rows[0].click();
  return true;
}"""

# 참조문서목록 → 선택된문서목록 이동 '아래(↓)' 버튼 좌표(프로브 확정 x≈477, y≈412).
# 두 그리드 사이 방향버튼 — 아이콘 전용이라 좌표/방향(down)으로 찾는다. 반환 {x, y} 또는 null.
# ⚠ 비영속(확인 전까지) — '선택된 문서 목록'으로 옮기기만 한다.
REFDOC_DOWN_BTN_FALLBACK = {"x": 477, "y": 412}
REFDOC_DOWN_BTN_RECT_JS = r"""() => {
  // 아래방향 아이콘 버튼 후보 — down/arrow/moveDown 류 클래스/aria. 없으면 null(폴백 좌표 사용).
  const cand = [...document.querySelectorAll('button, [role=button], a')].find(el => {
    if (el.offsetParent === null) return false;
    const s = ((el.className||'').toString() + ' ' + (el.getAttribute('aria-label')||'') + ' ' + (el.title||'')).toLowerCase();
    return /down|아래|movedown|arrow-?down/.test(s);
  });
  if (!cand) return null;
  const r = cand.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# ⚠ 게이트 전용 — '확인'(파란 OBTButton) 좌표. **반환만** 하며 이 파일/steps 어디서도
#   allow_confirm 게이트 밖에서는 클릭하지 않는다(절대 안전). 반환 {x, y} 또는 null.
REFDOC_CONFIRM_BTN_RECT_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const b = [...document.querySelectorAll('button')].filter(b => b.offsetParent !== null)
    .find(b => c(b.innerText) === '확인');
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# 참조문서 dialog 닫기(X) 좌표 — 확인/선택 미클릭 상태로 dialog 만 취소한다(비영속 유지).
# dialog 컨테이너(제목 '참조문서')의 첫 버튼이 닫기(X)라는 프로브 확정. 반환 {x, y} 또는 null.
REFDOC_CLOSE_BTN_RECT_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const heading = [...document.querySelectorAll('*')].find(
    el => el.children.length === 0 && c(el.innerText) === '참조문서'
  );
  let dlg = heading;
  for (let i = 0; i < 8 && dlg; i++) {
    const r = dlg.getBoundingClientRect();
    if (r.width > 400 && r.height > 300) break;
    dlg = dlg.parentElement;
  }
  if (!dlg) return null;
  const btn = dlg.querySelector('button');
  if (!btn) return null;
  const r = btn.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# 현재 가시 마스터 그리드(활성 탭 grid[0])의 rowCount — 조회 실행 후 결과 반영 확인용.
# 다중탭이라 인덱스 기반 ROWCOUNT_BY_INDEX_JS 는 다른 탭 그리드를 읽을 수 있어 가시로만 고른다.
# 반환 int(>=0) 또는 -1(그리드 미부착/미로딩 — 확인 불가).
VISIBLE_MASTER_ROWCOUNT_JS = r"""() => {
  try {
    const grids = [...document.querySelectorAll('.dews-ui-grid')].filter(el => el.offsetParent !== null);
    if (!grids.length) return -1;
    const ctrl = window.jQuery(grids[0]).data('dewsControl');
    const g = ctrl && ctrl._grid;
    if (!g) return -1;
    return g.getDataSource().getRowCount();
  } catch (e) { return -1; }
}"""

# ══════════════════════════════════════════════════════════════════════════════
# 참조문서 dialog — **dialog 스코프** 리더/마커 (2026-07-27 정밀 실측으로 전면 교체)
#
# 실측으로 드러난 것(e2e/voucher_card_refdoc_dom_probe.py, 계정 석대현):
#   1. dialog 밖(기안문서)에도 '조회' 버튼이 있다 → 전역 스캔이 그걸 잡아 **화면 밖 좌표
#      (y=-429)** 를 클릭했다. 그래서 "어떤 건 조회가 되고 어떤 건 안 되는" 증상이 났다.
#      → 반드시 **dialog 안에서만** 찾고, 좌표가 아니라 **요소 클릭**으로 누른다(자동 스크롤·
#        actionability 대기가 붙어 위치 문제가 원천 제거된다).
#   2. 참조문서 목록/선택된 문서 목록은 **RealGrid 캔버스**다(window.RealGridJS 존재, 숨은
#      `input[id^=grid_]` + <canvas>). DOM 텍스트로 행을 읽는 건 **원리적으로 불가능** —
#      기존 `REFDOC_MATCHES_JS`(전역 텍스트 정규식)가 항상 0건이었던 진짜 이유다.
#      → 판정은 dialog 의 **DOM 텍스트 앵커**로 한다: '총 N개' / '조회된 데이터가 없습니다.' /
#        '선택된 목록이 없습니다.'
# ══════════════════════════════════════════════════════════════════════════════

# dialog 루트 탐색 + 대상 요소에 마커 속성을 붙인다(클릭은 Playwright 요소 클릭으로).
# arg = {kind: 'search'|'move', index?: int}. 반환 {ok, marked, count}.
REFDOC_MARK_JS = r"""({ kind, index }) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const heading = [...document.querySelectorAll('*')].find(
    el => el.children.length === 0 && c(el.innerText) === '참조문서');
  let dlg = heading;
  for (let i = 0; i < 8 && dlg; i++) {
    const r = dlg.getBoundingClientRect();
    if (r.width > 400 && r.height > 300) break;
    dlg = dlg.parentElement;
  }
  if (!dlg) return { ok: false, reason: 'no-dialog' };
  for (const el of dlg.querySelectorAll('[data-nb-refdoc]')) el.removeAttribute('data-nb-refdoc');
  const vis = b => b.offsetParent !== null && !b.disabled;
  if (kind === 'search') {
    // 아이콘(icon-btn-search) 우선, 없으면 텍스트 '조회'. **dialog 안에서만** 찾는다.
    const btns = [...dlg.querySelectorAll('button')].filter(vis);
    const b = btns.find(x => x.querySelector('img[src*="icon-btn-search"]'))
           || btns.find(x => c(x.innerText) === '조회');
    if (!b) return { ok: false, reason: 'no-search-button' };
    b.setAttribute('data-nb-refdoc', 'search');
    return { ok: true, marked: 'search' };
  }
  if (kind === 'docno') {
    // 문서번호 라벨과 같은 행의 오른쪽 최근접 input(= 필터 입력).
    const lbl = [...dlg.querySelectorAll('*')].find(
      el => el.children.length === 0 && c(el.innerText) === '문서번호');
    if (!lbl) return { ok: false, reason: 'no-docno-label' };
    const lr = lbl.getBoundingClientRect();
    const inp = [...dlg.querySelectorAll('input')]
      .filter(i => i.offsetParent !== null && i.getBoundingClientRect().width > 40)
      .filter(i => { const r = i.getBoundingClientRect();
                     return Math.abs(r.top - lr.top) < 24 && r.x >= lr.x; })
      .sort((a, b) => a.getBoundingClientRect().x - b.getBoundingClientRect().x)[0];
    if (!inp) return { ok: false, reason: 'no-docno-input' };
    inp.setAttribute('data-nb-refdoc', 'docno');
    return { ok: true, marked: 'docno' };
  }
  if (kind === 'move') {
    // 두 그리드 **사이**의 아이콘 버튼들(라벨 없음, 27×27) = 이동(↓/↑). y 로 구간을 좁힌다.
    const gridRoots = [...dlg.querySelectorAll('input[id^=grid_]')].map(h => {
      let root = h.parentElement;
      for (let i = 0; i < 6 && root; i++) {
        if (root.querySelector('canvas')) return root;
        root = root.parentElement;
      }
      return null;
    }).filter(Boolean).map(el => el.getBoundingClientRect()).sort((a, b) => a.y - b.y);
    if (gridRoots.length < 2) return { ok: false, reason: 'grids-not-found' };
    const gapTop = gridRoots[0].bottom, gapBottom = gridRoots[1].top;
    const cands = [...dlg.querySelectorAll('button')].filter(b => {
      if (!vis(b) || c(b.innerText)) return false;          // 라벨 있는 버튼(확인 등) 제외
      // 두 그리드 사이에는 **페이지네이션**(첫/이전/다음/마지막)도 함께 있다 — 실측에서 후보가
      // 7개 잡혀 첫 두 개(페이지 이동)를 눌렀고 당연히 아무것도 옮겨지지 않았다. 이동 버튼은
      // OBTButton, 페이지네이션은 OBTPagination 이라 클래스로 가른다.
      const cls = (b.className || '').toString();
      if (/OBTPagination/.test(cls) || b.closest('[class*=OBTPagination]')) return false;
      if (!/OBTButton_root/.test(cls)) return false;
      const r = b.getBoundingClientRect();
      return r.top >= gapTop && r.bottom <= gapBottom && r.width <= 40 && r.height <= 40;
    }).sort((a, b) => a.getBoundingClientRect().x - b.getBoundingClientRect().x);
    if (!cands.length) return { ok: false, reason: 'no-move-button' };
    const i = Math.min(Math.max(index || 0, 0), cands.length - 1);
    cands[i].setAttribute('data-nb-refdoc', 'move');
    return { ok: true, marked: 'move', count: cands.length, index: i };
  }
  return { ok: false, reason: 'unknown-kind' };
}"""

# dialog 상태 — 조회 결과 건수/없음 문구/선택된 목록 비어있음 + 두 그리드 박스(캔버스 클릭용).
# 반환 {ok, total, noData, selectedEmpty, topGrid, bottomGrid}. total=null 이면 건수 표기 미발견.
REFDOC_STATE_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const heading = [...document.querySelectorAll('*')].find(
    el => el.children.length === 0 && c(el.innerText) === '참조문서');
  let dlg = heading;
  for (let i = 0; i < 8 && dlg; i++) {
    const r = dlg.getBoundingClientRect();
    if (r.width > 400 && r.height > 300) break;
    dlg = dlg.parentElement;
  }
  if (!dlg) return { ok: false, reason: 'no-dialog' };
  const text = c(dlg.innerText);
  const m = text.match(/총\s*([\d,]+)\s*개/);
  const boxes = [...dlg.querySelectorAll('input[id^=grid_]')].map(h => {
    let root = h.parentElement;
    for (let i = 0; i < 6 && root; i++) {
      if (root.querySelector('canvas')) return root;
      root = root.parentElement;
    }
    return null;
  }).filter(Boolean).map(el => {
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
  }).sort((a, b) => a.y - b.y);
  return {
    ok: true,
    total: m ? parseInt(m[1].replace(/,/g, ''), 10) : null,
    noData: text.includes('조회된 데이터가 없습니다'),
    selectedEmpty: text.includes('선택된 목록이 없습니다'),
    topGrid: boxes[0] || null,
    bottomGrid: boxes[1] || null,
  };
}"""


# 참조문서 dialog 를 **뷰포트 안으로** 스크롤하고 최종 위치를 돌려준다.
# ⚠ 필수(2026-07-27 실측): 결제창은 참조문서 선택 버튼(y≈1635)까지 스크롤된 상태라, dialog 가
#   열려도 그 내용이 화면 위(음수 y: 조회 버튼 -429, 문서번호 input -504)에 있는 경우가 있다.
#   요소 클릭은 Playwright 가 자동 스크롤하지만, **캔버스 그리드 행 클릭은 좌표**라 이 정렬이
#   선행되지 않으면 허공을 누른다. 반환 {ok, box} — box.y >= 0 이어야 좌표 조작이 성립한다.
REFDOC_SCROLL_INTO_VIEW_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const heading = [...document.querySelectorAll('*')].find(
    el => el.children.length === 0 && c(el.innerText) === '참조문서');
  let dlg = heading;
  for (let i = 0; i < 8 && dlg; i++) {
    const r = dlg.getBoundingClientRect();
    if (r.width > 400 && r.height > 300) break;
    dlg = dlg.parentElement;
  }
  if (!dlg) return { ok: false, reason: 'no-dialog' };
  dlg.scrollIntoView({ block: 'center', inline: 'center' });
  const r = dlg.getBoundingClientRect();
  return { ok: true, box: { x: Math.round(r.x), y: Math.round(r.y),
                            w: Math.round(r.width), h: Math.round(r.height) } };
}"""

# 참조문서 dialog 의 두 그리드를 **gridView 인스턴스**로 직접 읽는다(행 수 + 문서번호).
# ⚠ 발견 경위(2026-07-27, 사용자 지적): 그리드가 캔버스라 DOM 으로는 못 읽지만, 캔버스 컨테이너의
#   **부모 요소**(id="grid_<uuid>")에 RealGrid `gridView` 인스턴스가 붙어 있다. 앞선 조사가
#   컨테이너 자신의 own-property 만 봐서 놓쳤다(부모를 봐야 한다).
#   이제 '선택된 목록이 없습니다.' 문구 같은 간접 신호가 아니라 **행 수와 문서번호를 실제로**
#   확인할 수 있다 — 첨부 성공 판정의 근거가 정확해진다.
# 반환 {ok, top:{count, docNos}, selected:{count, docNos}} | {ok:false, reason}.
REFDOC_GRID_ROWS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const heading = [...document.querySelectorAll('*')].find(
    el => el.children.length === 0 && c(el.innerText) === '참조문서');
  let dlg = heading;
  for (let i = 0; i < 8 && dlg; i++) {
    const r = dlg.getBoundingClientRect();
    if (r.width > 400 && r.height > 300) break;
    dlg = dlg.parentElement;
  }
  if (!dlg) return { ok: false, reason: 'no-dialog' };
  const views = [];
  for (const el of dlg.querySelectorAll('[id^=grid_]')) {
    const gv = el.gridView;
    if (!gv || typeof gv.getDataSource !== 'function') continue;
    const rec = { y: Math.round(el.getBoundingClientRect().y), count: null, docNos: [] };
    try {
      const ds = gv.getDataSource();
      rec.count = ds.getRowCount();
      if (rec.count > 0) {
        const rows = ds.getJsonRows(0, Math.min(rec.count, 200) - 1);
        rec.docNos = rows.map(r => c(r.doc_no)).filter(Boolean);
      }
    } catch (e) { rec.err = String(e).slice(0, 80); }
    views.push(rec);
  }
  if (views.length < 2) return { ok: false, reason: 'grids-not-ready', found: views.length };
  views.sort((a, b) => a.y - b.y);
  return { ok: true, top: views[0], selected: views[1] };
}"""
