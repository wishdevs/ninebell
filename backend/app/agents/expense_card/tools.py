"""대화형 폼 도구 — 스키마 + page 조작 디스패치(카드상세 모달 필드 채움).

ninebell-bak `erp/graph.py` 의 `_CHAT_TOOLS` + `_do_fill_search`/`_do_fill_dropdown`/
`_do_fill_text`/`_do_budget`/`_do_account`/`_close_top_popup` 를 이식했다.

화면구동 JS 는 두 갈래다:
- **검증된 경로**(프로젝트·증빙): nbkit.omnisol.js_lib §B 상수 재사용(PROJECT_*/EVDN_*).
- **미검증(스캐폴드) 경로**(거래처·계정·예산단위·드롭다운·텍스트): 라벨 근접 기반 일반화
  프리미티브를 여기 P3-로컬 상수로 둔다(§B 에 없는, 결의서입력 전용 베스트에포트 JS).

⚠ 저장(F7)·상신·전표생성 액션은 어디서도 수행하지 않는다 — 모달 '적용'까지만.
"""

from __future__ import annotations

import re
from typing import Any

from nbkit.omnisol import js_lib

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

_KWINDOW_ANY_JS = "() => [...document.querySelectorAll('.k-window')].some(w => w.offsetParent !== null)"
_KWINDOW_OVER1_JS = "() => [...document.querySelectorAll('.k-window')].filter(w => w.offsetParent !== null).length > 1"


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
# page 조작 디스패치 — 예외는 호출자(chat_form)가 잡아 graceful 처리한다.
# ⚠ 어떤 함수도 저장(F7)·상신 액션을 수행하지 않는다(모달 '적용'까지만).
# ══════════════════════════════════════════════════════════════════════════════

def _norm_project(s: object) -> str:
    """프로젝트 매칭용 — 공백/언더스코어/하이픈 제거 + 소문자('spares acm' ↔ 'SPARES_ACM')."""
    return re.sub(r"[\s_\-]+", "", str(s or "").lower())


async def close_top_popup(page: Any) -> None:
    """카드 모달 위 팝업(.k-window)이 떠 있으면 '닫기'(없으면 Escape)로 닫는다.

    모달 자체도 .k-window 이므로 2개 이상일 때만 동작(모달을 닫지 않게).
    """
    has_popup = await page.evaluate(_KWINDOW_OVER1_JS)
    if not has_popup:
        return
    cb = await page.evaluate(POPUP_CLOSE_BTN_JS)
    if cb:
        await page.mouse.click(cb["x"], cb["y"])
    else:
        await page.keyboard.press("Escape")
    await page.wait_for_timeout(700)


