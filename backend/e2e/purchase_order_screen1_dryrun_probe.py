"""HEADLESS 쓰기 경로 드라이런 — 화면① 프로젝트BOM구매요청[나인벨] 저장 직전까지.

omnisol-flow-prober 위임(2026-08-25, 사용자 지시 "저장버튼을 제외하고 진행"). 목적은 조작
메커니즘 확정이며 **데이터는 하나도 만들지 않는다** — 저장(F7/.main-button.save)은 좌표만
기록하고 절대 클릭하지 않는다.

기존 프리미티브 재사용:
  - `app.agents.purchase_order.steps`: apply_project/ensure_fixed_header/set_checkbox/
    click_lookup/wait_bom_loaded/read_bom_signature
  - `app.agents.purchase_order.js`: CHECKBOX_RECT_JS/LOOKUP_BTN_JS/HEADER_STATE_JS/
    SET_INPUT_JS/TREEGRID_COUNT_JS/TREEGRID_MV_SIG_JS
  - `nbkit.omnisol.js_lib`: PICKER_* (검색/읽기/선택/적용/닫힘), FIELD_DISPLAY_JS
  - `nbkit.omnisol.codepicker`: _wait_picker_rows_stable/_wait_picker_closed/_picker_search
  - `e2e/purchase_order_screen23_dump_probe.py` 의 DOM 덤프 JS 패턴(라벨필드/코드피커
    wrapper/툴바아이콘/적용버튼행)과 **document 스코프 피커 오픈**(공장 필드 선례) — 그대로
    복사해 이 화면에 맞게 재사용(각주에 출처 표기).
  - `e2e/purchase_order_2285_probe.py` 의 CONFIRM_DIALOG_JS/CONFIRM_BTN_BOX_JS(다이얼로그
    스캐너) — 재조회 시 '초기화' 다이얼로그 가설 검증에 그대로 사용.

⛔⛔ 절대 금지 ⛔⛔
  - 저장(F7, `button.main-button.save` = `nbkit.omnisol.selectors.BTN_SAVE`) 클릭 금지.
    좌표/셀렉터만 기록한다.
  - `저장하시겠습니까?` 다이얼로그가 뜨면 반드시 [아니요].
  - 종료 시 미저장 변경이 남아 있으면 화면 이탈/재조회에서 뜨는 확인 다이얼로그도 [아니요]로 버린다.
  - 그리드 셀 값 주입에 `setValue` 우회 금지 — 실클릭/실타이핑만.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/purchase_order_screen1_dryrun_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import Page, async_playwright  # noqa: E402

from app.agents.purchase_order import js as po_js  # noqa: E402
from app.agents.purchase_order import steps as po_steps  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT, _ScaledPage  # noqa: E402
from nbkit.omnisol import codepicker, js_lib  # noqa: E402
from nbkit.omnisol import selectors as om_selectors  # noqa: E402
from nbkit.omnisol.errors import MenuError  # noqa: E402
from nbkit.omnisol.navigator import navigate_menu  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
# 헤디드 관찰용 — 각 액션 사이 지연(ms). 0 이면 전속력(기본, 헤드리스와 동일).
SLOW_MO = int(os.environ.get("E2E_SLOW_MO", "0"))
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

DEEPLINK = "/PU/PUOPRQ00200_X20616"
MENU_LABEL = "프로젝트BOM구매요청[나인벨]"
KEYWORD = "GY03-019"
PJT_NO = "2285"
DUE_DATE = "2026-12-31"
PURCHASE_REASON = "GY03-019, 12CH-L3 DRYRUN"


# ══════════════════════════════════════════════════════════════════════════
# JS — 이 화면 전용(재사용 출처는 각 상수 주석에 표기)
# ══════════════════════════════════════════════════════════════════════════

# purchase_order_2285_probe.py 의 CONFIRM_DIALOG_JS/CONFIRM_BTN_BOX_JS 그대로.
CONFIRM_DIALOG_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window, .k-dialog, [role=alertdialog]')].filter(w => w.offsetParent !== null);
  return wins.map(w => {
    const title = c((w.querySelector('.k-window-title')||{}).innerText);
    const text = c(w.innerText).slice(0, 200);
    const buttons = [...w.querySelectorAll('button')].filter(b => b.offsetParent !== null).map(b => c(b.innerText));
    const r = w.getBoundingClientRect();
    return { title, text, buttons, rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) } };
  });
}"""

CONFIRM_BTN_BOX_JS = r"""(btnText) => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const wins = [...document.querySelectorAll('.k-window, .k-dialog')].filter(w => w.offsetParent !== null);
  for (const w of wins) {
    const b = [...w.querySelectorAll('button')].find(x => x.offsetParent !== null && c(x.innerText) === btnText);
    if (b) { const r = b.getBoundingClientRect(); return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2) }; }
  }
  return null;
}"""

# purchase_order_screen23_dump_probe.py 의 DUMP_LABELED_FIELDS_JS 그대로(라벨→li→위젯 종류 판별).
DUMP_LABELED_FIELDS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const out = [];
  const labels = [...document.querySelectorAll('label')].filter(l => l.offsetParent !== null);
  for (const lbl of labels) {
    const text = c(lbl.innerText);
    if (!text) continue;
    const li = lbl.closest('li') || lbl.closest('div') || lbl.closest('td') || lbl.parentElement;
    if (!li) continue;
    const wrapper = li.querySelector('[id$="-wrapper"]');
    const codepickerText = li.querySelector('.dews-multicodepicker-text, .dews-codepicker-text');
    const checkbox = li.querySelector('input[type=checkbox]');
    const select = li.querySelector('select');
    const anyInput = li.querySelector('input');
    out.push({
      label: text,
      liClassName: (li.className || '').toString().slice(0, 150),
      wrapperId: wrapper ? wrapper.id : null,
      hasCodepickerText: !!codepickerText,
      codepickerValue: codepickerText ? codepickerText.value : null,
      hasCheckbox: !!checkbox,
      hasSelect: !!select,
      selectValue: select ? (select.options[select.selectedIndex] || {}).text : null,
      anyInputId: anyInput ? anyInput.id : null,
      anyInputValue: anyInput ? anyInput.value : null,
      anyInputReadonly: anyInput ? anyInput.readOnly : null,
      liHtmlSnippet: li.outerHTML.replace(/\s+/g, ' ').slice(0, 500),
    });
  }
  return out;
}"""

# screen23 DUMP_CODEPICKER_FIELDS_JS 그대로 — wrapper id 로 field_id 역산.
DUMP_CODEPICKER_FIELDS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const wrappers = [...document.querySelectorAll('[id$="-wrapper"]')].filter(e => e.offsetParent !== null);
  return wrappers.map(w => {
    const li = w.closest('li') || w.closest('div') || w.closest('td');
    const lbl = li ? li.querySelector('label') : null;
    return {
      wrapperId: w.id,
      fieldId: w.id.replace(/-wrapper$/, ''),
      label: lbl ? c(lbl.innerText) : null,
      hasBtn: !!w.querySelector('.dews-codepicker-button'),
    };
  });
}"""

