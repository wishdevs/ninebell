"""프로브 — 참조문서 dialog 의 **조회 버튼 / 목록 컨테이너 / 선택된 문서 목록** DOM 확정.

사용자 리포트(2026-07-27): 미지급금 법인카드 참조문서 단계에서
  (a) 문서번호를 넣고도 **어떤 건 조회를 클릭하고 어떤 건 안 한다**,
  (b) **한 건도 '선택된 문서 목록'에 추가되지 않는다**.

코드 감사 결과 확인 로직이 빠진 자리는 3곳이다:
  1. `expand_refdoc_filter` best-effort + 반환 무시 → 필터가 안 펼쳐져도 그대로 진행.
  2. `run_refdoc_search` 는 '조회' 버튼 rect 를 **가시성 필터 없이** 찾고(접힌 패널의 0×0
     버튼도 잡힘 → (0,0) 클릭), 반환 False(버튼 미발견)를 **호출부가 무시**한다.
  3. `move_refdoc_down` 은 이동 결과를 **읽을 리더가 없어** 미확인으로 통과한다.

이 프로브가 확정할 것:
  Q1. dialog 안 '조회' 버튼 후보들의 가시성·rect·disabled 상태(왜 어떤 건 클릭이 안 되는가).
  Q2. 참조문서**목록**(상단)과 **선택된 문서 목록**(하단) 컨테이너를 구분할 수 있는 DOM 특징.
  Q3. 아래(↓) 버튼 클릭 **전/후** 두 목록의 문서번호 분포 — 이동 성공을 읽을 리더의 근거.

⚠ 절대 안전: 참조문서 '확인' 미클릭, 결제창 상신·보관 미클릭, 저장(F7)·삭제(F6) 없음.
   결제창은 **정확히 1건만** 연다(EAP 임시문서 1건 — 기존 단건 결재와 동일 성격).
   dialog 는 취소(X)로 닫고 결제창도 닫는다(비영속).

Usage:
    cd backend && .venv/bin/python e2e/voucher_card_refdoc_dom_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import async_playwright  # noqa: E402

from app.agents.voucher_card import js as cjs  # noqa: E402
from app.agents.voucher_card import steps as csteps  # noqa: E402
from app.agents.voucher_receivable import steps as vr_steps  # noqa: E402
from app.config import get_settings  # noqa: E402
from nbkit.omnisol.menu_schemas import VOUCHER_RECEIVABLE  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
OUT = ARTIFACTS / "voucher_card_refdoc_dom.json"

# Q1 — '조회' 버튼 후보 전수(가시성·크기·disabled 포함). 현재 코드는 첫 매치를 무조건 쓰므로
# 숨은 버튼(접힌 패널)을 잡으면 (0,0) 근처를 클릭하게 된다.
SEARCH_BTNS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  return [...document.querySelectorAll('button')]
    .filter(b => c(b.innerText) === '조회')
    .map(b => {
      const r = b.getBoundingClientRect();
      return {
        visible: b.offsetParent !== null,
        disabled: !!b.disabled,
        x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
        w: Math.round(r.width), h: Math.round(r.height),
        cls: (b.className || '').toString().slice(0, 80),
      };
    });
}"""