async def do_fill_search(page: Any, field: str, query: str, value: str) -> str:
    """검색형 코드피커 채우기. '프로젝트'는 검증된 §B PROJECT_*_JS, 그 외는 일반화(미검증)."""
    verified = field == "프로젝트"
    if verified:
        box = await page.evaluate(js_lib.PROJECT_PICKER_BOX_JS)
    else:
        box = await page.evaluate(CARD_PICKER_BOX_JS, field)
    if not box:
        return f"fail: '{field}' 코드피커 버튼을 찾지 못함" + ("" if verified else " (미검증 필드)")
    await page.mouse.click(box["x"], box["y"])
    opened = False
    for _ in range(8):
        await page.wait_for_timeout(800)
        if verified:  # 프로젝트 팝업은 제목('프로젝트')으로 정확 판정.
            if await page.evaluate(js_lib.PROJECT_POPUP_OPEN_JS):
                opened = True
                break
        # 일반 코드피커는 제목이 '프로젝트'가 아니므로 .k-window 존재로 폴백 판정(미검증).
        elif await page.evaluate(_KWINDOW_ANY_JS):
            opened = True
            break
    if not opened:
        return f"fail: '{field}' 팝업이 열리지 않음" + ("" if verified else " (미검증)")
    await page.wait_for_timeout(800)
    if query:  # 화면 검색(있으면)으로 좁힌다.
        if verified:
            await page.evaluate(js_lib.PROJECT_SEARCH_SET_JS, query)
        else:
            await page.evaluate(CARD_POPUP_SEARCH_JS, query)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(1_200)
    if verified:
        v = _norm_project(value)

        def _has_match(options: list) -> bool:
            return any(
                v and v in _norm_project(o.get("label", "") + o.get("value", "") + o.get("description", ""))
                for o in options
            )

        res = await page.evaluate(js_lib.PROJECT_READ_JS, 25)
        opts = res.get("options") or []
        if not _has_match(opts):
            # 더존 검색 0건/무매칭이면 검색어 완화 재시도: 공백→'_' → 첫 토큰.
            base_q = (query or value).strip()
            for cand_q in (base_q.replace(" ", "_"), re.split(r"[\s_]+", base_q)[0] if base_q else ""):
                cand_q = cand_q.strip()
                if not cand_q:
                    continue
                await page.evaluate(js_lib.PROJECT_SEARCH_SET_JS, cand_q)
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(1_200)
                res = await page.evaluate(js_lib.PROJECT_READ_JS, 25)
                opts = res.get("options") or []
                if _has_match(opts):
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
            return (
                f"ambiguous: '{value}' 에 일치하는 프로젝트가 여러 개입니다(후보: {cand}). "
                "임의 선택하지 말고 사용자에게 어느 것인지 ask 로 물어보세요."
            )
        else:
            return f"fail: 프로젝트 '{value}' 와 일치하는 결과가 없음(검색어를 좁혀 다시 요청)"
        sel = await page.evaluate(js_lib.PROJECT_SELECT_JS, match["value"])
        if not sel.get("ok"):
            return f"fail: 프로젝트 '{value}' 행 선택 실패"
        await page.wait_for_timeout(400)
        ab = await page.evaluate(js_lib.PROJECT_APPLY_BOX_JS)
        if ab:
            await page.mouse.click(ab["x"], ab["y"])
        await page.wait_for_timeout(1_200)
        return f"ok: 프로젝트 '{sel.get('name') or value}' 선택·적용(검증)"
    # 미검증 일반 코드피커: 값 일치 행 선택 → 적용.
    sel = await page.evaluate(CARD_POPUP_SELECT_JS, value)
    if not sel.get("ok"):
        return f"fail(미검증): '{field}' 행 '{value}' 선택 실패 ({sel.get('reason')})"
    await page.wait_for_timeout(400)
    ab = await page.evaluate(CARD_POPUP_APPLY_BOX_JS)
    if ab:
        await page.mouse.click(ab["x"], ab["y"])
    await page.wait_for_timeout(1_000)
    return f"ok(미검증): '{field}' = '{value}' 선택·적용 시도"


async def do_fill_dropdown(page: Any, field: str, value: str) -> str:
    """Kendo 드롭다운 채우기(미검증). 위젯 .value() + change 필수."""
    r = await page.evaluate(CARD_DROPDOWN_SET_JS, [field, value])
    if not r.get("ok"):
        opts = r.get("opts")
        extra = f" (가능옵션: {opts})" if opts else ""
        return f"fail(미검증): 드롭다운 '{field}' = '{value}' 설정 실패 ({r.get('reason')}){extra}"
    return f"ok(미검증): 드롭다운 '{field}' = '{r.get('text', value)}'"


async def do_fill_text(page: Any, field: str, value: str) -> str:
    """텍스트/날짜/카드번호 입력 채우기(미검증)."""
    r = await page.evaluate(CARD_TEXT_SET_JS, [field, value])
    if not r.get("ok"):
        return f"fail(미검증): 입력 '{field}' = '{value}' 채우기 실패 ({r.get('reason')})"
    return f"ok(미검증): 입력 '{field}' = '{value}'"