# screen23 DUMP_TOOLBAR_ICON_JS 그대로.
DUMP_TOOLBAR_ICON_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const seen = new Set();
  const out = [];
  const els = [...document.querySelectorAll('button, [title], [aria-label]')].filter(e => e.offsetParent !== null);
  for (const e of els) {
    if (seen.has(e)) continue;
    seen.add(e);
    const r = e.getBoundingClientRect();
    out.push({
      tag: e.tagName, id: e.id || '', cls: (e.className || '').toString().slice(0, 150),
      text: c(e.innerText).slice(0, 30), title: e.getAttribute('title') || '',
      aria: e.getAttribute('aria-label') || '', disabled: !!e.disabled,
      rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
    });
  }
  return out;
}"""

# screen23 DUMP_APPLY_ROWS_JS 그대로 — 필터행 6종([적용]버튼) 위치 파악.
DUMP_APPLY_ROWS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const btns = [...document.querySelectorAll('button')].filter(b => b.offsetParent !== null && c(b.innerText) === '적용');
  return btns.map(b => {
    const row = b.closest('tr') || b.closest('li') || b.closest('div');
    const r = b.getBoundingClientRect();
    return {
      rowText: row ? c(row.innerText).slice(0, 150) : '',
      btnId: b.id || '', btnCls: (b.className || '').toString().slice(0, 120),
      btnRect: { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) },
    };
  });
}"""

# 신규(이 화면 고유) — 트리그리드 체크 메커니즘 전량 정찰: getColumns, check* 메서드 목록,
# DOM 자식 구조(캔버스 컨테이너 rect), getCellRect/rowHeight/checkBar 시도, 현재 체크수.
TREEGRID_INTROSPECT_JS = r"""() => {
  try {
    const el = document.querySelector('.dews-ui-treegrid');
    if (!el) return { ok: false, reason: 'no-treegrid' };
    const g = window.jQuery(el).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const cols = g.getColumns().map(c => ({
      fieldName: c.fieldName, header: c.header, visible: c.visible,
      width: c.width, editable: !!c.editable,
    }));
    const collectNames = (obj, re) => {
      const out = new Set();
      let p = obj;
      while (p) { Object.getOwnPropertyNames(p).forEach(n => { if (re.test(n)) out.add(n); }); p = Object.getPrototypeOf(p); }
      return [...out];
    };
    const gridCheckMethods = collectNames(g, /check/i);
    const dsCheckMethods = collectNames(ds, /check/i);
    const rect = el.getBoundingClientRect();
    const childEls = [...el.querySelectorAll('*')].slice(0, 60).map(ch => {
      const r = ch.getBoundingClientRect();
      return { tag: ch.tagName, cls: (ch.className || '').toString().slice(0, 100), rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) } };
    });
    let cellRectTry = null;
    try { cellRectTry = typeof g.getCellRect === 'function' ? g.getCellRect(1, cols[0].fieldName) : 'no-fn'; } catch (e) { cellRectTry = 'err:' + String(e).slice(0, 100); }
    let rowHeightTry = null;
    try { rowHeightTry = typeof g.getRowHeight === 'function' ? g.getRowHeight(1) : (g.rowHeight != null ? g.rowHeight : 'no-prop'); } catch (e) { rowHeightTry = 'err:' + String(e).slice(0, 100); }
    let checkBarTry = null;
    try { checkBarTry = g.checkBar ? JSON.parse(JSON.stringify(g.checkBar)) : (typeof g.getCheckBar === 'function' ? JSON.parse(JSON.stringify(g.getCheckBar())) : 'no-checkbar'); } catch (e) { checkBarTry = 'err:' + String(e).slice(0, 100); }
    let checkedItemsSample = null;
    // ⚠ getCheckedItems 는 grid(g) 메서드다 — ds 엔 없다(1차 정찰 실측: 'ds.getCheckedItems
    // is not a function'). PROCESS.md BOM 실측 기록의 표기(getCheckedItems())가 grid 기준.
    try { checkedItemsSample = g.getCheckedItems(); } catch (e) { checkedItemsSample = 'err:' + String(e).slice(0, 100); }
    const collectBroad = collectNames(g, /row|index|visible|expand|scroll|point|hit/i);
    return {
      ok: true, count: ds.getRowCount(),
      gridRect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) },
      columns: cols, gridCheckMethods, dsCheckMethods, gridBroadMethods: collectBroad,
      childEls, cellRectTry, rowHeightTry, checkBarTry, checkedItemsSample,
    };
  } catch (e) { return { ok: false, err: String(e).slice(0, 300) }; }
}"""

# 신규 — 임의 체크 메서드 호출 + 전/후 체크수 비교. arg=[methodName, args].
# ⚠ 체크 API 는 **grid(g) 소유**다 — ds 엔 checkParentProc/checkRowStates 뿐(1차 정찰 실측).
#   전/후 카운트는 **g.getCheckedRows()(행 공간)** 로 읽는다 — 리더(ds)와 같은 공간이라야 한다.
TRY_CHECK_METHOD_JS = r"""([methodName, args]) => {
  try {
    const el = document.querySelector('.dews-ui-treegrid');
    const g = window.jQuery(el).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const checkedLen = () => { try { return (g.getCheckedRows() || []).length; } catch (e) { return -1; } };
    let target = null, owner = null;
    if (typeof g[methodName] === 'function') { target = g; owner = 'grid'; }
    else if (typeof ds[methodName] === 'function') { target = ds; owner = 'ds'; }
    else return { ok: false, reason: 'no-such-method' };
    const before = checkedLen();
    const ret = target[methodName].apply(target, args || []);
    const after = checkedLen();
    return { ok: true, owner, before, after, ret: ret === undefined ? null : String(ret).slice(0, 60) };
  } catch (e) { return { ok: false, err: String(e).slice(0, 200) }; }
}"""