# Q2/Q3 — 문서번호 텍스트가 **어느 컨테이너**에 있는지. 각 매치의 조상 3단계 클래스와 y 좌표로
# 상단(참조문서목록) / 하단(선택된 문서 목록)을 가른다.
DOCNO_PLACES_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const re = /\(주\)나인벨-\d{4}-\d+/;
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    if (el.children.length > 0) continue;
    if (el.offsetParent === null) continue;
    const t = c(el.innerText || el.textContent || '');
    const m = t.match(re);
    if (!m) continue;
    const r = el.getBoundingClientRect();
    const chain = [];
    let p = el.parentElement;
    for (let i = 0; i < 4 && p; i++) {
      chain.push((p.tagName || '') + '.' + ((p.className || '').toString().split(/\s+/)[0] || ''));
      p = p.parentElement;
    }
    out.push({ docNo: m[0], y: Math.round(r.y), x: Math.round(r.x), chain });
  }
  return out;
}"""

# 조회 결과 목록의 **행 수와 샘플 텍스트** — '(주)나인벨-…' 정규식에 안 걸리는 형식의 결과도
# 잡기 위해(매치 0 = 결과 0 이 아닐 수 있다) 목록 영역의 실제 행을 센다.
# 참조문서 목록/선택된 문서 목록은 **캔버스 그리드**다(DOM 텍스트 스캔 불가 — 숨은
# grid_<uuid>_line 입력이 증거). 어떤 그리드 API 로 행을 읽을 수 있는지 실측한다.
GRID_API_JS = r"""() => {
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
  const out = { ok: true, globals: {
      RealGridJS: typeof window.RealGridJS, jQuery: typeof window.jQuery,
    }, grids: [] };
  // 숨은 line 입력의 조상에서 그리드 루트를 찾는다.
  const hidden = [...dlg.querySelectorAll('input[id^=grid_]')];
  for (const h of hidden) {
    let root = h.parentElement, found = null;
    for (let i = 0; i < 6 && root; i++) {
      if (root.querySelector('canvas')) { found = root; break; }
      root = root.parentElement;
    }
    const rec = { inputId: h.id, rootCls: found ? (found.className||'').toString().slice(0,80) : null,
                  canvases: found ? found.querySelectorAll('canvas').length : 0 };
    if (found) {
      const r = found.getBoundingClientRect();
      rec.box = { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
      // 프레임워크 훅 후보 — React props / dews / RealGrid 인스턴스 키
      rec.keys = Object.keys(found).slice(0, 12);
      try {
        if (window.jQuery) {
          const d = window.jQuery(found).data();
          rec.jqueryData = d ? Object.keys(d).slice(0, 10) : null;
        }
      } catch (e) { rec.jqueryErr = String(e).slice(0, 60); }
    }
    out.grids.push(rec);
  }
  // RealGrid 전역 인스턴스 목록(있으면 rowCount 를 바로 읽을 수 있다).
  try {
    if (window.RealGridJS && window.RealGridJS.GridView) out.hasGridView = true;
  } catch (e) { out.globalErr = String(e).slice(0, 60); }
  // '선택된 문서 목록' 빈 상태 문구 — 이동 성공 판정의 앵커 후보.
  out.emptyMarker = c(dlg.innerText).includes('선택된 목록이 없습니다.');
  return out;
}"""

# 하단 '선택된 문서 목록'에서 특정 문서번호를 **읽을 수 있는지** 판정한다.
# arg = 문서번호. 반환 {ok, dialogTextHasDocNo, bottomGridBox, leafMatches, canvasCount, aria}.
# RealGrid 인스턴스를 잡을 수 있는가 — 잡히면 하단 목록의 **실제 행 데이터**를 읽어
# '그 문서가 담겼는지'까지 확인할 수 있다.
# 하단(선택된 문서 목록) 그리드에서 **행 수**를 알 수 있는 흔적(ARIA/data-*/스크롤 높이) 탐색.
# 하단 그리드의 **행 수 API** 를 끝까지 찾는다 — RealGridJS 전체 키, 컨테이너/부모의 모든
# own-property(심볼 포함), React fiber 속 인스턴스, 전역 스캔(전체 키).
# gridView 인스턴스로 두 그리드의 **행 수·행 데이터**를 직접 읽는다.
GRIDVIEW_READ_JS = r"""() => {
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
    if (!gv) continue;
    const r = el.getBoundingClientRect();
    const rec = { id: el.id, y: Math.round(r.y), api: [] };
    for (const m of ['getItemCount', 'getRowCount', 'getDataSource', 'getColumns']) {
      if (typeof gv[m] === 'function') rec.api.push(m);
    }
    try { rec.itemCount = gv.getItemCount(); } catch (e) { rec.itemCountErr = String(e).slice(0, 60); }
    try {
      const ds = gv.getDataSource();
      rec.rowCount = ds.getRowCount();
      const n = Math.min(rec.rowCount, 3);
      rec.rows = n > 0 ? ds.getJsonRows(0, n - 1) : [];
    } catch (e) { rec.dsErr = String(e).slice(0, 80); }
    try { rec.cols = gv.getColumns().map(x => x.fieldName || x.name).slice(0, 10); } catch (e) {}
    views.push(rec);
  }
  views.sort((a, b) => a.y - b.y);
  return { ok: true, views };
}"""

GRID_COUNT_HUNT_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const out = {};
  try { out.realgridAllKeys = Object.getOwnPropertyNames(window.RealGridJS); } catch (e) {}
  const heading = [...document.querySelectorAll('*')].find(
    el => el.children.length === 0 && c(el.innerText) === '참조문서');
  let dlg = heading;
  for (let i = 0; i < 8 && dlg; i++) {
    const r = dlg.getBoundingClientRect();
    if (r.width > 400 && r.height > 300) break;
    dlg = dlg.parentElement;
  }
  if (!dlg) return { ...out, ok: false };
  const roots = [...dlg.querySelectorAll('input[id^=grid_]')].map(h => {
    let root = h.parentElement;
    for (let i = 0; i < 6 && root; i++) { if (root.querySelector('canvas')) return root; root = root.parentElement; }
    return null; }).filter(Boolean);
  roots.sort((a, b) => a.getBoundingClientRect().y - b.getBoundingClientRect().y);
  const bottom = roots[1];
  out.bottomFound = !!bottom;
  if (!bottom) return { ...out, ok: false };
  // 컨테이너와 조상들의 own-property/심볼에서 그리드 뷰처럼 보이는 것 찾기.
  const looksLikeView = v => v && typeof v === 'object' &&
    (typeof v.getItemCount === 'function' || typeof v.getDataSource === 'function' ||
     typeof v.getRowCount === 'function');
  out.hits = [];
  let node = bottom;
  for (let up = 0; up < 6 && node; up++, node = node.parentElement) {
    const names = Object.getOwnPropertyNames(node).concat(
      Object.getOwnPropertySymbols(node).map(String));
    for (const n of Object.getOwnPropertyNames(node)) {
      try {
        const v = node[n];
        if (looksLikeView(v)) out.hits.push({ up, prop: n, id: node.id || null });
        // React fiber/props 안쪽도 한 단계 본다.
        if (/^__react/.test(n) && v && typeof v === 'object') {
          for (const k of Object.keys(v).slice(0, 40)) {
            if (looksLikeView(v[k])) out.hits.push({ up, prop: n + '.' + k, id: node.id || null });
          }
        }
      } catch (e) {}
    }
    if (up === 0) out.ownProps = names.slice(0, 25);
  }
  // 전역 전체 스캔(키 제한 없음).
  out.globalViews = [];
  try {
    for (const k of Object.keys(window)) {
      try { if (looksLikeView(window[k])) out.globalViews.push(k); } catch (e) {}
    }
  } catch (e) {}
  return { ...out, ok: true };
}"""