async def do_budget(page: Any, use_item: str, division: str) -> tuple[str, str]:
    """예산단위 채움 — 사용항목→검색어→부서매칭→(제/판 모호 시 ambiguous). 반환 (status, message).

    status: ok | ambiguous | fail | unsupported. 검증: 야근식대(인사기획팀·석식) 라이브 확인.
    """
    bm = budget_for(use_item)
    if not bm:
        return ("unsupported", f"'{use_item}'는 예산단위 매핑에 없는 사용항목입니다.")
    keyword, acct_sub = bm
    # 이전 팝업이 카드 모달 위에 떠 있으면 닫는다(2차 호출 시 코드피커 가려짐 방지).
    await close_top_popup(page)
    box = await page.evaluate(CARD_PICKER_BOX_JS, "예산단위")
    if not box:
        return ("fail", "예산단위 코드피커 버튼을 못 찾음")
    await page.mouse.click(box["x"], box["y"])
    opened = False
    for _ in range(8):
        await page.wait_for_timeout(700)
        if await page.evaluate(_KWINDOW_ANY_JS):
            opened = True
            break
    if not opened:
        return ("fail", "예산단위 팝업이 열리지 않음")
    await page.wait_for_timeout(600)
    await page.evaluate(POPUP_SET_KEYWORD_JS, keyword)
    qb = await page.evaluate(POPUP_QUERY_BTN_JS)
    if qb:
        await page.mouse.click(qb["x"], qb["y"])
        await page.wait_for_timeout(1_500)
    rd = await page.evaluate(BUDGET_READ_JS)
    rows = rd.get("rows") or []
    dept = rd.get("dept", "")
    asub = norm_item(acct_sub)
    nd = norm_item(dept)
    # 부서(BG_NM) + 예산계정(BGACCT_NM) 매칭.
    cand = [r for r in rows if asub in norm_item(r["acct"]) and nd and norm_item(r["bg"]) == nd]
    if not cand:  # 부서 불일치 시 예산계정만으로(폴백).
        cand = [r for r in rows if asub in norm_item(r["acct"])]
    if not cand:
        await close_top_popup(page)  # 팝업 닫기(다음 시도 위해)
        return ("fail", f"'{keyword}' 검색에서 예산계정 '{acct_sub}'(부서 {dept})를 못 찾음")
    # 제/판 필터(division 주어지면).
    if division:
        dv = "(제)" if "제" in division else ("(판)" if "판" in division else "")
        if dv:
            cand = [r for r in cand if r["acct"].startswith(dv)] or cand
    if len(cand) > 1:
        await close_top_popup(page)  # 팝업 닫기 — 제/판 답 받아 재시도.
        opts = " / ".join(f"{r['bg']}·{r['biz']}·{r['acct']}" for r in cand[:6])
        return ("ambiguous", f"예산단위가 여러 개입니다(제조/판매 등): {opts}. 제조/판매 중 무엇인가요?")
    sel = await page.evaluate(BUDGET_SELECT_JS, cand[0]["idx"])
    if not sel.get("ok"):
        return ("fail", f"예산단위 행 선택 실패({sel.get('reason')})")
    await page.wait_for_timeout(300)
    ab = await page.evaluate(CARD_POPUP_APPLY_BOX_JS)
    if ab:
        await page.mouse.click(ab["x"], ab["y"])
    await page.wait_for_timeout(1_200)
    return ("ok", f"예산단위 '{cand[0]['acct']}' ({cand[0]['bg']}) 선택·적용")


async def do_account(page: Any) -> tuple[str, str]:
    """예산단위 후 자동축소된 계정을 자동 선택·적용. 보통 1건. 반환 (status, message)."""
    await close_top_popup(page)
    box = await page.evaluate(CARD_PICKER_BOX_JS, "계정")
    if not box:
        return ("fail", "계정 코드피커 버튼을 못 찾음")
    await page.mouse.click(box["x"], box["y"])
    opened = False
    for _ in range(8):
        await page.wait_for_timeout(700)
        if await page.evaluate(_KWINDOW_OVER1_JS):
            opened = True
            break
    if not opened:
        return ("fail", "계정 팝업이 열리지 않음")
    await page.wait_for_timeout(800)
    rd = await page.evaluate(ACCOUNT_READ_JS)
    rows = rd.get("rows") or []
    if not rows:  # 조회가 필요할 수 있음 — 한 번 눌러본다.
        qb = await page.evaluate(POPUP_QUERY_BTN_JS)
        if qb:
            await page.mouse.click(qb["x"], qb["y"])
            await page.wait_for_timeout(1_200)
            rd = await page.evaluate(ACCOUNT_READ_JS)
            rows = rd.get("rows") or []
    if not rows:
        await close_top_popup(page)
        return ("fail", "계정 후보가 없음")
    sel = await page.evaluate(ACCOUNT_SELECT_JS, 0)  # 자동축소(보통 1건) → 첫 행.
    if not sel.get("ok"):
        await close_top_popup(page)
        return ("fail", f"계정 행 선택 실패({sel.get('reason')})")
    await page.wait_for_timeout(300)
    ab = await page.evaluate(CARD_POPUP_APPLY_BOX_JS)
    if ab:
        await page.mouse.click(ab["x"], ab["y"])
    await page.wait_for_timeout(1_000)
    r0 = rows[0]
    acctnm = next((str(v) for k, v in r0.items() if ("NM" in k.upper() or "명" in k) and v), "자동")
    return ("ok", f"계정 '{acctnm}' 선택·적용(자동, {rd.get('n')}건)")
