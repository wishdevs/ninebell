"""대화형 폼 도구 — 스키마 + page 조작 디스패치(카드상세 모달 필드 채움).

ninebell-bak `erp/graph.py` 의 `_CHAT_TOOLS` + `_do_fill_search`/`_do_fill_dropdown`/
`_do_fill_text`/`_do_budget`/`_do_account`/`_close_top_popup` 를 이식했다.

화면구동 JS 는 두 갈래다:
- **검증된 경로**(프로젝트·증빙): nbkit.omnisol.js_lib §B 상수 재사용(PROJECT_*/EVDN_*).
- **미검증(스캐폴드) 경로**(거래처·계정·예산단위·드롭다운·텍스트): 라벨 근접 기반 일반화
  프리미티브를 여기 P3-로컬 상수로 둔다(§B 에 없는, 결의서입력 전용 베스트에포트 JS).

각 도구는 **세팅과 확인을 함께** 책임진다(nbkit.omnisol.verify 커널): 팝업이 정말 열렸는지,
'적용'이 폼에 붙었는지, 드롭다운·입력이 되돌려지지 않았는지를 확인하고서야 ok 를 돌려준다.
반환은 :class:`Verdict`(ok/message/status/warn) — 문자열 prefix 판정은 폐기했다.

⚠ 저장(F7)·상신·전표생성 액션은 어디서도 수행하지 않는다 — 모달 '적용'까지만.
"""

# 자체 피커 구현(아래 CARD_PICKER_BOX_JS 등)은 라이브 검증본이라 유지 — 신규 에이전트는
# nbkit.omnisol.codepicker 를 사용할 것(승격 2026-07-05).

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any

from nbkit.omnisol import js_lib, verify

from .domain import budget_for, norm_item

# ══════════════════════════════════════════════════════════════════════════════
# 검증/미검증 필드 카탈로그 — 시스템 프롬프트·로그에 정직하게 표기(거짓 검증 주장 방지).
# ══════════════════════════════════════════════════════════════════════════════
VERIFIED_FIELDS = {"프로젝트", "증빙"}
SCAFFOLD_SEARCH_FIELDS = ["사용자", "거래처", "계정", "예산계정", "예산단위", "비용센터", "사업계획"]
SCAFFOLD_DROPDOWN_FIELDS = ["처리여부", "승인구분", "부가세구분", "봉사료"]
SCAFFOLD_TEXT_FIELDS = ["카드번호", "승인일", "적요"]


# ══════════════════════════════════════════════════════════════════════════════
# P3-로컬 in-page JS(§B 에 없는 결의서입력 전용 미검증 프리미티브).
# ══════════════════════════════════════════════════════════════════════════════