BOTTOM_GRID_ATTRS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const heading = [...document.querySelectorAll('*')].find(
    el => el.children.length === 0 && c(el.innerText) === '참조문서');
  let dlg = heading;
  for (let i = 0; i < 8 && dlg; i++) {
    const r = dlg.getBoundingClientRect();
    if (r.width > 400 && r.height > 300) break;
    dlg = dlg.parentElement;
  }
  if (!dlg) return { ok: false };
  const roots = [...dlg.querySelectorAll('input[id^=grid_]')].map(h => {
    let root = h.parentElement;
    for (let i = 0; i < 6 && root; i++) { if (root.querySelector('canvas')) return root; root = root.parentElement; }
    return null; }).filter(Boolean);
  roots.sort((a, b) => a.getBoundingClientRect().y - b.getBoundingClientRect().y);
  const bottom = roots[1];
  if (!bottom) return { ok: false, reason: 'no-bottom' };
  const collect = el => {
    const o = { tag: el.tagName, id: el.id || null, cls: (el.className||'').toString().slice(0,60), attrs: {} };
    for (const a of el.attributes || []) {
      if (/^(aria-|role|data-)/.test(a.name)) o.attrs[a.name] = String(a.value).slice(0, 60);
    }
    return o;
  };
  const nodes = [collect(bottom)];
  for (const el of bottom.querySelectorAll('*')) {
    const info = collect(el);
    if (Object.keys(info.attrs).length) nodes.push(info);
    if (nodes.length > 15) break;
  }
  // 스크롤 영역 높이로 행 수를 유추할 수 있는지(내용 높이 / 행 높이).
  const scrollers = [...bottom.querySelectorAll('*')].filter(e => e.scrollHeight > e.clientHeight + 2)
    .map(e => ({ cls: (e.className||'').toString().slice(0,50), sh: e.scrollHeight, ch: e.clientHeight }));
  return { ok: true, nodes, scrollers, text: c(bottom.innerText).slice(0, 200) };
}"""

GRID_API_DEEP_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const out = { realgridKeys: [], views: [], containerProps: [] };
  try {
    if (window.RealGridJS) out.realgridKeys = Object.getOwnPropertyNames(window.RealGridJS).slice(0, 30);
  } catch (e) { out.err = String(e).slice(0, 80); }
  const heading = [...document.querySelectorAll('*')].find(
    el => el.children.length === 0 && c(el.innerText) === '참조문서');
  let dlg = heading;
  for (let i = 0; i < 8 && dlg; i++) {
    const r = dlg.getBoundingClientRect();
    if (r.width > 400 && r.height > 300) break;
    dlg = dlg.parentElement;
  }
  if (!dlg) return { ...out, ok: false };
  const roots = [...dlg.querySelectorAll('input[id^=grid_]')].map(h => {
    let root = h.parentElement;
    for (let i = 0; i < 6 && root; i++) { if (root.querySelector('canvas')) return root; root = root.parentElement; }
    return null; }).filter(Boolean);
  roots.sort((a, b) => a.getBoundingClientRect().y - b.getBoundingClientRect().y);
  for (const r of roots) {
    const props = Object.getOwnPropertyNames(r).filter(k => !/^(__reactFiber|__reactProps)/.test(k));
    out.containerProps.push({ id: r.id || null, props: props.slice(0, 15),
                              parentId: r.parentElement ? (r.parentElement.id || null) : null });
  }
  // 전역에서 GridView 인스턴스처럼 보이는 것 탐색(getDataSource 보유).
  try {
    for (const k of Object.keys(window).slice(0, 400)) {
      const v = window[k];
      if (v && typeof v === 'object' && typeof v.getDataSource === 'function') out.views.push(k);
    }
  } catch (e) { out.scanErr = String(e).slice(0, 60); }
  return { ...out, ok: true };
}"""