# 신규 — 앱 핸들러 발화 계측: onItemChecked/onItemsChecked/onItemAllChecked 를 감싸 호출수를 센다.
# API 체크(checkAll/checkItem)가 실클릭과 같은 이벤트를 발화하는지 판정하는 근거.
INSTALL_CHECK_SPY_JS = r"""() => {
  try {
    const el = document.querySelector('.dews-ui-treegrid');
    const g = window.jQuery(el).data('dewsControl')._grid;
    if (window.__checkSpy) return { ok: true, already: true };
    const spy = { onItemChecked: 0, onItemsChecked: 0, onItemAllChecked: 0 };
    for (const name of ['onItemChecked', 'onItemsChecked', 'onItemAllChecked']) {
      const orig = g[name];
      g[name] = function (...a) {
        spy[name] += 1;
        if (typeof orig === 'function') { try { return orig.apply(this, a); } catch (e) {} }
        return undefined;
      };
    }
    window.__checkSpy = spy;
    return { ok: true, installed: Object.keys(spy) };
  } catch (e) { return { ok: false, err: String(e).slice(0, 200) }; }
}"""

READ_CHECK_SPY_JS = r"""(reset) => {
  const s = window.__checkSpy || null;
  if (!s) return null;
  const snap = { ...s };
  if (reset) { for (const k of Object.keys(s)) s[k] = 0; }
  return snap;
}"""


# 신규 — 지정 행들의 컬럼 값 스냅샷(적용 전/후 diff 로 '어느 fieldName 에 값이 꽂히는지' 특정).
# arg=[itemIndexes, fieldNames]. fieldNames 가 비면 전 컬럼.
GRID_ROW_VALUES_JS = r"""([idxs, fields]) => {
  try {
    const el = document.querySelector('.dews-ui-treegrid');
    const g = window.jQuery(el).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const cols = (fields && fields.length) ? fields : g.getColumns().map(c => c.fieldName).filter(Boolean);
    const out = {};
    for (const i of idxs) {
      const row = {};
      for (const f of cols) {
        try { const v = ds.getValue(i, f); if (v !== null && v !== undefined && String(v) !== '') row[f] = String(v).slice(0, 60); } catch (e) {}
      }
      out[i] = row;
    }
    return out;
  } catch (e) { return { err: String(e).slice(0, 200) }; }
}"""

# 신규 — 현재 체크된 행의 레벨 분포 + 첫 N개 샘플(ITEM_CD/ITEM_NM/level).
CHECKED_SUMMARY_JS = r"""(limit) => {
  try {
    const el = document.querySelector('.dews-ui-treegrid');
    const g = window.jQuery(el).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const items = g.getCheckedRows() || [];
    const levelCounts = {};
    const sample = [];
    for (const idx of items) {
      let level = -1, itemCd = null, itemNm = null;
      try { level = ds.getLevel(idx); } catch (e) {}
      try { itemCd = ds.getValue(idx, 'ITEM_CD'); } catch (e) {}
      try { itemNm = ds.getValue(idx, 'ITEM_NM'); } catch (e) {}
      levelCounts[level] = (levelCounts[level] || 0) + 1;
      if (sample.length < limit) sample.push({ idx, level, ITEM_CD: itemCd, ITEM_NM: itemNm });
    }
    return { ok: true, total: items.length, levelCounts, sample, rawItems: items.slice(0, 30) };
  } catch (e) { return { ok: false, err: String(e).slice(0, 200) }; }
}"""

# 신규 — 트리그리드에서 level==3(SET) 행 후보 목록(인덱스+ITEM_CD/NM) 상위 limit개.
FIND_SET_ROWS_JS = r"""(limit) => {
  try {
    const el = document.querySelector('.dews-ui-treegrid');
    const g = window.jQuery(el).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const count = ds.getRowCount();
    const out = [];
    for (let i = 1; i <= count && out.length < limit; i++) {
      let level = -1;
      try { level = ds.getLevel(i); } catch (e) {}
      if (level === 3) {
        let itemCd = null, itemNm = null;
        try { itemCd = ds.getValue(i, 'ITEM_CD'); } catch (e) {}
        try { itemNm = ds.getValue(i, 'ITEM_NM'); } catch (e) {}
        out.push({ i, ITEM_CD: itemCd, ITEM_NM: itemNm });
      }
    }
    return out;
  } catch (e) { return []; }
}"""

# 신규 — setCurrent 로 특정 행을 스크롤해 보이게 한 뒤, 그리드 컨테이너 기준 상대 좌표 계산
# 시도(여러 후보 API를 순서대로 시도하고 성공한 것과 실패 이력을 함께 반환). arg=itemIndex.
SCROLL_AND_LOCATE_ROW_JS = r"""(itemIndex) => {
  const el = document.querySelector('.dews-ui-treegrid');
  const g = window.jQuery(el).data('dewsControl')._grid;
  const ds = g.getDataSource();
  const attempts = [];
  try {
    const cols = g.getColumns();
    const f = (cols.find(c => c.visible) || cols[0]).fieldName;
    g.setCurrent({ itemIndex, fieldName: f });
    attempts.push({ api: 'setCurrent', ok: true });
  } catch (e) { attempts.push({ api: 'setCurrent', ok: false, err: String(e).slice(0, 100) }); }
  // showRow / ensureVisible / scrollIntoView 류 후보를 순서대로 시도.
  for (const name of ['showRow', 'ensureVisible', 'scrollIntoView', 'moveCurrentIntoView']) {
    try {
      if (typeof g[name] === 'function') { g[name](itemIndex); attempts.push({ api: name, ok: true }); }
      else if (typeof ds[name] === 'function') { ds[name](itemIndex); attempts.push({ api: 'ds.' + name, ok: true }); }
    } catch (e) { attempts.push({ api: name, ok: false, err: String(e).slice(0, 100) }); }
  }
  let cellRect = null;
  try { const cols = g.getColumns(); cellRect = g.getCellRect ? g.getCellRect(itemIndex, cols[0].fieldName) : null; } catch (e) {}
  let currentInfo = null;
  try { currentInfo = g.getCurrent ? g.getCurrent() : null; } catch (e) {}
  return { attempts, cellRect, currentInfo };
}"""

# 신규 — 체크박스(트리) 컬럼 fieldName 추정: getColumns() 에서 헤더/필드명에 check 관련 흔적이
# 있는지, 없으면 첫 트리(indent) 컬럼을 후보로 반환.
CHECK_COLUMN_GUESS_JS = r"""() => {
  try {
    const el = document.querySelector('.dews-ui-treegrid');
    const g = window.jQuery(el).data('dewsControl')._grid;
    const cols = g.getColumns();
    const guess = cols.find(c => /check|chk|sel/i.test(c.fieldName || '') || /선택|체크/.test(c.header || ''));
    return { guess: guess ? { fieldName: guess.fieldName, header: guess.header } : null, first3: cols.slice(0, 3).map(c => ({ fieldName: c.fieldName, header: c.header })) };
  } catch (e) { return { err: String(e).slice(0, 150) }; }
}"""