# 임의 코드피커(라벨 기준) 버튼 좌표 — 프로젝트 외 검색형 필드(거래처·계정 등) 공용(미검증).
# (프로젝트는 검증된 js_lib.PROJECT_PICKER_BOX_JS 사용.)
CARD_PICKER_BOX_JS = """(label) => {
  const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
  const root = wins.length ? wins[wins.length - 1] : document;
  const lbls = [...root.querySelectorAll('label,span,div,th')].filter(e => e.offsetParent !== null && String(e.innerText || '').trim() === label);
  if (!lbls.length) return null;
  const lr = lbls[0].getBoundingClientRect();
  const btns = [...root.querySelectorAll('button.dews-codepicker-button')].filter(b => b.offsetParent !== null);
  let best = null, bd = 1e9;
  for (const b of btns) { const r = b.getBoundingClientRect(); if (Math.abs(r.top - lr.top) < 22 && r.left > lr.left) { const dx = r.left - lr.left; if (dx < bd) { bd = dx; best = b; } } }
  if (!best) return null;
  const r = best.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# 가장 최근 팝업(.k-window) 검색창에 q 입력(프로젝트 #s_search_key 패턴 일반화, 미검증).
CARD_POPUP_SEARCH_JS = """(q) => {
  const wins = [...document.querySelectorAll('.k-window')].filter(d => d.offsetParent !== null);
  const dlg = wins[wins.length - 1];
  if (!dlg) return false;
  const i = dlg.querySelector('#s_search_key') || dlg.querySelector('input[type=text], input:not([type])');
  if (!i) return false;
  const s = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(i), 'value').set;
  s.call(i, q); i.dispatchEvent(new Event('input', { bubbles: true })); i.focus();
  return true;
}"""

# 가장 최근 팝업 그리드에서 value(임의 컬럼 일치) 행 선택(미검증).
CARD_POPUP_SELECT_JS = """(val) => {
  try {
    const wins = [...document.querySelectorAll('.k-window')].filter(d => d.offsetParent !== null);
    const dlg = wins[wins.length - 1];
    if (!dlg) return { ok: false, reason: 'no-popup' };
    const pg = window.jQuery(dlg.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const ds = pg.getDataSource();
    const rows = ds.getJsonRows(0, ds.getRowCount() - 1);
    let i = -1, field = null;
    for (let r = 0; r < rows.length && i < 0; r++) {
      for (const [k, v] of Object.entries(rows[r])) {
        if (String(v).trim() === String(val).trim()) { i = r; field = k; break; }
      }
    }
    if (i < 0) for (let r = 0; r < rows.length && i < 0; r++) {
      for (const [k, v] of Object.entries(rows[r])) {
        if (String(v).includes(String(val))) { i = r; field = k; break; }
      }
    }
    if (i < 0) return { ok: false, reason: 'value-not-found' };
    pg.setCurrent({ itemIndex: i, fieldName: field });
    pg.setSelection({ startRow: i, endRow: i, startColumn: 0, endColumn: 0 });
    return { ok: true };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 40) }; }
}"""

# 가장 최근 팝업의 '적용' 버튼 좌표(실제 클릭용).
CARD_POPUP_APPLY_BOX_JS = """() => {
  const wins = [...document.querySelectorAll('.k-window')].filter(d => d.offsetParent !== null);
  const dlg = wins[wins.length - 1];
  if (!dlg) return null;
  const btn = [...dlg.querySelectorAll('button')].find(b => (b.innerText || '').trim() === '적용');
  if (!btn) return null;
  const r = btn.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# Kendo 드롭다운에 value 설정. native value 무시 → 위젯 .value() + change 필수(미검증 필드 포함).
CARD_DROPDOWN_SET_JS = """([label, value]) => {
  try {
    const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
    const root = wins.length ? wins[wins.length - 1] : document;
    const sels = [...root.querySelectorAll('select')];
    let sel = sels.find(s => (s.id || '').includes(label));
    if (!sel) {
      const lbls = [...root.querySelectorAll('label,span,div,th')].filter(e => e.offsetParent !== null && String(e.innerText || '').trim() === label);
      if (lbls.length) {
        const lr = lbls[0].getBoundingClientRect();
        let bd = 1e9;
        for (const s of sels) { const r = s.getBoundingClientRect(); if (Math.abs(r.top - lr.top) < 24 && r.left >= lr.left) { const dx = r.left - lr.left; if (dx < bd) { bd = dx; sel = s; } } }
      }
    }
    if (!sel) sel = sels.find(s => [...s.options].some(o => o.text.trim() === value || o.text.includes(value)));
    if (!sel) return { ok: false, reason: 'select-not-found' };
    const opt = [...sel.options].find(o => o.text.trim() === value) || [...sel.options].find(o => o.text.includes(value));
    if (!opt) return { ok: false, reason: 'option-not-found', opts: [...sel.options].map(o => o.text.trim()).slice(0, 10) };
    const w = window.jQuery && window.jQuery(sel).data('kendoDropDownList');
    if (w) { w.value(opt.value); w.trigger('change'); }
    else { sel.value = opt.value; sel.dispatchEvent(new Event('change', { bubbles: true })); }
    return { ok: true, text: opt.text.trim(), id: sel.id || '' };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 40) }; }
}"""

# 텍스트/날짜/카드번호 입력 채우기. 라벨 근접 또는 id/placeholder 부분일치로 input 을 찾는다(미검증).
CARD_TEXT_SET_JS = """([label, value]) => {
  try {
    const wins = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null);
    const root = wins.length ? wins[wins.length - 1] : document;
    const ins = [...root.querySelectorAll('input')].filter(i => i.offsetParent !== null && i.type !== 'hidden' && !/codepicker|search_key/.test(i.id || ''));
    let inp = ins.find(i => (i.id || '').includes(label) || (i.placeholder || '').includes(label) || (i.getAttribute('aria-label') || '').includes(label));
    if (!inp) {
      const lbls = [...root.querySelectorAll('label,span,div,th')].filter(e => e.offsetParent !== null && String(e.innerText || '').trim() === label);
      if (lbls.length) {
        const lr = lbls[0].getBoundingClientRect();
        let bd = 1e9;
        for (const i of ins) { const r = i.getBoundingClientRect(); if (Math.abs(r.top - lr.top) < 24 && r.left >= lr.left) { const dx = r.left - lr.left; if (dx < bd) { bd = dx; inp = i; } } }
      }
    }
    if (!inp) return { ok: false, reason: 'input-not-found' };
    const s = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(inp), 'value').set;
    s.call(inp, value);
    inp.dispatchEvent(new Event('input', { bubbles: true }));
    inp.dispatchEvent(new Event('change', { bubbles: true }));
    return { ok: true, id: inp.id || '' };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 40) }; }
}"""

# ── 예산단위/계정 팝업 검색·읽기·선택(미검증 도메인 프리미티브) ──────────────────
# 가장 최근 팝업의 검색어(#keyword) 설정.
POPUP_SET_KEYWORD_JS = """(kw) => {
  const dlg = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null).pop();
  if (!dlg) return false;
  const i = dlg.querySelector('#keyword') || dlg.querySelector('input[id*=keyword]');
  if (!i) return false;
  const s = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(i), 'value').set;
  s.call(i, kw); i.dispatchEvent(new Event('input', { bubbles: true })); i.focus();
  return true;
}"""

# 가장 최근 팝업의 '조회' 버튼 좌표.
POPUP_QUERY_BTN_JS = """() => {
  const dlg = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null).pop();
  if (!dlg) return null;
  const b = [...dlg.querySelectorAll('button')].find(x => (x.innerText || '').trim() === '조회');
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# 가장 최근 팝업의 '닫기' 버튼 좌표(없으면 null).
POPUP_CLOSE_BTN_JS = """() => {
  const dlg = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null).pop();
  if (!dlg) return null;
  const b = [...dlg.querySelectorAll('button')].find(x => (x.innerText || '').trim() === '닫기');
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""

# 예산단위 팝업 전체 행 구조화 read(부서/사업계획/예산계정).
BUDGET_READ_JS = """() => {
  try {
    const dlg = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null).pop();
    const g = window.jQuery(dlg.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const ds = g.getDataSource(); const n = ds.getRowCount();
    const rows = n ? ds.getJsonRows(0, n - 1) : [];
    const c = s => String(s == null ? '' : s).replace(/\\s+/g, ' ').trim();
    return { n, dept: rows[0] ? c(rows[0].DEPT_NM) : '',
      rows: rows.map((r, i) => ({ idx: i, bg: c(r.BG_NM), biz: c(r.BIZPLAN_NM), acct: c(r.BGACCT_NM) })) };
  } catch (e) { return { n: 0, rows: [], err: String(e).slice(0, 50) }; }
}"""

# 예산단위 팝업에서 idx 행 선택.
BUDGET_SELECT_JS = """(idx) => {
  try {
    const dlg = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null).pop();
    const g = window.jQuery(dlg.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    g.setCurrent({ itemIndex: idx, fieldName: 'BG_NM' });
    g.setSelection({ startRow: idx, endRow: idx, startColumn: 0, endColumn: 0 });
    return { ok: true };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 40) }; }
}"""

# 계정 팝업 행 read(예산단위 후 자동축소 — 보통 1건).
ACCOUNT_READ_JS = """() => {
  try {
    const dlg = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null).pop();
    const g = window.jQuery(dlg.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const ds = g.getDataSource(); const n = ds.getRowCount();
    const c = s => String(s == null ? '' : s).replace(/\\s+/g, ' ').trim();
    const rows = n ? ds.getJsonRows(0, Math.min(n, 10) - 1) : [];
    const cols = (g.getColumns() || []).filter(x => x.visible !== false).map(x => x.fieldName || x.name);
    return { n, cols, rows: rows.map(r => { const o = {}; for (const k of cols) o[k] = c(r[k]); return o; }) };
  } catch (e) { return { n: 0, rows: [], err: String(e).slice(0, 40) }; }
}"""

# 계정 팝업 idx 행 선택(첫 표시 컬럼 기준).
ACCOUNT_SELECT_JS = """(idx) => {
  try {
    const dlg = [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null).pop();
    const g = window.jQuery(dlg.querySelector('.dews-ui-grid')).data('dewsControl')._grid;
    const cols = (g.getColumns() || []).filter(c => c.visible !== false);
    const f = (cols[0] || {}).fieldName || (cols[0] || {}).name;
    g.setCurrent({ itemIndex: idx, fieldName: f });
    g.setSelection({ startRow: idx, endRow: idx, startColumn: 0, endColumn: 0 });
    return { ok: true };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 40) }; }
}"""

# 카드 모달 로딩 오버레이(dews 진행 바/마스크)가 걷혔는지 — 보이면 false(아직 로딩 중).
# ⚠ 이건 **판정이 아니라 정착(settle)** 이다: 확인 커널이 매 read 직전에 호출해 "로딩 중
#   스냅샷"이나 "직전(스테일) 조회 결과"를 읽고 반영됐다고 오판하는 것을 막는다.
MODAL_IDLE_JS = """() => {
  try {
    const prog = [...document.querySelectorAll('.dews-ui-progress, .dews-progress-wrapper, .dews-progress-bar, [class*="dews-progress"]')]
      .filter(e => e.offsetParent !== null);
    if (prog.length) return false;
    const masks = [...document.querySelectorAll('.k-loading-mask, .k-overlay')]
      .filter(e => e.offsetParent !== null);
    return masks.length === 0;
  } catch (e) { return true; }
}"""

# settle 훅의 폴링 상한(ms) — 확인 1회당 최악 대기. 판정이 아니라 정착이라 짧게 잡는다.
SETTLE_CAP_MS = 1_500


# ══════════════════════════════════════════════════════════════════════════════
# Gemini function-calling 도구 스키마.
# ══════════════════════════════════════════════════════════════════════════════
CHAT_TOOLS: list[dict] = [
    {
        "name": "read_transactions",
        "description": (
            "하단 법인카드 거래 내역 리스트를 읽어 표로 보여준다. 사용자가 '내역/거래 보여줘/뭐 있어/리스트' "
            "라고 하면 호출. 행은 1-based 번호로 참조된다. 값을 채우지는 않는다(읽기 전용)."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "set_expense",
        "description": (
            "법인카드 사용항목(야근식대·회식·국내출장·주차료 등)으로 예산단위+적요를 한 번에 채운다. "
            "use_item=사용항목, division=제조/판매(예산단위가 제/판으로 모호할 때만). "
            "예산단위는 사용자 부서로 자동 매칭하고, 제/판이 남으면 ambiguous 로 되묻는다(그때 ask→division 받아 재호출). "
            "적요는 규칙대로 자동(예: 야근식대→직원 야근 식대(법인카드)). 프로젝트는 별도 fill_search."
        ),
        "parameters": {
            "type": "object",
            "properties": {"use_item": {"type": "string"}, "division": {"type": "string"}},
            "required": ["use_item"],
        },
    },
    {
        "name": "fill_search",
        "description": (
            "코드피커(돋보기) 검색형 필드를 채운다. field=필드명(예 '프로젝트','거래처','계정'), "
            "query=팝업에서 검색할 키워드(선택), value=선택할 행의 표시값. "
            "'프로젝트'는 검증된 경로로 동작하고, 그 외 코드피커 필드는 미검증(베스트에포트)이다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "field": {"type": "string"},
                "query": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["field", "value"],
        },
    },
    {
        "name": "fill_dropdown",
        "description": (
            "Kendo 드롭다운 필드를 채운다(처리여부·승인구분·부가세구분·봉사료 등). "
            "field=필드명, value=옵션 표시 텍스트(예 '공제','불공제'). 미검증(베스트에포트)."
        ),
        "parameters": {
            "type": "object",
            "properties": {"field": {"type": "string"}, "value": {"type": "string"}},
            "required": ["field", "value"],
        },
    },
    {
        "name": "fill_text",
        "description": (
            "텍스트/날짜/카드번호 입력 필드를 채운다(적요·카드번호·승인일 등). "
            "field=필드명, value=입력값. 미검증(베스트에포트)."
        ),
        "parameters": {
            "type": "object",
            "properties": {"field": {"type": "string"}, "value": {"type": "string"}},
            "required": ["field", "value"],
        },
    },
    {
        "name": "ask",
        "description": "정보가 부족하거나 모호할 때 사용자에게 되묻는다. question=물어볼 한 문장.",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
    {
        "name": "turn_done",
        "description": (
            "이번 사용자 요청의 필드를 모두 처리했을 때 호출한다(대화를 끝내는 게 아님). "
            "message=사용자에게 할 짧은 안내. 종료(전송 완료)는 오직 사용자가 화면의 '선택 완료' 버튼으로만 한다."
        ),
        "parameters": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# 확인(verify) 규율 — 이 모듈의 도구는 **세팅과 확인을 함께** 책임진다.
#
# 이전 구조의 조용한 실패(감사 2026-07-27): do_* 가 전부 "팝업 내부 상태 ok" 또는 "세터 JS 가
# ok 를 냈다"에서 멈추고 뒤는 page.wait_for_timeout 고정대기(700~1500ms)뿐이었다. 그 결과
#   · '적용' 버튼 좌표가 없으면 클릭을 **건너뛰고도 ok** 를 반환 → 화면에 없는 값이 템플릿으로 영속
#   · 팝업 열림 판정이 "visible .k-window 가 하나라도 있으면 true" → 카드 모달 자체가 .k-window 라
#     **항상 참**(피커가 안 열려도 opened) → 이후 조작이 카드 모달을 대상으로 나감
#   · 검색어 세팅 JS 의 반환 bool 을 버려 **미필터 전체 목록**이 후보가 됨
# 이제 각 지점은 nbkit.omnisol.verify 커널로 반영을 확인하고서야 ok 를 돌려준다.
#
# 실패 정책: 불일치(리더로 읽었는데 값이 다름/안 붙음) = **하드 실패**(그 값이 전표 데이터를
# 정의한다). 확인 불가(리더가 필드·위젯을 못 읽음) = **경고 후 진행**(리더 오탐이 플로우를
# 끊지 않게 — D7 규율과 동일). 대기는 커널의 **실시간**(asyncio.sleep) 재시도로만 한다
# (page.wait_for_timeout 은 delay_scale 로 축소돼 느린 세션에서 관찰창이 붕괴한다).
#
# ⚠ 어떤 함수도 저장(F7)·상신 액션을 수행하지 않는다(모달 '적용'까지만). reapply 로 다시
#   누르는 것은 **직전과 동일한 액션**(돋보기·조회·적용)뿐이다.
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Verdict:
    """도구 실행 결과 — 세팅 성공이 아니라 **반영 확인** 결과다.

    ok      : 값이 화면에 반영됐음이 확인됨(또는 확인 불가라 경고 후 진행).
    message : 사용자/로그에 그대로 노출하는 한 줄(기존 문자열 반환과 같은 톤).
    status  : ok | fail | ambiguous | unsupported | skip — 호출부 분기용.
    warn    : 확인 불가 사유(있으면 호출부가 warn 로그로 노출하고 '미확인'으로 표시).
    """

    ok: bool
    message: str
    status: str = "ok"
    warn: str | None = None


def merge_warn(*parts: str | None) -> str | None:
    """여러 단계의 '확인 불가' 사유를 하나로 합친다(없으면 None)."""
    got = [p for p in parts if p]
    return " / ".join(got) if got else None


def _norm_project(s: object) -> str:
    """프로젝트 매칭용 — 공백/언더스코어/하이픈 제거 + 소문자('spares acm' ↔ 'SPARES_ACM')."""
    return re.sub(r"[\s_\-]+", "", str(s or "").lower())


def _norm_loose(s: object) -> str:
    """표시값 비교용 — 공백·구분기호 제거 + 소문자(코드피커가 값을 재포맷해도 비교되게)."""
    return re.sub(r"[\s_\-\.,()\[\]/]+", "", str(s or "").lower())


def _display_matches(display: Any, candidates: list[str]) -> bool:
    """코드피커 표시값이 우리가 고른 값인지 — 후보 중 하나와 느슨하게 일치하면 반영된 것.

    ⚠ 빈 문자열은 실패다(= '적용'이 폼에 안 붙음). null 은 여기서 False 지만 호출부가
      ``unknown_when`` 으로 '확인 불가'와 구분한다.
    ⚠ 피커가 코드만/이름만 보여주는 경우가 있어 **양방향 부분일치**로 본다(표시값이 후보를
      포함하거나, 후보가 표시값을 포함).
    """
    if display is None:
        return False
    shown = _norm_loose(display)
    if not shown:
        return False
    wants = [_norm_loose(c) for c in candidates if c]
    if not wants:  # 후보를 모르면 '비어있지 않음'까지만 확인한다.
        return True
    return any(w in shown or shown in w for w in wants)


def _text_matches(actual: Any, expected: str) -> bool:
    """일반 input readback 비교 — 마스킹·날짜 재포맷을 흡수한다.

    승인일 '20260707' 이 위젯에서 '2026-07-07' 로, 카드번호가 '1234-****' 로 재포맷되는 자리가
    있어 정확일치만 요구하면 정상 입력이 하드 실패한다. 반대로 **입력이 거부돼 빈 값**이거나
    전혀 다른 값이면 잡아야 하므로, 구분기호를 제거한 뒤 동등/포함으로 판정한다.
    """
    if actual is None:
        return False
    a = " ".join(str(actual).split())
    e = " ".join(str(expected).split())
    if not e:
        return not a
    if a == e or e in a:
        return True
    ca = re.sub(r"[^0-9A-Za-z가-힣]", "", a)
    ce = re.sub(r"[^0-9A-Za-z가-힣]", "", e)
    return bool(ce) and (ca == ce or ce in ca)


async def wait_modal_idle(page: Any, *, cap_ms: int = 8_000, interval_ms: int = 200) -> bool:
    """카드 모달 로딩 오버레이가 걷힐 때까지 조건 폴링(best-effort). 확인 커널의 ``settle`` 훅.

    ⚠ 대기는 **실시간**(asyncio.sleep)이다 — page.wait_for_timeout 은 워크플로우
      ``delay_scale``(예: 0.4)로 줄어들어 느린 세션에서 관찰창이 40%로 붕괴한다(공지 팝업 선례).
    ⚠ 이 함수는 **판정이 아니다**: 상한을 넘겨도 False 만 돌려주고 흐름을 막지 않는다
      (판정은 confirm_* 가 한다). 스텁/버전차로 평가가 실패하면 True 로 흡수한다.
    """
    waited = 0
    while waited < cap_ms:
        try:
            if await page.evaluate(MODAL_IDLE_JS):
                return True
        except Exception:  # noqa: BLE001 — 스텁/버전차 방어(best-effort).
            return True
        await asyncio.sleep(interval_ms / 1000)
        waited += interval_ms
    return False


def _settle(page: Any):
    """확인 직전 정착 훅 — 로딩이 걷힌 뒤 읽어 '로딩 중 스냅샷/스테일 결과' 오독을 막는다."""
    return lambda: wait_modal_idle(page, cap_ms=SETTLE_CAP_MS)


async def _popup_count(page: Any) -> int:
    """현재 보이는 k-window 개수(카드 모달 포함). 리더가 int 를 못 주면 0 으로 본다."""
    n = await page.evaluate(js_lib.POPUP_COUNT_JS)
    return n if isinstance(n, int) else 0


def _not_int(v: Any) -> bool:
    """POPUP_COUNT_JS 가 int 가 아니면 '개수가 틀림'이 아니라 **확인 불가**다."""
    return not isinstance(v, int)


async def close_top_popup(page: Any) -> Verdict:
    """카드 모달 위 팝업(.k-window)이 떠 있으면 '닫기'(없으면 Escape)로 닫고 **닫혔는지 확인**한다.

    모달 자체도 .k-window 이므로 2개 이상일 때만 동작(모달을 닫지 않게).

    ⚠ 확인이 필요한 이유: 이어지는 do_budget/do_account 의 피커 탐색·조작 root 가 '최상단
      k-window' 다. 안 닫힌 스테일 팝업이 하나 남으면 다음 돋보기 클릭이 그 팝업 뒤라 먹히지
      않는데도 최상단 그리드가 ready 라 오판해 **엉뚱한 창을 조작**한다(2026-07-24 부서팝업
      46행 사고와 같은 구조). 고정대기 700ms 로는 '닫혔다'를 알 수 없다.
    """
    before = await page.evaluate(js_lib.POPUP_COUNT_JS)
    if not isinstance(before, int):
        return Verdict(True, "잔여 팝업 닫힘 미확인", warn="팝업 개수 리더가 int 를 주지 않음")
    if before <= 1:
        return Verdict(True, "닫을 잔여 팝업 없음")

    async def _close() -> None:
        cb = await page.evaluate(POPUP_CLOSE_BTN_JS)
        if cb:
            await page.mouse.click(cb["x"], cb["y"])
        else:
            await page.keyboard.press("Escape")

    await _close()
    res = await verify.confirm_popup_count(
        page, less_than=before, timing=verify.ASYNC, reapply=_close, unknown_when=_not_int
    )
    if res:
        return Verdict(True, "잔여 팝업 닫힘 확인")
    if res.unknown:
        return Verdict(True, "잔여 팝업 닫힘 미확인", warn=res.reason)
    return Verdict(False, f"잔여 팝업이 닫히지 않음 — {res.reason}", status="fail")


async def _open_picker(page: Any, *, label: str, box_js: str, box_arg: Any, what: str) -> tuple[Verdict, str | None]:
    """코드피커 돋보기를 클릭하고 **새 팝업이 떴는지**(개수 증가) 확인한다.

    ⚠ 이전 판정("visible .k-window 가 하나라도 있으면 열림")은 **카드상세 모달 자체가
      .k-window** 라 항상 참이었다 — 피커가 안 열려도 opened=True 가 되고, 이후 팝업 조작 JS 가
      '최상단 k-window' = 카드 모달을 대상으로 나갔다. 열기 **직전 개수**를 기준으로 증가를 봐야
      스테일 팝업/미개봉을 모두 구분할 수 있다.

    반환 (Verdict, warn) — Verdict.ok=False 면 호출부가 즉시 하드 실패로 단락한다.
    """
    before = await _popup_count(page)
    box = await page.evaluate(box_js, box_arg)
    if not box:
        return (Verdict(False, f"'{label}' 코드피커 버튼을 찾지 못함", status="fail"), None)
    await page.mouse.click(box["x"], box["y"])

    async def _reclick() -> None:
        again = await page.evaluate(box_js, box_arg)
        if again:
            await page.mouse.click(again["x"], again["y"])

    res = await verify.confirm_popup_count(
        page, more_than=before, timing=verify.ASYNC, reapply=_reclick, unknown_when=_not_int
    )
    if res:
        return (Verdict(True, f"{what} 열림 확인"), None)
    if res.unknown:
        return (Verdict(True, f"{what} 열림 미확인"), res.reason)
    return (Verdict(False, f"'{label}' 팝업이 열리지 않음 — {res.reason}", status="fail"), None)


async def _apply_and_confirm(
    page: Any,
    *,
    field: str,
    candidates: list[str],
    tag: str = "",
    apply_box_js: str = CARD_POPUP_APPLY_BOX_JS,
) -> Verdict:
    """팝업 '적용'을 클릭하고 **폼 표시값에 반영됐는지** 확인한다 — '적용이 폼에 안 붙는' 자리.

    ⚠ 적용 버튼 좌표가 없으면 지금까지는 클릭을 조용히 건너뛰고 ok 를 돌려줬다: '적용을 아예
      안 했음'이 성공으로 보고돼 화면에 없는 값이 selections/템플릿으로 영속됐다. 여기서는
      **명시적 실패**다(확인 불가가 아니다 — 액션 자체를 못 한 것이므로).
    ⚠ 표시값 리더는 **모달 스코프**(최상단 visible k-window)로 읽는다. 전역 라벨 검색은 모달 뒤
      배경 결의서입력 화면의 동명 라벨을 읽어 '반영됐다'고 오판할 수 있다.
    """
    ab = await page.evaluate(apply_box_js)
    if not ab:
        return Verdict(False, f"fail{tag}: '{field}' 팝업 '적용' 버튼을 찾지 못함(적용 미실행)", status="fail")
    await page.mouse.click(ab["x"], ab["y"])

    async def _reapply() -> None:
        again = await page.evaluate(apply_box_js)
        if again:
            await page.mouse.click(again["x"], again["y"])

    res = await verify.confirm(
        read=lambda: page.evaluate(js_lib.SCOPED_FIELD_VALUE_JS, {"label": field}),
        ok=lambda v: _display_matches(v, candidates),
        timing=verify.ASYNC,
        what=f"'{field}' 폼 표시값",
        expected=candidates[0] if candidates else "(비어있지 않음)",
        settle=_settle(page),
        reapply=_reapply,
        unknown_when=lambda v: v is None,
    )
    if res:
        return Verdict(True, f"ok{tag}: '{field}' = '{res.actual}' 선택·적용(반영 확인)")
    if res.unknown:
        # 리더가 필드를 못 읽음 — 오탐이 플로우를 끊지 않게 진행하되 '미확인'으로 표기한다.
        return Verdict(True, f"ok{tag}: '{field}' 선택·적용(반영 미확인)", warn=res.reason)
    return Verdict(False, f"fail{tag}: '{field}' 적용이 폼에 반영되지 않음 — {res.reason}", status="fail")


async def do_fill_search(page: Any, field: str, query: str, value: str) -> Verdict:
    """검색형 코드피커 채우기. '프로젝트'는 검증된 §B PROJECT_*_JS, 그 외는 일반화(미검증).

    확인 지점(전부 하드): 팝업 개수 증가(열림) → 검색창 세팅 성공 → 조회 결과에 대상 존재 →
    행 선택 → '적용' 실행 → **폼 표시값 반영**. 하나라도 어긋나면 ok 를 돌려주지 않는다.
    """
    verified = field == "프로젝트"
    tag = "" if verified else "(미검증)"
    box_js = js_lib.PROJECT_PICKER_BOX_JS if verified else CARD_PICKER_BOX_JS
    box_arg = None if verified else field

    opened, warn = await _open_picker(
        page, label=field, box_js=box_js, box_arg=box_arg, what=f"'{field}' 코드피커 팝업"
    )
    if not opened.ok:
        return Verdict(False, f"fail{tag}: {opened.message}", status="fail")
    if verified:
        # 보조 확인 — 개수는 늘었지만 그게 '프로젝트' 팝업인지까지 제목으로 본다(soft).
        titled = await verify.confirm(
            read=lambda: page.evaluate(js_lib.PROJECT_POPUP_OPEN_JS),
            ok=bool,
            timing=verify.ASYNC,
            what="프로젝트 팝업 제목",
            expected="프로젝트",
        )
        if not titled:
            warn = merge_warn(warn, titled.reason)

    if query:  # 화면 검색(있으면)으로 후보를 좁힌다.
        set_js = js_lib.PROJECT_SEARCH_SET_JS if verified else CARD_POPUP_SEARCH_JS
        # ⚠ 이 반환값을 버리면 검색창을 못 찾았을 때 **미필터 전체 목록**이 후보가 된 채로
        #   그대로 선택까지 진행한다(엉뚱한 행 선택). 명시적으로 실패시킨다.
        if await page.evaluate(set_js, query) is False:
            return Verdict(
                False, f"fail{tag}: '{field}' 팝업 검색창을 찾지 못함(검색어 미적용)", status="fail"
            )
        await page.keyboard.press("Enter")

    if verified:
        v = _norm_project(value)

        def _has_match(options: Any) -> bool:
            return any(
                v and v in _norm_project(o.get("label", "") + o.get("value", "") + o.get("description", ""))
                for o in (options or [])
            )

        async def _read_opts() -> Any:
            res = await page.evaluate(js_lib.PROJECT_READ_JS, 25)
            return (res or {}).get("options") or []

        # 고정대기(1.2s) 대신 **결과 도착까지 확인**한다 — 조회를 눌렀어도 그리드가 아직
        # 직전(스테일) 결과이거나 로딩 중이면 '결과 없음'으로 오판해 완화 재검색으로 새기 때문.
        found = await verify.confirm(
            _read_opts,
            _has_match,
            timing=verify.HEAVY,
            what=f"프로젝트 '{value}' 검색 결과",
            expected=value,
            settle=_settle(page),
        )
        opts = found.actual or []
        if not found:
            # 더존 검색 0건/무매칭이면 검색어 완화 재시도: 공백→'_' → 첫 토큰.
            base_q = (query or value).strip()
            for cand_q in (base_q.replace(" ", "_"), re.split(r"[\s_]+", base_q)[0] if base_q else ""):
                cand_q = cand_q.strip()
                if not cand_q:
                    continue
                await page.evaluate(js_lib.PROJECT_SEARCH_SET_JS, cand_q)
                await page.keyboard.press("Enter")
                found = await verify.confirm(
                    _read_opts,
                    _has_match,
                    timing=verify.HEAVY,
                    what=f"프로젝트 '{value}' 재검색('{cand_q}') 결과",
                    expected=value,
                    settle=_settle(page),
                )
                opts = found.actual or []
                if found:
                    break

        exact = [o for o in opts if v and v in (_norm_project(o.get("label")), _norm_project(o.get("value")))]
        partial = [
            o
            for o in opts
            if v and v in _norm_project(o.get("label", "") + o.get("value", "") + o.get("description", ""))
        ]
        if len(exact) == 1:
            match = exact[0]
        elif len(partial) == 1 and not exact:
            match = partial[0]
        elif exact or partial:
            cand = ", ".join((o.get("label") or o.get("value") or "") for o in (exact or partial)[:6])
            return Verdict(
                False,
                f"ambiguous: '{value}' 에 일치하는 프로젝트가 여러 개입니다(후보: {cand}). "
                "임의 선택하지 말고 사용자에게 어느 것인지 ask 로 물어보세요.",
                status="ambiguous",
            )
        else:
            return Verdict(
                False, f"fail: 프로젝트 '{value}' 와 일치하는 결과가 없음(검색어를 좁혀 다시 요청)", status="fail"
            )
        sel = await page.evaluate(js_lib.PROJECT_SELECT_JS, match["value"])
        if not (sel or {}).get("ok"):
            return Verdict(False, f"fail: 프로젝트 '{value}' 행 선택 실패", status="fail")
        name = sel.get("name") or value
        applied = await _apply_and_confirm(
            page,
            field=field,
            candidates=[name, str(match.get("value") or ""), value],
            apply_box_js=js_lib.PROJECT_APPLY_BOX_JS,
        )
        return Verdict(applied.ok, applied.message, applied.status, merge_warn(warn, applied.warn))

    # 미검증 일반 코드피커: 값 일치 행 선택 → 적용.
    # ⚠ 이 팝업 그리드에는 전용 read 리더가 없다 — 선택 JS 자체가 '값 일치 행이 있으면
    #   setCurrent' 라 **멱등**이므로, 커널의 read 로 써서 "그리드가 도착해 대상 행이 생길
    #   때까지" 재시도한다(고정대기 1.2s + 결과 미확인 조합을 대체). 부작용은 우리가 어차피
    #   하려던 선택뿐이다.
    async def _try_select() -> Any:
        return await page.evaluate(CARD_POPUP_SELECT_JS, value)

    picked = await verify.confirm(
        _try_select,
        lambda r: isinstance(r, dict) and bool(r.get("ok")),
        timing=verify.HEAVY,
        what=f"'{field}' 팝업 행 '{value}'",
        expected=value,
        settle=_settle(page),
    )
    if not picked:
        reason = (picked.actual or {}).get("reason") if isinstance(picked.actual, dict) else None
        return Verdict(
            False, f"fail{tag}: '{field}' 행 '{value}' 선택 실패 ({reason or picked.reason})", status="fail"
        )
    applied = await _apply_and_confirm(page, field=field, candidates=[value], tag=tag)
    return Verdict(applied.ok, applied.message, applied.status, merge_warn(warn, applied.warn))


async def do_fill_dropdown(page: Any, field: str, value: str) -> Verdict:
    """Kendo 드롭다운 채우기(미검증). 위젯 .value() + change 필수 + **선택값 재확인**.

    ⚠ 세터의 {ok:true} 는 "옵션을 찾아 위젯 .value()+change 를 호출했다"까지다 — change
      핸들러가 값을 되돌리는 연쇄 필드가 있어(§C SELECTED_TEXT_JS 주석) 선택 텍스트를 다시
      읽어야 확정된다. 되돌려지는 성격이라 재시도 때 **재세팅**(reapply)한다.
    """

    async def _set() -> Any:
        return await page.evaluate(CARD_DROPDOWN_SET_JS, [field, value])

    r = await _set()
    if not (r or {}).get("ok"):
        opts = (r or {}).get("opts")
        extra = f" (가능옵션: {opts})" if opts else ""
        return Verdict(
            False,
            f"fail(미검증): 드롭다운 '{field}' = '{value}' 설정 실패 ({(r or {}).get('reason')}){extra}",
            status="fail",
        )
    text = r.get("text") or value
    sid = str(r.get("id") or "").strip()
    if not sid:
        # 세터가 select id 를 못 준 경우 — 읽을 앵커가 없다(확인 불가). 진행하되 미확인 표기.
        return Verdict(
            True,
            f"ok(미검증): 드롭다운 '{field}' = '{text}' (반영 미확인 — select id 없음)",
            warn=f"드롭다운 '{field}' 선택값 확인 불가(세터가 select id 를 주지 않음)",
        )
    res = await verify.confirm_select(
        page,
        f"#{sid}",
        text,
        timing=verify.INSTANT,
        reapply=_set,
        unknown_when=lambda v: not (isinstance(v, dict) and v.get("ok")),
    )
    if res:
        return Verdict(True, f"ok(미검증): 드롭다운 '{field}' = '{text}' (반영 확인)")
    if res.unknown:
        return Verdict(True, f"ok(미검증): 드롭다운 '{field}' = '{text}' (반영 미확인)", warn=res.reason)
    return Verdict(
        False, f"fail(미검증): 드롭다운 '{field}' 값이 '{text}' 로 유지되지 않음 — {res.reason}", status="fail"
    )


async def do_fill_text(page: Any, field: str, value: str) -> Verdict:
    """텍스트/날짜/카드번호 입력 채우기(미검증) + **입력값 readback**.

    ⚠ 세터의 {ok:true} 는 "input 을 찾아 native setter + input/change 를 발화했다"까지다 —
      마스킹·날짜 위젯이 입력을 재포맷하거나 **거부**해도 성공으로 보고돼 selections/템플릿에
      누적됐다. 세터가 돌려준 id(없으면 라벨 근접)로 실제 value 를 다시 읽어 확정한다.
    """

    async def _set() -> Any:
        return await page.evaluate(CARD_TEXT_SET_JS, [field, value])

    r = await _set()
    if not (r or {}).get("ok"):
        return Verdict(
            False,
            f"fail(미검증): 입력 '{field}' = '{value}' 채우기 실패 ({(r or {}).get('reason')})",
            status="fail",
        )
    iid = str(r.get("id") or "").strip()
    arg = {"selector": f"#{iid}"} if iid else {"label": field}
    res = await verify.confirm(
        read=lambda: page.evaluate(js_lib.SCOPED_FIELD_VALUE_JS, arg),
        ok=lambda v: _text_matches(v, value),
        timing=verify.INSTANT,
        what=f"입력 '{field}'",
        expected=value,
        reapply=_set,
        unknown_when=lambda v: v is None,
    )
    if res:
        return Verdict(True, f"ok(미검증): 입력 '{field}' = '{value}' (반영 확인)")
    if res.unknown:
        return Verdict(True, f"ok(미검증): 입력 '{field}' = '{value}' (반영 미확인)", warn=res.reason)
    return Verdict(
        False,
        f"fail(미검증): 입력 '{field}' 값이 '{value}' 로 반영되지 않음(실제 {res.actual!r})",
        status="fail",
    )


async def _click_popup_query(page: Any) -> None:
    """최상단 팝업의 '조회' 버튼을 누른다(좌표가 없으면 no-op). 확인 재시도의 reapply 로도 쓴다."""
    qb = await page.evaluate(POPUP_QUERY_BTN_JS)
    if qb:
        await page.mouse.click(qb["x"], qb["y"])


async def do_budget(page: Any, use_item: str, division: str) -> Verdict:
    """예산단위 채움 — 사용항목→검색어→부서매칭→(제/판 모호 시 ambiguous).

    status: ok | ambiguous | fail | unsupported. 검증: 야근식대(인사기획팀·석식) 라이브 확인.
    예산단위는 **전표 데이터 자체를 정의**하므로 확인 지점은 전부 하드 실패다.
    """
    bm = budget_for(use_item)
    if not bm:
        return Verdict(False, f"'{use_item}'는 예산단위 매핑에 없는 사용항목입니다.", status="unsupported")
    keyword, acct_sub = bm
    # 이전 팝업이 카드 모달 위에 떠 있으면 닫는다(2차 호출 시 코드피커 가려짐 방지).
    # 안 닫히면 이후 팝업 조작이 스테일 창을 대상으로 나가므로 여기서 끊는다.
    closed = await close_top_popup(page)
    if not closed.ok:
        return Verdict(False, f"예산단위 진입 전 {closed.message}", status="fail")

    opened, warn = await _open_picker(
        page, label="예산단위", box_js=CARD_PICKER_BOX_JS, box_arg="예산단위", what="예산단위 팝업"
    )
    if not opened.ok:
        return Verdict(False, opened.message, status="fail")
    warn = merge_warn(closed.warn, warn)

    # ⚠ 이 반환값을 버리면 #keyword 미발견 시 **필터 없는 전체 목록**이 예산단위 후보가 된다
    #   (엉뚱한 부서·예산계정 선택). 명시적으로 실패시킨다.
    if await page.evaluate(POPUP_SET_KEYWORD_JS, keyword) is False:
        await close_top_popup(page)
        return Verdict(False, f"예산단위 팝업 검색창(#keyword)을 찾지 못함 — '{keyword}' 미적용", status="fail")
    await _click_popup_query(page)

    asub = norm_item(acct_sub)

    def _cands(rd: Any) -> list[dict]:
        """읽은 그리드에서 (부서+예산계정) 후보를 고른다 — 순수 함수(확인 커널의 ok 판정에 재사용)."""
        if not isinstance(rd, dict):
            return []
        rows = rd.get("rows") or []
        nd = norm_item(rd.get("dept", ""))
        # 부서(BG_NM) + 예산계정(BGACCT_NM) 매칭.
        hit = [r for r in rows if asub in norm_item(r.get("acct")) and nd and norm_item(r.get("bg")) == nd]
        if not hit:  # 부서 불일치 시 예산계정만으로(폴백).
            hit = [r for r in rows if asub in norm_item(r.get("acct"))]
        return hit

    # 고정대기(1.5s) 대신 **후보가 잡힐 때까지** 확인한다 — 조회를 눌렀어도 그리드가 아직
    # 직전(스테일) 결과이거나 로딩 중이면 '못 찾음'으로 오판하고 끝났다.
    res = await verify.confirm(
        read=lambda: page.evaluate(BUDGET_READ_JS),
        ok=lambda rd: bool(_cands(rd)),
        timing=verify.HEAVY,
        what=f"예산단위 '{keyword}' 조회 결과",
        expected=acct_sub,
        settle=_settle(page),
        reapply=_click_popup_query,
    )
    rd = res.actual if isinstance(res.actual, dict) else {}
    cand = _cands(rd)
    if not cand:
        await close_top_popup(page)  # 팝업 닫기(다음 시도 위해)
        return Verdict(
            False,
            f"'{keyword}' 검색에서 예산계정 '{acct_sub}'(부서 {rd.get('dept', '')})를 못 찾음",
            status="fail",
        )
    # 제/판 필터(division 주어지면).
    if division:
        dv = "(제)" if "제" in division else ("(판)" if "판" in division else "")
        if dv:
            cand = [r for r in cand if str(r.get("acct", "")).startswith(dv)] or cand
    if len(cand) > 1:
        await close_top_popup(page)  # 팝업 닫기 — 제/판 답 받아 재시도.
        opts = " / ".join(f"{r['bg']}·{r['biz']}·{r['acct']}" for r in cand[:6])
        return Verdict(
            False,
            f"예산단위가 여러 개입니다(제조/판매 등): {opts}. 제조/판매 중 무엇인가요?",
            status="ambiguous",
        )
    sel = await page.evaluate(BUDGET_SELECT_JS, cand[0]["idx"])
    if not (sel or {}).get("ok"):
        return Verdict(False, f"예산단위 행 선택 실패({(sel or {}).get('reason')})", status="fail")
    applied = await _apply_and_confirm(
        page, field="예산단위", candidates=[str(cand[0].get("bg") or ""), str(cand[0].get("acct") or "")]
    )
    if not applied.ok:
        return Verdict(False, f"예산단위 적용 실패 — {applied.message}", status="fail")
    tail = "(반영 미확인)" if applied.warn else "(반영 확인)"
    return Verdict(
        True,
        f"예산단위 '{cand[0]['acct']}' ({cand[0]['bg']}) 선택·적용{tail}",
        warn=merge_warn(warn, applied.warn),
    )


async def do_account(page: Any) -> Verdict:
    """예산단위 후 자동축소된 계정을 자동 선택·적용. 보통 1건.

    ⚠ 후보가 2건 이상이어도 무조건 첫 행을 고른다(도메인 규칙) — 다만 그 모호성을 warn 으로
      노출한다(조용히 첫 행을 고르고 'ok' 로만 보고하던 자리).
    """
    closed = await close_top_popup(page)
    if not closed.ok:
        return Verdict(False, f"계정 진입 전 {closed.message}", status="fail")

    opened, warn = await _open_picker(
        page, label="계정", box_js=CARD_PICKER_BOX_JS, box_arg="계정", what="계정 팝업"
    )
    if not opened.ok:
        return Verdict(False, opened.message, status="fail")
    warn = merge_warn(closed.warn, warn)

    # 1회 read + '조회' 1회 재시도(고정대기 1.2s) 대신 커널로 — 로딩 중 스냅샷/스테일 결과를
    # '후보 없음'으로 오판하지 않게 하고, 재시도 때 '조회'를 다시 누른다.
    res = await verify.confirm(
        read=lambda: page.evaluate(ACCOUNT_READ_JS),
        ok=lambda rd: isinstance(rd, dict) and bool(rd.get("rows")),
        timing=verify.HEAVY,
        what="계정 후보",
        expected=">=1건",
        settle=_settle(page),
        reapply=_click_popup_query,
    )
    if not res:
        await close_top_popup(page)
        return Verdict(False, "계정 후보가 없음", status="fail")
    rd = res.actual
    rows = rd.get("rows") or []
    if len(rows) > 1:
        warn = merge_warn(warn, f"계정 후보가 {rd.get('n')}건인데 첫 행을 자동 선택함(모호)")
    sel = await page.evaluate(ACCOUNT_SELECT_JS, 0)  # 자동축소(보통 1건) → 첫 행.
    if not (sel or {}).get("ok"):
        await close_top_popup(page)
        return Verdict(False, f"계정 행 선택 실패({(sel or {}).get('reason')})", status="fail")
    r0 = rows[0]
    acctnm = next((str(v) for k, v in r0.items() if ("NM" in k.upper() or "명" in k) and v), "")
    applied = await _apply_and_confirm(page, field="계정", candidates=[acctnm] if acctnm else [])
    if not applied.ok:
        return Verdict(False, f"계정 적용 실패 — {applied.message}", status="fail")
    tail = "(반영 미확인)" if applied.warn else "(반영 확인)"
    return Verdict(
        True,
        f"계정 '{acctnm or '자동'}' 선택·적용(자동, {rd.get('n')}건){tail}",
        warn=merge_warn(warn, applied.warn),
    )