SELECTED_LIST_PROBE_JS = r"""(docNo) => {
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
  const grids = [...dlg.querySelectorAll('input[id^=grid_]')].map(h => {
    let root = h.parentElement;
    for (let i = 0; i < 6 && root; i++) { if (root.querySelector('canvas')) return root; root = root.parentElement; }
    return null; }).filter(Boolean);
  grids.sort((a, b) => a.getBoundingClientRect().y - b.getBoundingClientRect().y);
  const bottom = grids[1] || null;
  const leafMatches = [];
  if (bottom) {
    for (const el of bottom.querySelectorAll('*')) {
      if (el.children.length > 0) continue;
      const t = c(el.innerText || el.textContent || '');
      if (t && t.includes(docNo)) leafMatches.push(t.slice(0, 80));
    }
  }
  return {
    ok: true,
    dialogTextHasDocNo: c(dlg.innerText).includes(docNo),
    bottomExists: !!bottom,
    canvasCount: bottom ? bottom.querySelectorAll('canvas').length : 0,
    leafMatches,
    ariaText: bottom ? c(bottom.getAttribute('aria-label') || '') : null,
    hiddenInputs: bottom ? [...bottom.querySelectorAll('input')].map(i => (i.value||'').slice(0,40)) : [],
  };
}"""