# 신규 — 캔버스 엘리먼트 rect(체크바/헤더 좌표 계산 기준) + checkBar.width.
CANVAS_RECT_JS = r"""() => {
  try {
    const el = document.querySelector('.dews-ui-treegrid');
    const g = window.jQuery(el).data('dewsControl')._grid;
    const canvas = el.querySelector('canvas');
    const r = canvas.getBoundingClientRect();
    let checkBarWidth = 20;
    try { checkBarWidth = g.getCheckBar().width; } catch (e) {}
    return { rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) }, checkBarWidth };
  } catch (e) { return { err: String(e).slice(0, 150) }; }
}"""

# 신규 — 필터행 전체 덤프(라벨이 <label> 이 아니라 codepicker_fields 의 label 이 null 로 나온다).
# [적용] 버튼 id 와 같은 행에 있는 input 을 x 좌표 근접도로 짝지어 반환.
DUMP_FILTER_ROW_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const btns = [...document.querySelectorAll('button')].filter(b => b.offsetParent !== null && c(b.innerText) === '적용');
  const inputs = [...document.querySelectorAll('input')].filter(e => e.offsetParent !== null).map(e => {
    const r = e.getBoundingClientRect();
    return { id: e.id, value: e.value, readOnly: e.readOnly, cls: (e.className||'').toString().slice(0,80),
             x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width) };
  });
  return btns.map(b => {
    const r = b.getBoundingClientRect();
    // 같은 y 대역(±20px)에서 버튼 왼쪽에 있는 input 중 가장 가까운 것.
    const near = inputs
      .filter(i => Math.abs(i.y - r.y) < 24 && i.x < r.x)
      .sort((p, q) => (r.x - p.x) - (r.x - q.x));
    return {
      btnId: b.id,
      btnRect: { x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2) },
      nearestInputs: near.slice(0, 3),
    };
  });
}"""

# 신규 — 지정 SET 행의 **하위 전 자손 인덱스**를 레벨 워크로 계산(전파 API 에 의존하지 않는다).
# 트리그리드는 부모 바로 뒤에 자손이 이어지므로, level > 기준레벨 인 동안 이어 담는다.
DESCENDANTS_JS = r"""(itemIndex) => {
  try {
    const el = document.querySelector('.dews-ui-treegrid');
    const g = window.jQuery(el).data('dewsControl')._grid;
    const ds = g.getDataSource();
    const count = ds.getRowCount();
    const base = ds.getLevel(itemIndex);
    const out = [];
    for (let i = itemIndex + 1; i <= count; i++) {
      const lv = ds.getLevel(i);
      if (lv <= base) break;
      out.push(i);
    }
    return { base, descendants: out };
  } catch (e) { return { err: String(e).slice(0, 200) }; }
}"""

# 신규 — 지정 인덱스를 **하나씩** g.checkItem(i, true) 로 체크하고 최종 체크 집합을 반환.
# ⚠ `checkItems(배열, true)` 는 쓰지 말 것 — 자손 10개(4~13)를 넘겼는데 99행(다음 SET 과 그
#   하위까지)이 체크되는 과잉 전파가 실측됐다(3차 실행). checkItem 단건은 정확히 1개씩 는다.
# ⚠⚠ 인덱스 공간 함정 2 (3·4차 실측): `checkItem`/`getCheckedItems` 는 **아이템 인덱스** 공간이고
#   `ds.getLevel`/`ds.getValue` 는 **데이터 행** 공간이다. 데이터 행 번호를 checkItem 에 넘기면
#   엉뚱한 행이 체크된다 — 자손 10개(4~13) 요청 → 99행(다음 SET 14 와 그 하위 전부) 체크.
#   변환 API 실재: getItemIndex(dataRow)/getDataRow(itemIndex)/getRowsOfItems/getItemsOfRows.
#   해법: 리더가 데이터 행 공간이므로 **checkRow/getCheckedRows(행 공간)** 로 통일한다.
CHECK_EACH_JS = r"""([rows, checked]) => {
  try {
    const el = document.querySelector('.dews-ui-treegrid');
    const g = window.jQuery(el).data('dewsControl')._grid;
    const before = (g.getCheckedRows() || []).length;
    for (const r of rows) { g.checkRow(r, checked); }
    const after = (g.getCheckedRows() || []);
    return { ok: true, before, after: after.length, items: after };
  } catch (e) { return { ok: false, err: String(e).slice(0, 200) }; }
}"""

# 신규 — g.getCheckedRows() 길이(전/후 비교 공용, **행 공간** — ds 리더와 동일 공간).
GET_CHECKED_LEN_JS = r"""() => {
  try {
    const el = document.querySelector('.dews-ui-treegrid');
    const g = window.jQuery(el).data('dewsControl')._grid;
    return (g.getCheckedRows() || []).length;
  } catch (e) { return -1; }
}"""


async def _shot(page: Page, name: str) -> None:
    try:
        p = str(ARTIFACTS / f"po_dryrun_{name}.png")
        await page.screenshot(path=p, full_page=True)
        print(f"[shot] {p}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[shot] skipped {name}: {exc!r}", flush=True)


async def _dump(name: str, data) -> None:
    path = ARTIFACTS / f"po_dryrun_{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[dump] {path}", flush=True)


async def _scan_dialog(page: Page, *, cap_s: float = 4.0) -> dict | None:
    """DOM 다이얼로그 폴링(k-window/k-dialog/alertdialog). 미발생 None."""
    t0 = time.monotonic()
    while (time.monotonic() - t0) < cap_s:
        dialogs = await page.evaluate(CONFIRM_DIALOG_JS)
        cand = next(
            (d for d in dialogs if d["buttons"] and len(d["buttons"]) <= 3 and "프로젝트" not in d["title"]),
            None,
        )
        if cand:
            return cand
        await page.wait_for_timeout(150)
    return None


async def _wait_sig_change(page: Page, prev: dict | None, *, cap_s: float = 30.0) -> dict:
    """조회 후 그리드 정착 대기 — **직전 시그니처와 달라질 것 + 연속 2폴 동일**.

    `steps.wait_bom_filtered` 는 `mvY==0`(구매요청만) 하드코딩이라 이동요청만 시나리오에 못 쓴다.
    `wait_bom_loaded`(rows>0)만 쓰면 **stale 그리드에 정착**한다 — 1차 실행에서 이동요청만
    조회가 797/133(무필터 시그니처)로 읽힌 원인.
    """
    t0 = time.monotonic()
    last: dict | None = None
    stable = 0
    while (time.monotonic() - t0) < cap_s:
        sig = await po_steps.read_bom_signature(page)
        changed = prev is None or sig != prev
        if changed and last is not None and sig == last:
            stable += 1
            if stable >= 2:
                return sig
        else:
            stable = 0
        last = sig
        await page.wait_for_timeout(300)
    return last or {}


async def _handle_dialog(page: Page, results: dict, key: str, *, click: str) -> dict | None:
    """DOM 다이얼로그가 뜨면 기록하고 `click`(예/아니요) 버튼을 누른다. 미발생 None."""
    dlg = await _scan_dialog(page, cap_s=4.0)
    results[key] = dlg
    if not dlg:
        print(f"[dialog] {key}: 미발생", flush=True)
        return None
    print(f"[dialog] {key}: {dlg['text'][:80]!r} buttons={dlg['buttons']}", flush=True)
    box = await page.evaluate(CONFIRM_BTN_BOX_JS, click)
    if box:
        await page.mouse.click(box["x"], box["y"])
        await page.wait_for_timeout(500)
        results[f"{key}_clicked"] = click
    else:
        results[f"{key}_click_failed"] = f"{click} 버튼 미발견"
    return dlg


async def _apply_buttons(page: Page) -> list[dict]:
    return await page.evaluate(DUMP_APPLY_ROWS_JS)


async def _query_expect(
    page: Page, prev: dict, expect_count: int, results: dict, key: str, *, tries: int = 3
) -> dict:
    """조회 → (미저장 변경 다이얼로그 있으면 [예]) → 시그니처가 기대치가 될 때까지 재시도.

    ⚠ 2차 실행 실패: 체크박스 변경 + 다이얼로그 [예] 까지 다 됐는데 그리드가 갱신되지 않아
    이동요청(164) 데이터셋 그대로였고, 이후 단계 전부가 잘못된 데이터 위에서 돌았다.
    조용히 넘어가면 뒤 단계 결과가 통째로 무의미해지므로 **여기서 명시적으로 실패**시킨다.
    """
    log: list[dict] = []
    for attempt in range(1, tries + 1):
        states = await page.evaluate(
            """(ids) => Object.fromEntries(ids.map(i => {
                 const e = document.getElementById(i); return [i, e ? !!e.checked : null];
               }))""",
            ["s_pu_chk", "s_move_chk"],
        )
        await po_steps.click_lookup(page)
        dlg = await _handle_dialog(page, results, f"{key}_dialog_try{attempt}", click="예")
        sig = await _wait_sig_change(page, prev, cap_s=20.0)
        log.append({"attempt": attempt, "checkbox": states, "dialog": bool(dlg), "signature": sig})
        print(f"[query] {key} try{attempt} checkbox={states} dialog={bool(dlg)} → {sig}", flush=True)
        if sig.get("count") == expect_count:
            results[key] = {"ok": True, "signature": sig, "attempts": log}
            return sig
        await page.wait_for_timeout(1_000)
    results[key] = {
        "ok": False,
        "expected_count": expect_count,
        "attempts": log,
        "cause": "조회 미반영 — 체크박스는 세팅됐으나 그리드 시그니처가 기대치로 바뀌지 않음",
    }
    raise RuntimeError(f"{key}: 조회가 기대 행수({expect_count})로 반영되지 않음 — {log[-1]['signature']}")


async def _click_apply_by_id(page: Page, btn_id: str, results: dict, key: str) -> bool:
    """필터행 `[적용]` 을 **버튼 id 로** 클릭.

    ⚠ 1차 실행 실패 원인: 6개 `[적용]` 이 같은 컨테이너를 공유해 `closest('tr'/'li'/'div')` 의
    rowText 가 전부 동일하다 → 라벨 키워드 매칭이 항상 첫 번째(비용센터)를 집었다.
    실측된 짝(좌표 순서와 일치): 이동출고 `b_public_sl_cd` · 이동입고 `b_mv_sl_cd` ·
    구매요청저장위치 `btn_sl_cd` · 거래처 `btn_partner_cd` · 납기예정일 `btn_bfdedt_dt` ·
    비용센터 `btn_cc_cd`.
    """
    box = await page.evaluate(
        """(id) => {
             const b = document.getElementById(id);
             if (!b || b.offsetParent === null) return null;
             const r = b.getBoundingClientRect();
             return { x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2), disabled: !!b.disabled };
           }""",
        btn_id,
    )
    results[key] = {"btn_id": btn_id, "box": box}
    if not box:
        print(f"[apply] {btn_id}: 버튼 미발견", flush=True)
        return False
    await page.mouse.click(box["x"], box["y"])
    await page.wait_for_timeout(900)
    print(f"[apply] {btn_id}: 클릭 {box}", flush=True)
    return True


async def _pick_code(page: Page, field_id: str, keyword: str) -> dict:
    """필터행 코드피커 — 돋보기 열기(document 스코프) → 검색 → 첫 행 선택 → 적용.

    `codepicker._open_picker` 는 card_collect 모달 전용(`.k-window` 타이틀 '법인카드' 스코프)이라
    최상위 폼에는 못 쓴다(screen23 프로브 실측). 오픈만 document 스코프로 하고 나머지는
    `js_lib.PICKER_*` 를 그대로 재사용한다.
    """
    out: dict = {"field_id": field_id, "keyword": keyword}
    box = await page.evaluate(
        """(id) => {
             const w = document.getElementById(id + '-wrapper');
             const b = w ? w.querySelector('.dews-codepicker-button') : null;
             if (!b) return null;
             const r = b.getBoundingClientRect();
             return { x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2) };
           }""",
        field_id,
    )
    out["open_box"] = box
    if not box:
        out["ok"] = False
        out["reason"] = "돋보기 버튼 미발견"
        return out
    await page.mouse.click(box["x"], box["y"])
    await page.wait_for_timeout(1_200)
    try:
        await codepicker._picker_search(page, keyword)
        await codepicker._wait_picker_rows_stable(page)
        rows = await page.evaluate(js_lib.PICKER_ROWCOUNT_JS)
        out["rowcount"] = rows
        await page.evaluate(js_lib.PICKER_SELECT_JS, 0)
        apply_box = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
        if apply_box:
            await page.mouse.click(apply_box["x"], apply_box["y"])
        await codepicker._wait_picker_closed(page)
        out["ok"] = True
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["err"] = repr(exc)[:200]
        await page.keyboard.press("Escape")
    out["display"] = await page.evaluate(
        "(id) => { const e = document.getElementById(id + '_text') || document.getElementById(id); return e ? e.value : null; }",
        field_id,
    )
    return out


async def _set_text_field(page: Page, field_id: str, value: str) -> dict:
    """상단 폼/필터행 텍스트 입력 — 네이티브 setter + 이벤트(po_js.SET_INPUT_JS 재사용)."""
    await page.evaluate(po_js.SET_INPUT_JS, [field_id, value])
    await page.wait_for_timeout(300)
    got = await page.evaluate(
        "(id) => { const e = document.getElementById(id); return e ? e.value : null; }", field_id
    )
    return {"field_id": field_id, "want": value, "got": got, "ok": got == value}


async def _save_button_info(page: Page) -> dict:
    """⛔ 저장 버튼 셀렉터/좌표/활성여부만 기록 — 클릭하지 않는다."""
    return await page.evaluate(
        """(sel) => {
             const b = document.querySelector(sel);
             if (!b) return { found: false, selector: sel };
             const r = b.getBoundingClientRect();
             return { found: true, selector: sel, disabled: !!b.disabled,
                      rect: { x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2) } };
           }""",
        om_selectors.BTN_SAVE,
    )


async def main() -> None:
    results: dict = {"userid": USERID, "keyword": KEYWORD, "pjt_no": PJT_NO, "mode": "write-dryrun-no-save"}
    native_dialogs: list[dict] = []
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO)
    raw_page = await browser.new_page(viewport=LIVE_VIEWPORT)
    page = _ScaledPage(raw_page, DELAY_SCALE)
    base = get_settings().erp_base

    async def _on_native_dialog(dialog) -> None:
        entry = {"type": dialog.type, "message": dialog.message, "phase": results.get("_phase")}
        native_dialogs.append(entry)
        print(f"[NATIVE DIALOG] {entry}", flush=True)
        # ⛔ 저장 확인이면 [아니요] 상당(dismiss), 그 외(재조회 초기화 등)는 진행 허용(accept).
        # 네이티브 confirm 은 accept=예/dismiss=아니오 매핑. 문구로 판별.
        if "저장" in (dialog.message or ""):
            await dialog.dismiss()
        else:
            await dialog.accept()

    raw_page.on("dialog", lambda d: asyncio.ensure_future(_on_native_dialog(d)))

    try:
        # ── 0. 진입 ──────────────────────────────────────────────────────
        results["_phase"] = "entry"
        print("[entry] login + SCM 전환 + 메뉴 진입…", flush=True)
        await ensure_logged_in(page, USERID, PASSWORD, base)
        await ensure_user_type(page, "SCM")
        try:
            await navigate_menu(page, DEEPLINK, base, label=MENU_LABEL, grids_required=1)
        except MenuError as exc:
            results["menu_entry_error"] = str(exc)
            await _dump("results", results)
            return
        await page.wait_for_timeout(1_500)

        print(f"[project] apply_project({KEYWORD!r}, {PJT_NO!r})…", flush=True)
        apply_res = await po_steps.apply_project(page, KEYWORD, PJT_NO)
        results["project_apply"] = apply_res
        if not apply_res.get("ok"):
            results["error"] = "프로젝트 적용 실패 — 중단"
            await _dump("results", results)
            return

        header_res = await po_steps.ensure_fixed_header(page)
        results["ensure_fixed_header"] = header_res
        print(f"[header] {header_res}", flush=True)

        await po_steps.click_lookup(page)
        await po_steps.wait_bom_loaded(page)
        await page.wait_for_timeout(800)
        await _shot(page, "00_initial_query")

        sig_base = await po_steps.read_bom_signature(page)
        results["baseline_query"] = sig_base
        print(f"[entry] 무필터 baseline = {sig_base}", flush=True)
        await _dump("results", results)

        # 필터행 [적용] 버튼 6종 + 라벨 필드 전량 — 저장위치/납기/구매사유 위치 특정용.
        results["apply_rows"] = await _apply_buttons(page)
        results["filter_row"] = await page.evaluate(DUMP_FILTER_ROW_JS)
        results["labeled_fields"] = await page.evaluate(DUMP_LABELED_FIELDS_JS)
        results["codepicker_fields"] = await page.evaluate(DUMP_CODEPICKER_FIELDS_JS)
        results["save_button"] = await _save_button_info(page)  # ⛔ 기록만, 클릭 안 함
        print(f"[recon] 적용버튼 {len(results['apply_rows'])}개 / 저장버튼 {results['save_button']}", flush=True)
        await _dump("results", results)

        # ── 1-1. 이동요청만 필터 → 조회 → 행수(기대 164) ────────────────
        results["_phase"] = "1-1_move_only_filter"
        results["set_구매요청_off"] = await po_steps.set_checkbox(page, "구매요청", False)
        results["set_이동요청_on"] = await po_steps.set_checkbox(page, "이동요청", True)
        sig_move = await _query_expect(page, sig_base, 164, results, "move_only_query")
        print(f"[1-1] 이동요청만 조회 — {sig_move}", flush=True)
        await _shot(page, "01_move_only_after_query")
        await _dump("results", results)

        # ── 1-2. 그리드 정찰 + 전체선택 세터 확정 ────────────────────────
        results["_phase"] = "1-2_select_all"
        introspect = await page.evaluate(TREEGRID_INTROSPECT_JS)
        results["treegrid_introspect"] = introspect
        results["check_column_guess"] = await page.evaluate(CHECK_COLUMN_GUESS_JS)
        results["canvas_rect"] = await page.evaluate(CANVAS_RECT_JS)
        results["check_spy_install"] = await page.evaluate(INSTALL_CHECK_SPY_JS)
        print(f"[1-2] 정찰 count={introspect.get('count')} canvas={results['canvas_rect']}", flush=True)

        # (A) API 경로 — checkAll / setAllCheck 순서로 시도.
        select_all: list[dict] = []
        for method, args in (("checkAll", [True]), ("setAllCheck", [True])):
            res = await page.evaluate(TRY_CHECK_METHOD_JS, [method, args])
            res["method"] = method
            spy = await page.evaluate(READ_CHECK_SPY_JS, True)
            res["handler_spy"] = spy
            select_all.append(res)
            print(f"[1-2] {method}{args} → {res}", flush=True)
            if res.get("ok") and (res.get("after") or 0) > (res.get("before") or 0):
                break
        results["select_all_attempts"] = select_all
        results["checked_after_select_all"] = await page.evaluate(CHECKED_SUMMARY_JS, 5)
        print(f"[1-2] 전체선택 후 = {results['checked_after_select_all'].get('total')}행", flush=True)
        await _shot(page, "02_after_select_all")
        await _dump("results", results)

        # ── 1-3. 저장위치 2종 세팅 + [적용] → 그리드 반영 컬럼 특정 ──────
        results["_phase"] = "1-3_storage_location"
        probe_idxs = [2, 3, 4, 5, 6]
        before_vals = await page.evaluate(GRID_ROW_VALUES_JS, [probe_idxs, []])
        results["storage_before"] = before_vals

        # 실측 짝(1차 실행에서 id 확보): 필드 ↔ [적용] 버튼.
        storage: dict = {}
        for label, field_id, btn_id, want in (
            ("이동출고저장위치", "n_public_sl_cd", "b_public_sl_cd", "공용자재"),
            ("이동입고저장위치", "n_mv_sl_cd", "b_mv_sl_cd", "프로젝트"),
        ):
            storage[label] = {"pick": await _pick_code(page, field_id, want)}
            storage[label]["applied"] = await _click_apply_by_id(
                page, btn_id, results, f"apply_{label}"
            )
            print(f"[1-3] {label} → {storage[label]}", flush=True)
        results["storage_location"] = storage

        after_vals = await page.evaluate(GRID_ROW_VALUES_JS, [probe_idxs, []])
        results["storage_after"] = after_vals
        results["storage_diff"] = {
            i: {k: {"before": before_vals.get(str(i), {}).get(k), "after": v}
                for k, v in after_vals.get(str(i), {}).items()
                if before_vals.get(str(i), {}).get(k) != v}
            for i in probe_idxs
        }
        print(f"[1-3] 저장위치 적용 diff = {results['storage_diff']}", flush=True)
        await _shot(page, "03_after_storage_apply")
        await _dump("results", results)

        # ── 2. 재조회 — '초기화' 다이얼로그 가설(미저장 변경 있을 때만 발생) ──
        results["_phase"] = "2_requery_dialog"
        results["set_이동요청_off"] = await po_steps.set_checkbox(page, "이동요청", False)
        results["set_구매요청_on"] = await po_steps.set_checkbox(page, "구매요청", True)
        sig_pur = await _query_expect(page, sig_move, 664, results, "purreq_only_query")
        print(f"[2] 구매요청만 조회 — {sig_pur}", flush=True)
        await _shot(page, "04_purreq_only_after_query")
        await _dump("results", results)

        # ── 3. 구매요청 구간 — SET 단일 체크 / 납기 / 구매사유 ───────────
        results["_phase"] = "3_unit_inputs"
        await page.evaluate(TRY_CHECK_METHOD_JS, ["checkAll", [False]])  # 초기화
        await page.evaluate(READ_CHECK_SPY_JS, True)
        set_rows = await page.evaluate(FIND_SET_ROWS_JS, 40)
        results["set_rows"] = set_rows
        print(f"[3] SET(level3) 행 {len(set_rows)}개", flush=True)

        if set_rows:
            target = set_rows[0]
            idx = target["i"]
            results["set_target"] = target

            # (A) API 경로 — checkItem 단일 체크 + 자식 전파 관찰.
            r_item = await page.evaluate(TRY_CHECK_METHOD_JS, ["checkRow", [idx, True]])
            r_item["spy"] = await page.evaluate(READ_CHECK_SPY_JS, True)
            results["check_item_api"] = r_item
            results["checked_after_check_item"] = await page.evaluate(CHECKED_SUMMARY_JS, 10)
            print(f"[3] checkRow({idx}) → {r_item} / 체크수={results['checked_after_check_item'].get('total')}", flush=True)

            # 자식 전파 — 1차 실행에서 checkChildren(idx, True, True) 가 before/after 1→1 로
            # 전파에 실패했다. 인자 시그니처 후보를 훑고, 그래도 안 되면 **자손 인덱스를 직접
            # 계산해 checkItems 로 일괄 체크**한다(전파 API 의미론에 의존하지 않는 결정적 경로).
            desc = await page.evaluate(DESCENDANTS_JS, idx)
            results["descendants"] = {"base_level": desc.get("base"), "count": len(desc.get("descendants") or [])}
            print(f"[3] SET({idx}) 자손 {results['descendants']}", flush=True)

            child_attempts: list[dict] = []
            for args in ([idx, True, True], [idx, True], [idx]):
                r = await page.evaluate(TRY_CHECK_METHOD_JS, ["checkChildren", args])
                r["args"] = args
                r["spy"] = await page.evaluate(READ_CHECK_SPY_JS, True)
                child_attempts.append(r)
                print(f"[3] checkChildren{args} → before={r.get('before')} after={r.get('after')}", flush=True)
                if r.get("ok") and (r.get("after") or 0) > (r.get("before") or 0):
                    break
            results["check_children_attempts"] = child_attempts

            # ⚠ checkItems(배열, true) 는 과잉 전파(자손 10 요청 → 99 체크, 3차 실측)라 폐기.
            #    checkItem 단건 루프 + **정확 일치 검증**이 확정 경로다.
            expected = sorted([idx, *(desc.get("descendants") or [])])
            each = await page.evaluate(CHECK_EACH_JS, [desc.get("descendants") or [], True])
            each["spy"] = await page.evaluate(READ_CHECK_SPY_JS, True)
            got = sorted(each.get("items") or [])
            each["expected"] = expected
            each["exact_match"] = got == expected
            each["unexpected"] = [i for i in got if i not in expected]
            each["missing"] = [i for i in expected if i not in got]
            results["check_each_loop"] = each
            print(
                f"[3] checkItem 루프(자손 {len(desc.get('descendants') or [])}개) → "
                f"체크 {each.get('after')} / 기대 {len(expected)} / 정확일치={each['exact_match']}",
                flush=True,
            )
            if not each["exact_match"]:
                print(
                    f"[3] ⚠ 체크 집합 불일치 — 초과={each['unexpected'][:10]} 누락={each['missing'][:10]}",
                    flush=True,
                )

            results["checked_after_children"] = await page.evaluate(CHECKED_SUMMARY_JS, 10)
            print(f"[3] 전파 후 체크수 = {results['checked_after_children'].get('total')}", flush=True)

            # (B) 실클릭 경로 — 체크바 좌표 캘리브레이션(헤더높이 후보 스캔).
            await page.evaluate(TRY_CHECK_METHOD_JS, ["checkAll", [False]])
            await page.evaluate(SCROLL_AND_LOCATE_ROW_JS, 1)
            await page.wait_for_timeout(400)
            canvas = (results["canvas_rect"] or {}).get("rect") or {}
            bar_w = (results["canvas_rect"] or {}).get("checkBarWidth") or 20
            # 1차 실행에서 헤더높이 후보 6종(28~40) × x=바중앙 이 전부 0 체크였다 →
            # y 를 넓게(첫 데이터행 근방 20~140px) 훑고 x 도 3종 시도한다.
            calib: list[dict] = []
            hit_entry: dict | None = None
            for x_off in (6, 10, 16):
                if hit_entry:
                    break
                for y_off in range(20, 141, 6):
                    x = canvas.get("x", 0) + x_off
                    y = canvas.get("y", 0) + y_off
                    await page.mouse.click(x, y)
                    await page.wait_for_timeout(200)
                    n = await page.evaluate(GET_CHECKED_LEN_JS)
                    if n and n > 0:
                        got = await page.evaluate(CHECKED_SUMMARY_JS, 3)
                        hit_entry = {
                            "x_off": x_off, "y_off": y_off, "click": {"x": x, "y": y},
                            "checked_total": got.get("total"), "sample": got.get("sample"),
                            "spy": await page.evaluate(READ_CHECK_SPY_JS, True),
                        }
                        calib.append(hit_entry)
                        print(f"[3] 좌표 캘리브 HIT x+{x_off} y+{y_off} → 체크 {n}", flush=True)
                        await page.evaluate(TRY_CHECK_METHOD_JS, ["checkAll", [False]])
                        break
            results["click_calibration"] = {
                "canvas": canvas, "checkBarWidth": bar_w,
                "hit": hit_entry, "scanned": len(calib),
                "note": "미적중이면 캔버스 좌표 클릭이 체크바에 안 닿는다는 뜻 — API 경로를 채택",
            }
            if not hit_entry:
                print("[3] 좌표 캘리브 전 구간 미적중 — 실클릭 경로 보류, API 경로 채택", flush=True)

            # 본 작업용 체크 복원 — SET + 자손을 checkItem 단건 루프로(과잉 전파 없는 경로).
            restore = await page.evaluate(CHECK_EACH_JS, [expected, True])
            restore["exact_match"] = sorted(restore.get("items") or []) == expected
            results["checked_restore"] = restore
            results["checked_final"] = await page.evaluate(CHECKED_SUMMARY_JS, 10)
            print(f"[3] 체크 복원 {restore.get('after')}행 정확일치={restore['exact_match']}", flush=True)
            await _shot(page, "05_after_set_check")
            await _dump("results", results)

        # 납기예정일 — 필터행 입력 + [적용] → 어느 컬럼에 꽂히는지 diff.
        results["_phase"] = "3b_due_date"
        chk = results.get("checked_final") or {}
        due_idxs = [s["idx"] for s in (chk.get("sample") or [])][:5] or [2, 3, 4]
        due_before = await page.evaluate(GRID_ROW_VALUES_JS, [due_idxs, []])
        # 납기예정일 입력 id — 필터행 덤프에서 `btn_bfdedt_dt` 왼쪽 최근접 input 으로 역산.
        due_row = next(
            (r for r in (results.get("filter_row") or []) if r.get("btnId") == "btn_bfdedt_dt"), None
        )
        due_input = next(
            (i for i in ((due_row or {}).get("nearestInputs") or []) if i.get("id")), None
        )
        results["due_field"] = {"row": due_row, "picked_input": due_input}
        if due_input:
            results["due_set"] = await _set_text_field(page, due_input["id"], DUE_DATE)
            print(f"[3b] 납기 입력 id={due_input['id']} → {results['due_set']}", flush=True)
        results["due_applied"] = await _click_apply_by_id(
            page, "btn_bfdedt_dt", results, "apply_납기예정일"
        )
        due_after = await page.evaluate(GRID_ROW_VALUES_JS, [due_idxs, []])
        results["due_diff"] = {
            i: {k: {"before": due_before.get(str(i), {}).get(k), "after": v}
                for k, v in due_after.get(str(i), {}).items()
                if due_before.get(str(i), {}).get(k) != v}
            for i in due_idxs
        }
        print(f"[3b] 납기 적용 diff = {results['due_diff']}", flush=True)
        await _dump("results", results)

        # 구매사유 — 상단 폼(#i_rmk_dc)인지 필터행([적용] 필요)인지 실측.
        results["_phase"] = "3c_purchase_reason"
        reason_fld = next(
            (f for f in results["labeled_fields"] if (f.get("label") or "").startswith("구매사유")),
            None,
        )
        results["reason_field"] = reason_fld
        reason_id = (reason_fld or {}).get("anyInputId") or "i_rmk_dc"
        results["reason_set"] = await _set_text_field(page, reason_id, PURCHASE_REASON)
        rows_now = await _apply_buttons(page)
        results["reason_has_apply_btn"] = any("구매사유" in r.get("rowText", "") for r in rows_now)
        print(
            f"[3c] 구매사유 id={reason_id} set={results['reason_set']} "
            f"적용버튼={results['reason_has_apply_btn']}",
            flush=True,
        )
        await _shot(page, "06_before_save")
        await _dump("results", results)

        # ── 4. 저장 직전 스냅샷 — ⛔ 여기서 멈춘다 ──────────────────────
        results["_phase"] = "4_pre_save_snapshot"
        results["pre_save"] = {
            "checked": await page.evaluate(CHECKED_SUMMARY_JS, 10),
            # ⚠ HEADER_STATE_JS 는 ([codeIds, reasonId]) 를 받는다 — 인자 없이 부르면
            #   'object null is not iterable' 로 터진다(1차 실행 마지막 예외 원인).
            "header_state": await page.evaluate(
                po_js.HEADER_STATE_JS, [["i_purgrp_cd", "i_purorg_cd"], "i_rmk_dc"]
            ),
            "sample_values": await page.evaluate(GRID_ROW_VALUES_JS, [due_idxs, []]),
            "save_button": await _save_button_info(page),  # ⛔ 클릭 안 함
        }
        print(f"[4] 저장 직전 스냅샷 — 저장 버튼 클릭하지 않음. {results['pre_save']['save_button']}", flush=True)
        await _dump("results", results)

        # ── 5. 정리 — 미저장 변경 버리기(저장 확인 뜨면 [아니요]) ────────
        results["_phase"] = "5_discard"
        await po_steps.set_checkbox(page, "이동요청", True)
        await po_steps.click_lookup(page)
        await _handle_dialog(page, results, "discard_dialog", click="아니요")
        await page.wait_for_timeout(1_200)
        results["saved_anything"] = False
        print("\n===== DRYRUN COMPLETE — 저장 0건, 잔존 데이터 0 =====", flush=True)

    except Exception as exc:  # noqa: BLE001
        results["error"] = f"probe exception: {exc!r}"
        results["native_dialogs"] = native_dialogs
        print(f"[ERROR] {results['error']}", flush=True)
        await _shot(raw_page, "exception")
        await _dump("results", results)
    finally:
        results["native_dialogs"] = native_dialogs
        await _dump("results_final_partial1", results)
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