DIAG_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const heading = [...document.querySelectorAll('*')].find(
    el => el.children.length === 0 && c(el.innerText) === '참조문서');
  let dlg = heading;
  for (let i = 0; i < 8 && dlg; i++) {
    const r = dlg.getBoundingClientRect();
    if (r.width > 400 && r.height > 300) break;
    dlg = dlg.parentElement;
  }
  if (!dlg) return { ok: false };
  const box = e => { const r = e.getBoundingClientRect();
    return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) }; };
  const labels = [...dlg.querySelectorAll('*')]
    .filter(el => el.children.length === 0 && /문서번호/.test(c(el.innerText)))
    .map(el => ({ tag: el.tagName, text: c(el.innerText), box: box(el),
                  cls: (el.className||'').toString().slice(0,50) }));
  const inputs = [...dlg.querySelectorAll('input')].filter(i => i.offsetParent !== null)
    .map(i => ({ box: box(i), value: i.value, w: Math.round(i.getBoundingClientRect().width) }));
  const gridRoots = [...dlg.querySelectorAll('input[id^=grid_]')].map(h => {
    let root = h.parentElement;
    for (let i = 0; i < 6 && root; i++) { if (root.querySelector('canvas')) return root; root = root.parentElement; }
    return null; }).filter(Boolean).map(el => el.getBoundingClientRect()).sort((a,b)=>a.y-b.y);
  const gapTop = gridRoots.length > 1 ? gridRoots[0].bottom : 0;
  const gapBottom = gridRoots.length > 1 ? gridRoots[1].top : 0;
  const gapButtons = [...dlg.querySelectorAll('button')].filter(b => b.offsetParent !== null)
    .map(b => ({ text: c(b.innerText), box: box(b), cls: (b.className||'').toString().slice(0,60) }))
    .filter(b => b.box.y >= gapTop - 5 && b.box.y <= gapBottom);
  return { ok: true, labels, inputs, gapTop: Math.round(gapTop), gapBottom: Math.round(gapBottom), gapButtons };
}"""

DIALOG_DUMP_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  // dialog 루트 — 제목 '참조문서' 리프에서 위로 올라가 충분히 큰 조상.
  const heading = [...document.querySelectorAll('*')].find(
    el => el.children.length === 0 && c(el.innerText) === '참조문서');
  let dlg = heading;
  for (let i = 0; i < 8 && dlg; i++) {
    const r = dlg.getBoundingClientRect();
    if (r.width > 400 && r.height > 300) break;
    dlg = dlg.parentElement;
  }
  if (!dlg) return { ok: false, reason: 'no-dialog' };
  const box = e => { const r = e.getBoundingClientRect();
    return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) }; };
  const buttons = [...dlg.querySelectorAll('button')].filter(b => b.offsetParent !== null)
    .map(b => ({ text: c(b.innerText).slice(0, 20), box: box(b), disabled: !!b.disabled,
                 aria: b.getAttribute('aria-label'), title: b.title || null,
                 cls: (b.className||'').toString().slice(0, 70),
                 html: b.innerHTML.slice(0, 120) }));
  const inputs = [...dlg.querySelectorAll('input')].filter(i => i.offsetParent !== null)
    .map(i => ({ id: i.id || null, name: i.name || null, ph: i.placeholder || null,
                 value: i.value, box: box(i) }));
  // 목록 컨테이너 후보 — dialog 안에서 행처럼 보이는 요소가 여럿인 블록.
  const lists = [];
  for (const el of dlg.querySelectorAll('div, table, ul')) {
    if (el.offsetParent === null) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 150 || r.height < 40) continue;
    const rows = [...el.children].filter(ch => ch.offsetParent !== null && c(ch.innerText));
    if (rows.length < 1) continue;
    lists.push({ cls: (el.className||'').toString().slice(0,80), id: el.id || null,
                 box: box(el), nChildren: rows.length,
                 sample: rows.slice(0, 3).map(ch => c(ch.innerText).slice(0, 90)) });
  }
  return { ok: true, dialogBox: box(dlg), buttons, inputs,
           lists: lists.sort((a,b) => b.nChildren - a.nChildren).slice(0, 12),
           text: c(dlg.innerText).slice(0, 900) };
}"""

RESULT_ROWS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const grids = [...document.querySelectorAll('[class*=Grid], [class*=grid], table, [role=grid]')]
    .filter(el => el.offsetParent !== null);
  let best = null;
  for (const g of grids) {
    const rows = [...g.querySelectorAll('tr, [role=row], [class*=row], [class*=Row]')]
      .filter(r => r.offsetParent !== null && c(r.innerText).length > 0);
    if (!best || rows.length > best.count) {
      best = {
        cls: (g.className || '').toString().slice(0, 90),
        count: rows.length,
        sample: rows.slice(0, 5).map(r => c(r.innerText).slice(0, 120)),
      };
    }
  }
  return best || { cls: null, count: 0, sample: [] };
}"""

# 목록 컨테이너 후보 — dialog 안의 스크롤 가능한 그리드/리스트 영역.
CONTAINERS_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const out = [];
  for (const el of document.querySelectorAll('div, section, table')) {
    if (el.offsetParent === null) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 200 || r.height < 60) continue;
    const cls = (el.className || '').toString();
    if (!/grid|Grid|list|List|table|Table|body|Body/.test(cls)) continue;
    out.push({
      tag: el.tagName, cls: cls.slice(0, 100), id: el.id || null,
      x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
      textHead: c(el.innerText).slice(0, 80),
    });
  }
  return out;
}"""


async def main() -> int:
    settings = get_settings()
    report: dict = {"userid": USERID}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        ctx = await browser.new_context(viewport={"width": 1600, "height": 1000})
        page = await ctx.new_page()
        child = None
        try:
            await ensure_logged_in(page, USERID, PASSWORD, settings.erp_base)
            await ensure_user_type(page, "회계")
            await navigate_schema(page, VOUCHER_RECEIVABLE, settings.erp_base)

            # Phase A — 전표조회승인(전표유형=일반) 조회.
            await vr_steps.expand_condition_panel(page)
            for label, call in (
                ("작성부서", vr_steps.set_dept_all(page)),
                ("회계일", vr_steps.set_period_this_month(page)),
                ("작성자", vr_steps.clear_writer(page)),
                ("전표상태", vr_steps.set_docu_status(page)),
                ("전자결재상태", vr_steps.set_gwaprvlst(page)),
            ):
                r = await call
                if not r.get("ok"):
                    print(f"[FAIL] 조회조건 {label}: {r.get('reason')}")
                    return 1
            r = await vr_steps.set_docu_types(page, csteps.DOCU_TYPES_CARD)
            if not r.get("ok"):
                print(f"[FAIL] 전표유형: {r.get('reason')}")
                return 1
            q = await vr_steps.run_query(page)
            if not q.get("ok") or int(q["rowcount"]) <= 0:
                print(f"[FAIL] 조회: {q}")
                return 1
            print(f"[A] 전표조회승인 대상 {q['rowcount']}건")

            # Phase B — 결재번호 맵 수집(프로덕션 스텝 그대로).
            opened = await csteps.open_collect_tab(page)
            if not opened.get("ok"):
                print(f"[FAIL] 결의서조회승인 탭: {opened.get('reason')}")
                return 1
            await csteps.set_collect_dept_all(page)
            await csteps.clear_collect_writer(page)
            if not await csteps.set_collect_gubun_card(page):
                print("[FAIL] 결의구분=카드 확인 실패")
                return 1
            if not await csteps.run_collect_query(page):
                print("[FAIL] 결의서조회승인 조회 확인 실패")
                return 1
            pm = await csteps.read_payment_map(page)
            payment_map = pm.get("map") or {}
            print(f"[B] 결재번호 맵 {len(payment_map)}건")
            if not payment_map:
                print("[FAIL] 맵 0건 — 참조문서 단계에 도달할 수 없다")
                return 1
            if not await csteps.switch_back_to_voucher_tab(page):
                print("[FAIL] 전표조회승인 탭 복귀 실패")
                return 1

            # 행별 결의서번호 ↔ 맵 대조(대상 선별).
            rows_ab = []
            for idx in range(int(q["rowcount"])):
                ab = await vr_steps.read_row_abdocu_no(page, idx)
                rows_ab.append((idx, await vr_steps.read_row_key(page, idx),
                                str(ab).strip() if ab else ""))
            with_ab = [r for r in rows_ab if r[2]]
            print(f"[C] 조회 {len(rows_ab)}건 / 결의서번호 보유 {len(with_ab)}건 / "
                  f"맵 매칭 {len([r for r in with_ab if r[2] in payment_map])}건")

            # Phase C — 맵에 있는 행 **여러 건**을 프로덕션 훅으로 연속 처리한다.
            from app.agents.voucher_card.nodes.reference_doc import make_reference_doc_hook

            hook = make_reference_doc_hook()
            targets = [(i, d, payment_map[a]) for i, d, a in with_ab if a in payment_map]
            limit = int(os.environ.get("E2E_REFDOC_ROWS", "2"))
            results = []
            for seq, (idx, docu_no, gwdocu_no) in enumerate(targets[:limit], start=1):
                print(f"\n===== [{seq}/{min(limit, len(targets))}] 전표={docu_no} 결재번호={gwdocu_no} =====")
                await vr_steps.uncheck_all_rows(page)
                await vr_steps.check_row(page, idx)
                child = await vr_steps.open_approval(page)
                if child is None:
                    results.append({"seq": seq, "error": "결제창 미출현"})
                    continue
                logs: list = []

                class _Q:
                    async def put(self, frame):
                        logs.append(frame)

                try:
                    await vr_steps.poll_child_ready(child)
                    if os.environ.get("E2E_MANUAL") == "1":
                        # 훅이 dialog 를 닫기 **전** 상태를 판독하기 위해 스텝을 직접 밟는다.
                        await csteps.open_refdoc_dialog(child)
                        await csteps.expand_refdoc_filter(child)
                        await csteps.fill_refdoc_docno(child, gwdocu_no)
                        base = (await csteps.read_refdoc_state(child)).get("total")
                        await csteps.run_refdoc_search(child)
                        st = await csteps.poll_refdoc_result(child, prev_total=base)
                        print(f"   [manual] total={st.get('total')} settled={st.get('settled')}")
                        await csteps.select_refdoc_first_row(child)
                        mv = await csteps.move_refdoc_down(child)
                        print(f"   [manual] move verified={mv.get('verified')}")
                        rows = await child.evaluate(GRIDVIEW_READ_JS)
                        print(f"   [gridView 판독] {json.dumps(rows, ensure_ascii=False)[:900]}")
                        report["gridview_read"] = rows
                        deep = await child.evaluate(GRID_COUNT_HUNT_JS)
                        print(f"   [행수 API 탐색] {json.dumps(deep, ensure_ascii=False)[:1200]}")
                        report["grid_count_hunt"] = deep
                        attrs = await child.evaluate(BOTTOM_GRID_ATTRS_JS)
                        print(f"   [하단그리드 속성] {json.dumps(attrs, ensure_ascii=False)[:700]}")
                        report["bottom_attrs"] = attrs
                        api = await child.evaluate(GRID_API_DEEP_JS)
                        print(f"   [RealGrid API] {json.dumps(api, ensure_ascii=False)[:600]}")
                        report["grid_api_deep"] = api
                        probe = await child.evaluate(SELECTED_LIST_PROBE_JS, gwdocu_no)
                        print(f"   [선택목록 판독] {json.dumps(probe, ensure_ascii=False)[:400]}")
                        report.setdefault("selected_list_probe", []).append(probe)
                        await child.screenshot(path=str(ARTIFACTS / "refdoc_manual_after_move.png"))
                        await csteps.close_refdoc_dialog(child)
                    else:
                        await hook(child, gwdocu_no, _Q())
                    state = await csteps.read_refdoc_state(child)
                    # ⚠ 이동 후 **하단(선택된 문서 목록)에 그 문서번호가 실제로 있는지** 읽을 수
                    #    있는가? 캔버스면 DOM 텍스트로는 안 보인다 — 여기서 결론을 낸다.
                    sel_probe = await child.evaluate(SELECTED_LIST_PROBE_JS, gwdocu_no)
                    print(f"   [선택목록 판독] {json.dumps(sel_probe, ensure_ascii=False)[:300]}")
                    report.setdefault("selected_list_probe", []).append(sel_probe)
                    msgs = [f.get("log") for f in logs if isinstance(f, dict) and f.get("log")]
                    for m in msgs:
                        print(f"   · {m}")
                    results.append({"seq": seq, "docu_no": docu_no, "logs": msgs,
                                    "selectedEmpty": state.get("selectedEmpty"),
                                    "total": state.get("total")})
                    await child.screenshot(path=str(ARTIFACTS / f"refdoc_run_{seq}.png"))
                finally:
                    await vr_steps.close_child(child)
                    await vr_steps.settle_parent_after_child_close(page, child)
                child = None
            report["runs"] = results
            print("\n===== 요약 =====")
            for r in results:
                ok = r.get("selectedEmpty") is False
                print(f"[{r.get('seq')}] {r.get('docu_no')} total={r.get('total')} "
                      f"선택목록반영={'✅' if ok else '❌'}")
        finally:
            if child is not None:
                await vr_steps.close_child(child)
            await ctx.close()
            await browser.close()

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[artifact] {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
