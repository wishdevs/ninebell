"""프로브 — 참조문서 dialog **'아래(↓) 이동'** 성립 조건 실측(H1~H6) + **'확인' 클릭·첨부표시**
실측(P1~P5, E2E_REFDOC_CONFIRM=1 일 때만).

오케스트레이터 지시(2026-08-07): 문서번호 검색까지는 되는데 '아래' 버튼으로 '참조문서 목록'
→'선택된 문서 목록' 이동이 실기기에서 안 된다는 사용자 리포트를 실측으로 확정한다.

가설(순서대로, 각각 증거를 남긴다):
  H1. 체크박스 클릭 → REFDOC_TOP_CHECKED_JS 로 체크 반영 확인 + 상단 그리드 gridView 의
      사용 가능한 메서드 전체 목록 덤프(Object.keys + prototype chain).
  H2. move 후보 버튼(0,1) 각각 — 클릭 전후 class/disabled/img src 덤프 + 선택 목록 count 변화.
      실마우스 좌표 클릭과 el.click() 두 방식 비교.
  H3. 체크가 아니라 행 선택(포커스)이 이동 조건인가 — 행 중앙 클릭 후 버튼 → count 변화.
  H4. gridView API 직접 체크(H1 덤프에서 찾은 체크 API) → 버튼 → count 변화.
  H5. 행 dblclick 이 이동 제스처인가 — dblclick 단독, dblclick+버튼 각각 확인.
  H6. 이동 성립 조합을 찾으면: (a) count==1 + 문서번호 일치, (b) dialog 닫았다 다시 열어도
      선택 목록 유지되는지, (c) 반대 버튼으로 원복 가능한지 확인 후 원복.

후속 임무(2026-08-07, 사용자 명시 승인 — E2E_REFDOC_CONFIRM=1 일 때만 활성화. 이 모드에서는
H3~H6(대조군·원복)을 건너뛰고 H1+H2(성공) 직후 곧장 P1~P5 로 진행한다 — 이미 확정된 가설을
재검증하며 결제창을 더 열 필요가 없다):
  P1. 확정 시퀀스(체크박스 → arrBtnDown)로 선택 목록 1건을 만든 뒤 **확인** 클릭
      (`csteps.click_refdoc_confirm` 재사용) → dialog 소멸 확인.
  P2. 확인 직후 **EAP 본문**(dialog 밖)에서 첨부 표시가 어떻게 바뀌는지 — 확인 전/후 비교.
  P3. 확인 후 참조문서 dialog 를 다시 열면 '선택된 문서 목록'이 어떻게 보이는지.
  P4. 결제창을 상신 없이 close 했다가 **같은 전표의 결제창을 다시 열어** P2 리더로 재확인 —
      첨부 표시가 남아 있는지(영속성). 남아 있어도 지우려 시도하지 않는다(사실만 보고).
  P5. 확인 클릭이 거절되는 케이스(필수값 경고 등)가 있으면 기록.

⚠ 절대 안전: 기본 모드(H1~H6)는 참조문서 '확인' 버튼 클릭 금지(게이트 유지) — 상신·보관도
  항상 금지. E2E_REFDOC_CONFIRM=1 일 때만 '확인' 클릭이 허용된다(사용자 명시 승인, 상신·보관은
  이 모드에서도 여전히 금지). 결제창은 필요한 만큼만 열되 6회를 넘기지 않는다. 기본 모드에서는
  '선택된 문서 목록'에 무엇이 담기든 확인을 누르지 않는 한 비영속이라(팝업 close 로 discard)
  여러 행을 시험해도 실 전표에 영향 없음.

Usage:
    cd backend && .venv/bin/python e2e/voucher_card_refdoc_move_probe.py
    cd backend && E2E_REFDOC_CONFIRM=1 .venv/bin/python e2e/voucher_card_refdoc_move_probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from playwright.async_api import async_playwright  # noqa: E402

from app.agents.voucher_card import js as cjs  # noqa: E402
from app.agents.voucher_card import steps as csteps  # noqa: E402
from app.agents.voucher_receivable import steps as vr_steps  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.live.runner import LIVE_VIEWPORT, _ScaledPage  # noqa: E402
from nbkit.omnisol.menu_schemas import VOUCHER_RECEIVABLE  # noqa: E402
from nbkit.patterns.login_flow import ensure_logged_in  # noqa: E402
from nbkit.patterns.menu_navigate_flow import navigate_schema  # noqa: E402
from nbkit.patterns.user_type_flow import ensure_user_type  # noqa: E402

USERID = os.environ.get("E2E_USERID", "이트라이브2")
PASSWORD = os.environ.get("E2E_PASSWORD", "1111")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"
DELAY_SCALE = float(os.environ.get("E2E_DELAY_SCALE", "0.4"))  # 프로덕션 voucher 계열 기본값.
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

# 이번 달만으로는 ABDOCU_NO 보유 행이 0건일 수 있다(실측: 2026-08 현재 1건뿐이고 그마저 미보유) —
# 결제창 도달 가능성을 위해 최근 수개월로 넓힌다(가설 검증 목적, 실 업무 조회기간과 무관).
PERIOD_START = os.environ.get("E2E_REFDOC_PERIOD_START", "20260201")
PERIOD_END = os.environ.get("E2E_REFDOC_PERIOD_END", "20260807")

# 2026-08-07 후속 임무 — 사용자가 명시 승인한 경우에만 '확인' 클릭을 허용한다(기본 OFF).
CONFIRM_MODE = os.environ.get("E2E_REFDOC_CONFIRM", "0") == "1"


# ══════════════════════════════════════════════════════════════════════════════
# 프로브 전용 JS — 프로덕션 REFDOC_MARK_JS('move')/REFDOC_TOP_CHECKED_JS 와 같은 dlg 탐색·
# 필터 로직을 그대로 미러링하되, 마킹 대신 **후보 전체 상태를 반환**한다(진단용, 읽기전용).
# ══════════════════════════════════════════════════════════════════════════════

_DLG_FIND = r"""
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const heading = [...document.querySelectorAll('*')].find(
    el => el.children.length === 0 && c(el.innerText) === '참조문서');
  let dlg = heading;
  for (let i = 0; i < 8 && dlg; i++) {
    const r = dlg.getBoundingClientRect();
    if (r.width > 400 && r.height > 300) break;
    dlg = dlg.parentElement;
  }
"""

MOVE_BTNS_STATE_JS = r"""() => {""" + _DLG_FIND + r"""
  if (!dlg) return { ok: false, reason: 'no-dialog' };
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
    if (!(b.offsetParent !== null && !b.disabled) || c(b.innerText)) return false;
    const cls = (b.className || '').toString();
    if (/OBTPagination/.test(cls) || b.closest('[class*=OBTPagination]')) return false;
    if (!/OBTButton_root/.test(cls)) return false;
    const r = b.getBoundingClientRect();
    return r.top >= gapTop && r.bottom <= gapBottom && r.width <= 40 && r.height <= 40;
  }).sort((a, b) => a.getBoundingClientRect().x - b.getBoundingClientRect().x);
  return {
    ok: true, count: cands.length, gapTop: Math.round(gapTop), gapBottom: Math.round(gapBottom),
    items: cands.map((b, i) => {
      const r = b.getBoundingClientRect();
      const img = b.querySelector('img');
      return {
        index: i, disabled: !!b.disabled, cls: (b.className || '').toString().slice(0, 100),
        html: b.innerHTML.slice(0, 150),
        imgSrc: img ? (img.getAttribute('src') || '').slice(-70) : null,
        rect: { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
                 w: Math.round(r.width), h: Math.round(r.height) },
      };
    }),
  };
}"""

# H1 — 상단(또는 하단) 그리드 gridView 의 **모든 함수형 프로퍼티**(own + prototype chain).
GRIDVIEW_METHODS_JS = r"""(which) => {""" + _DLG_FIND + r"""
  if (!dlg) return { ok: false, reason: 'no-dialog' };
  const views = [];
  for (const el of dlg.querySelectorAll('[id^=grid_]')) {
    if (el.gridView) views.push({ y: Math.round(el.getBoundingClientRect().y), gv: el.gridView, id: el.id });
  }
  if (views.length < 2) return { ok: false, reason: 'grids-not-ready', found: views.length };
  views.sort((a, b) => a.y - b.y);
  const target = which === 'bottom' ? views[1] : views[0];
  const gv = target.gv;
  const ownKeys = Object.keys(gv);
  const methods = new Set();
  let proto = Object.getPrototypeOf(gv), hops = 0;
  while (proto && proto !== Object.prototype && hops < 12) {
    for (const name of Object.getOwnPropertyNames(proto)) {
      try { if (typeof gv[name] === 'function') methods.add(name); } catch (e) {}
    }
    proto = Object.getPrototypeOf(proto);
    hops++;
  }
  const all = [...methods].sort();
  const relevant = all.filter(n => /check|Check|select|Select|focus|Focus|current|Current|^row|Row|item|Item/.test(n));
  return {
    ok: true, gridId: target.id, ownKeysCount: ownKeys.length, ownKeysSample: ownKeys.slice(0, 30),
    methodCount: all.length, methods: all, relevant,
  };
}"""

# H4 — gridView API 로 특정 행을 직접 체크/선택 시도(존재하는 메서드만 호출, 실패는 흡수).
GRIDVIEW_TRY_CHECK_JS = r"""(payload) => {
  const { which, itemIndex, apiNames } = payload;""" + _DLG_FIND + r"""
  if (!dlg) return { ok: false, reason: 'no-dialog' };
  const views = [];
  for (const el of dlg.querySelectorAll('[id^=grid_]')) {
    if (el.gridView) views.push({ y: Math.round(el.getBoundingClientRect().y), gv: el.gridView });
  }
  if (views.length < 2) return { ok: false, reason: 'grids-not-ready' };
  views.sort((a, b) => a.y - b.y);
  const gv = which === 'bottom' ? views[1].gv : views[0].gv;
  const tried = [];
  for (const name of apiNames) {
    if (typeof gv[name] !== 'function') { tried.push({ name, exists: false }); continue; }
    try {
      gv[name](itemIndex, true);
      tried.push({ name, exists: true, called: true });
    } catch (e) {
      try {
        gv[name](itemIndex);
        tried.push({ name, exists: true, called: true, arity1: true });
      } catch (e2) {
        tried.push({ name, exists: true, called: false, error: String(e2).slice(0, 80) });
      }
    }
  }
  return { ok: true, tried };
}"""

# 하단(선택된 문서 목록) 그리드의 체크된 행 수 — REFDOC_TOP_CHECKED_JS 미러(대상만 bottom).
BOTTOM_CHECKED_JS = r"""() => {""" + _DLG_FIND + r"""
  if (!dlg) return { ok: false, reason: 'no-dialog' };
  const views = [];
  for (const el of dlg.querySelectorAll('[id^=grid_]')) {
    if (el.gridView) views.push({ y: Math.round(el.getBoundingClientRect().y), gv: el.gridView });
  }
  if (views.length < 2) return { ok: false, reason: 'grids-not-ready' };
  views.sort((a, b) => a.y - b.y);
  const gv = views[1].gv;
  try {
    for (const f of ['getCheckedRows', 'getCheckedItems']) {
      if (typeof gv[f] !== 'function') continue;
      const arr = gv[f]();
      if (Array.isArray(arr)) return { ok: true, checked: arr.length, api: f };
    }
    return { ok: false, reason: 'no-check-api' };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 80) }; }
}"""


# P2 — EAP 본문(dialog 밖)의 '참조문서' 행 + '첨부파일' 행 상태를 읽는다. dialog 가 닫혀 있어도
# 동작해야 하므로 REFDOC_SELECT_BTN_RECT_JS 와 같은 **문서 전체 탐색**(dialog 스코프 아님)을
# 쓴다 — 확인 클릭 전/후 비교로 '첨부됨' 표시 방식을 실측 확정하는 것이 목적.
# 반환 스키마(js.py 이식 후보): {ok, count, docNos, refdocRowText, attachText, noneMarker}.
#   count    : 행 텍스트에서 찾은 건수 후보(정규식 매치, 없으면 null — 표시 방식에 따라 다를 수 있음)
#   docNos   : 행 텍스트에 포함된 문서번호 패턴('(주)나인벨-YYYY-NNNNN') 전량
#   noneMarker: '선택된 문서가 없습니다' 문구 포함 여부(미확인 상태의 확실한 앵커)
EAP_BODY_STATE_JS = r"""() => {
  const c = s => String(s==null?'':s).replace(/\s+/g,' ').trim();
  const btn = [...document.querySelectorAll('button')].find(b => {
    const row = b.closest('tr') || b.closest('li') || (b.parentElement && b.parentElement.parentElement);
    return row && c(row.innerText).replace(/\s+/g,'').includes('참조문서');
  });
  const row = btn ? (btn.closest('tr') || btn.closest('li') || (btn.parentElement && btn.parentElement.parentElement)) : null;
  const refdocRowText = row ? c(row.innerText) : null;
  const re = /\(주\)나인벨-\d{4}-\d+/g;
  const docNos = refdocRowText ? [...new Set(refdocRowText.match(re) || [])] : [];
  let count = null;
  if (refdocRowText) {
    const m = refdocRowText.match(/(\d+)\s*건/) || refdocRowText.match(/\((\d+)\)/);
    if (m) count = parseInt(m[1], 10);
  }
  const attachLabel = [...document.querySelectorAll('*')].find(
    el => el.children.length === 0 && /^첨부파일/.test(c(el.innerText)));
  const attachRow = attachLabel ? (attachLabel.closest('div') || attachLabel.parentElement) : null;
  const attachText = attachRow ? c(attachRow.innerText).slice(0, 150) : (attachLabel ? c(attachLabel.innerText) : null);
  return {
    ok: !!row, refdocRowText, docNos, count, attachText,
    noneMarker: refdocRowText ? refdocRowText.includes('선택된 문서가 없습니다') : null,
  };
}"""


# ══════════════════════════════════════════════════════════════════════════════
# 파이썬 헬퍼
# ══════════════════════════════════════════════════════════════════════════════

REPORT: dict[str, Any] = {"userid": USERID, "delay_scale": DELAY_SCALE, "attempts": []}


def log_attempt(hypo: str, action: str, result: str, classification: str | None = None) -> None:
    entry = {"hypothesis": hypo, "action": action, "result": result}
    if classification:
        entry["classification"] = classification
    REPORT["attempts"].append(entry)
    tag = f" [{classification}]" if classification else ""
    print(f"[{hypo}] {action} -> {result}{tag}", flush=True)


async def dump_json(name: str, obj: Any) -> None:
    (ARTIFACTS / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


async def selected_count(child: Any) -> int | None:
    g = await csteps.read_refdoc_grids(child)
    if not (isinstance(g, dict) and g.get("ok")):
        return None
    return (g.get("selected") or {}).get("count")


async def top_count(child: Any) -> int | None:
    g = await csteps.read_refdoc_grids(child)
    if not (isinstance(g, dict) and g.get("ok")):
        return None
    return (g.get("top") or {}).get("count")


async def poll_until(check, tries: int = 6, interval: float = 0.35):
    """조건이 참이 될 때까지 실시간 폴링(최대 tries 회). 마지막 판독값을 돌려준다."""
    last = None
    for _ in range(tries):
        last = await check()
        if last[0]:
            return last[1], True
        await asyncio.sleep(interval)
    return last[1] if last else None, False


async def click_checkbox(child: Any, box: dict, row: int = 0) -> None:
    y = box["y"] + csteps._GRID_HEADER_H + csteps._GRID_ROW_H * row + csteps._GRID_ROW_H // 2
    await child.mouse.click(box["x"] + csteps._GRID_CHECKBOX_DX, y)


async def click_row_center(child: Any, box: dict, row: int = 0) -> None:
    y = box["y"] + csteps._GRID_HEADER_H + csteps._GRID_ROW_H * row + csteps._GRID_ROW_H // 2
    await child.mouse.click(box["x"] + max(160, int(box.get("w", 300) * 0.4)), y)


async def dblclick_row_center(child: Any, box: dict, row: int = 0) -> None:
    y = box["y"] + csteps._GRID_HEADER_H + csteps._GRID_ROW_H * row + csteps._GRID_ROW_H // 2
    await child.mouse.dblclick(box["x"] + max(160, int(box.get("w", 300) * 0.4)), y)


async def ensure_row_checked(child: Any, row: int) -> dict:
    """상단 그리드 지정 행의 체크박스를 클릭하고 반영을 확인한다(이미 체크돼 있으면 재클릭하지
    않는다 — 체크박스라 재클릭은 **토글-해제**가 된다. 이 실수로 1차 재현에서 회귀가 났었다).

    ⚠ 상단(참조문서 목록)은 이동해도 그 행이 목록에서 사라지지 않는다(실측: 총 건수 불변,
      체크만 자동 해제) — 즉 **같은 행을 재사용하면 그 문서가 이미 선택 목록에 있어** '중복
      방지로 미이동'과 '그 제스처 자체가 안 통함'을 구분할 수 없다. 가설마다 **아직 손대지
      않은 새 행 인덱스**를 넘겨 이 confound 를 차단한다(호출부 책임 — 이 함수는 항상 단일
      행만 체크돼 있다는 불변조건을 전제한다).
    """
    chk = await child.evaluate(cjs.REFDOC_TOP_CHECKED_JS)
    if isinstance(chk, dict) and chk.get("ok") and (chk.get("checked") or 0) >= 1:
        return chk
    st = await csteps.read_refdoc_state(child)
    box = st.get("topGrid") if isinstance(st, dict) else None
    if not box:
        return {"ok": False, "reason": "no-topGrid"}
    await click_checkbox(child, box, row=row)
    await asyncio.sleep(0.3)
    return await child.evaluate(cjs.REFDOC_TOP_CHECKED_JS)


async def try_move(child: Any, index: int, method: str) -> dict:
    """move 후보 버튼(index)을 지정 방식(mouse|el.click)으로 눌러 selected count 변화를 관찰."""
    dump_before = await child.evaluate(MOVE_BTNS_STATE_JS)
    item = None
    if isinstance(dump_before, dict) and dump_before.get("ok"):
        item = next((it for it in dump_before.get("items", []) if it["index"] == index), None)
    if not item:
        return {"ok": False, "reason": "button-not-found", "index": index, "method": method}
    pre = await selected_count(child)
    if method == "mouse":
        await child.mouse.click(item["rect"]["x"], item["rect"]["y"])
    else:
        await child.evaluate(
            r"""(rect) => {
                  const el = document.elementFromPoint(rect.x, rect.y);
                  const btn = el && el.closest ? el.closest('button') : null;
                  if (btn) btn.click();
                  return !!btn;
                }""",
            item["rect"],
        )

    async def _check():
        c = await selected_count(child)
        return (c is not None and pre is not None and c > pre), c

    after, grew = await poll_until(_check, tries=6, interval=0.35)
    dump_after = await child.evaluate(MOVE_BTNS_STATE_JS)
    return {
        "ok": True, "index": index, "method": method, "pre": pre, "after": after, "grew": grew,
        "before_state": item, "after_state": dump_after,
    }


async def run_h3_h6(child: Any, methods: Any, n_candidates: int, h2_success: dict | None) -> None:
    """H3(행 포커스 대조군)~H6(영속성·재오픈·원복) — 기본 모드 전용(CONFIRM_MODE 에서는 건너뜀)."""
    # ══════════════════════ H3 — 체크 대신 행 포커스(중앙 클릭)만 ══════════════════════
    st3 = await csteps.read_refdoc_state(child)
    box3 = st3.get("topGrid") if isinstance(st3, dict) else None
    if box3 and n_candidates:
        pre3 = await selected_count(child)
        await click_row_center(child, box3, row=2)  # 새 행(row0/1 은 이미 선택 목록에 있음).
        await asyncio.sleep(0.3)
        chk3 = await child.evaluate(cjs.REFDOC_TOP_CHECKED_JS)
        use_idx = h2_success["index"] if h2_success else 0
        res3 = await try_move(child, use_idx, "mouse")
        log_attempt(
            "H3", f"행 중앙 클릭(체크박스 미클릭, checked={chk3}) 후 버튼 index={use_idx}",
            f"pre={res3.get('pre')} after={res3.get('after')} grew={res3.get('grew')}",
            "체크없이는 미이동(예상대로)" if not res3.get("grew") else "⚠ 체크 없이도 이동됨(가설 위반)",
        )
        await child.screenshot(path=str(ARTIFACTS / "refdoc_move_probe_h3_row_center.png"))
        REPORT["h3"] = {"checked_state": chk3, "pre": pre3, "move_result": res3}
    else:
        log_attempt("H3", "topGrid/버튼 후보 없음", "스킵", "선행조건 미충족")

    # ══════════════════════ H4 — gridView API 직접 체크 ══════════════════════
    candidate_apis = ["checkItem", "setCheck", "checkRow", "setChecked", "setRowChecked", "toggleCheck"]
    if isinstance(methods, dict) and methods.get("ok"):
        # H1 덤프에서 발견된 실제 존재 메서드를 우선순위에 추가(중복 제거, 발견분 먼저).
        found = [m for m in methods.get("methods", []) if m in candidate_apis]
        candidate_apis = found + [m for m in candidate_apis if m not in found]
    h4_api_result = await child.evaluate(
        # 새 행(row3) — row0~2 는 이미 선택 목록에 있거나(0) 체크 시도로 손댔다(2).
        GRIDVIEW_TRY_CHECK_JS, {"which": "top", "itemIndex": 3, "apiNames": candidate_apis}
    )
    REPORT["h4_api_tried"] = h4_api_result
    existing_apis = [t for t in (h4_api_result.get("tried") or []) if t.get("exists")]
    print(f"[H4] 시도한 API: {json.dumps(h4_api_result, ensure_ascii=False)[:500]}", flush=True)
    if existing_apis:
        await asyncio.sleep(0.3)
        chk4 = await child.evaluate(cjs.REFDOC_TOP_CHECKED_JS)
        use_idx = h2_success["index"] if h2_success else 0
        res4 = await try_move(child, use_idx, "mouse")
        log_attempt(
            "H4", f"gridView API({[t['name'] for t in existing_apis]}) 로 행0 체크 후 버튼",
            f"checked후={chk4} pre={res4.get('pre')} after={res4.get('after')} grew={res4.get('grew')}",
        )
        REPORT["h4"] = {"checked_state": chk4, "move_result": res4}
        await child.screenshot(path=str(ARTIFACTS / "refdoc_move_probe_h4_api_check.png"))
    else:
        log_attempt("H4", "체크 API 미존재(top grid gridView)", "스킵", "API부재")

    # ══════════════════════ H5 — 행 dblclick ══════════════════════
    st5 = await csteps.read_refdoc_state(child)
    box5 = st5.get("topGrid") if isinstance(st5, dict) else None
    if box5:
        pre5a = await selected_count(child)
        await dblclick_row_center(child, box5, row=4)  # 새 행 — 앞선 가설이 손댄 0~3 회피.
        await asyncio.sleep(0.4)
        after5a = await selected_count(child)
        log_attempt(
            "H5", f"행 dblclick 단독 pre={pre5a} after={after5a}",
            f"grew={after5a is not None and pre5a is not None and after5a > pre5a}",
        )
        if not (after5a is not None and pre5a is not None and after5a > pre5a) and n_candidates:
            use_idx = h2_success["index"] if h2_success else 0
            res5 = await try_move(child, use_idx, "mouse")
            log_attempt(
                "H5", f"행 dblclick 후 버튼 index={use_idx}",
                f"pre={res5.get('pre')} after={res5.get('after')} grew={res5.get('grew')}",
            )
            REPORT["h5_after_button"] = res5
        REPORT["h5_dblclick_alone"] = {"pre": pre5a, "after": after5a}
        await child.screenshot(path=str(ARTIFACTS / "refdoc_move_probe_h5_dblclick.png"))
    else:
        log_attempt("H5", "topGrid box 없음", "스킵", "선행조건 미충족")

    # ══════════════════════ H6 — 이동 성립 시: 영속성·재오픈·원복 ══════════════════════
    if h2_success:
        g = await csteps.read_refdoc_grids(child)
        REPORT["h6_grid_after_h2"] = g
        sel = (g.get("selected") or {}) if isinstance(g, dict) and g.get("ok") else {}
        log_attempt("H6a", "선택 목록 count/문서번호", f"count={sel.get('count')} docNos={sel.get('docNos')}")

        closed = await csteps.close_refdoc_dialog(child)
        await asyncio.sleep(0.4)
        reopened = await csteps.open_refdoc_dialog(child)
        log_attempt("H6b", f"dialog 닫기({closed})→재오픈", reopened)
        if reopened == "opened":
            g2 = await csteps.read_refdoc_grids(child)
            REPORT["h6_grid_after_reopen"] = g2
            sel2 = (g2.get("selected") or {}) if isinstance(g2, dict) and g2.get("ok") else {}
            persisted = (sel2.get("count") or 0) >= (sel.get("count") or 0) and (sel.get("count") or 0) > 0
            log_attempt(
                "H6b", f"재오픈 후 선택 목록 count={sel2.get('count')} docNos={sel2.get('docNos')}",
                "유지됨" if persisted else "소멸/불일치",
            )
            await child.screenshot(path=str(ARTIFACTS / "refdoc_move_probe_h6_reopened.png"))

            # 원복 — 다른 버튼 인덱스로 하단 행 체크 후 이동 시도.
            other_idx = 1 - h2_success["index"] if n_candidates >= 2 else None
            if other_idx is not None:
                st6 = await csteps.read_refdoc_state(child)
                bbox = st6.get("bottomGrid") if isinstance(st6, dict) else None
                if bbox:
                    await click_checkbox(child, bbox, row=0)
                    await asyncio.sleep(0.3)
                    chk6 = await child.evaluate(BOTTOM_CHECKED_JS)
                    pre6 = await selected_count(child)
                    res6 = await try_move(child, other_idx, "mouse")
                    reverted = (res6.get("after") or 0) < (pre6 or 0) if res6.get("after") is not None else False
                    log_attempt(
                        "H6c", f"하단 체크({chk6}) 후 반대버튼 index={other_idx}",
                        f"pre={pre6} after={res6.get('after')} reverted={reverted}",
                    )
                    REPORT["h6_revert"] = {"checked": chk6, "pre": pre6, "result": res6, "reverted": reverted}
                    await child.screenshot(path=str(ARTIFACTS / "refdoc_move_probe_h6_revert.png"))
                else:
                    log_attempt("H6c", "bottomGrid box 없음", "스킵")
            else:
                log_attempt("H6c", "반대 버튼 인덱스 없음(후보 1개뿐)", "스킵")
    else:
        log_attempt("H6", "H2 미성공 — 원복 대상 없음", "스킵")

    await csteps.close_refdoc_dialog(child)


async def run_p1_p5(child: Any) -> None:
    """P1~P5 — '확인' 클릭 + EAP 본문 첨부표시 실측(CONFIRM_MODE 전용, 사용자 명시 승인 2026-08-07).

    ⚠ 이 함수만 참조문서 '확인'을 클릭한다(csteps.click_refdoc_confirm 재사용). 상신·보관은
      여전히 어디서도 클릭하지 않는다. P4(영속성 재확인)는 호출부(main)가 결제창을 close 했다가
      **같은 전표로 다시 열어** 이 함수의 EAP_BODY_STATE_JS 리더로 재확인한다.
    """
    # ══════════════════════ P2(baseline) — 확인 전 EAP 본문 상태 ══════════════════════
    baseline = await child.evaluate(EAP_BODY_STATE_JS)
    REPORT["p2_baseline"] = baseline
    log_attempt("P2", "확인 전 EAP 본문 상태", json.dumps(baseline, ensure_ascii=False))
    await child.screenshot(path=str(ARTIFACTS / "refdoc_confirm_probe_p0_before_confirm.png"))

    # ══════════════════════ P1 — 확인 클릭 → dialog 소멸 확인(프로덕션 재사용) ══════════════════════
    confirmed = await csteps.click_refdoc_confirm(child)
    REPORT["p1_confirm_result"] = confirmed
    log_attempt(
        "P1", "참조문서 '확인' 클릭(csteps.click_refdoc_confirm)", json.dumps(confirmed, ensure_ascii=False),
        None if (isinstance(confirmed, dict) and confirmed.get("ok")) else "확인 클릭 실패/거절(P5 참조)",
    )
    await child.screenshot(path=str(ARTIFACTS / "refdoc_confirm_probe_p1_after_confirm.png"))
    if not (isinstance(confirmed, dict) and confirmed.get("ok")):
        # P5 — 거절 케이스: dialog 잔존 상태를 기록하고 종료(더 진행할 것이 없다).
        state_after_fail = await csteps.read_refdoc_state(child)
        REPORT["p5_confirm_rejected"] = state_after_fail
        log_attempt("P5", "확인 실패 후 dialog 상태", json.dumps(state_after_fail, ensure_ascii=False))
        return

    # ══════════════════════ P2 — 확인 직후 EAP 본문 상태(비교) ══════════════════════
    after_confirm = await child.evaluate(EAP_BODY_STATE_JS)
    REPORT["p2_after_confirm"] = after_confirm
    changed = json.dumps(baseline, ensure_ascii=False) != json.dumps(after_confirm, ensure_ascii=False)
    log_attempt(
        "P2", "확인 직후 EAP 본문 상태(baseline 대비 변화)", json.dumps(after_confirm, ensure_ascii=False),
        "변화 감지" if changed else "⚠ 변화 없음(리더 재검토 필요)",
    )

    # ══════════════════════ P3 — 참조문서 dialog 재오픈 시 선택 목록 표시 ══════════════════════
    reopened = await csteps.open_refdoc_dialog(child)
    log_attempt("P3", "확인 후 dialog 재오픈", reopened)
    if reopened == "opened":
        g3 = await csteps.read_refdoc_grids(child)
        REPORT["p3_grid_after_confirm_reopen"] = g3
        sel3 = (g3.get("selected") or {}) if isinstance(g3, dict) and g3.get("ok") else {}
        log_attempt("P3", "재오픈 후 선택 목록", f"count={sel3.get('count')} docNos={sel3.get('docNos')}")
        await child.screenshot(path=str(ARTIFACTS / "refdoc_confirm_probe_p3_reopened.png"))
        await csteps.close_refdoc_dialog(child)


async def main() -> int:  # noqa: C901 — 진단 스크립트, 단일 흐름 유지가 가독성에 유리.
    settings = get_settings()
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS)
    context = await browser.new_context(viewport=LIVE_VIEWPORT)
    raw_page = await context.new_page()
    page = _ScaledPage(raw_page, DELAY_SCALE)
    child = None
    popups_opened = 0

    try:
        await ensure_logged_in(page, USERID, PASSWORD, settings.erp_base)
        await ensure_user_type(page, "회계")
        await navigate_schema(page, VOUCHER_RECEIVABLE, settings.erp_base)

        # ── Phase A — 전표조회승인(전표유형=일반) 조회(프로덕션 진입과 동일) ──
        await vr_steps.expand_condition_panel(page)
        await vr_steps.set_dept_all(page)
        await vr_steps.set_period(page, PERIOD_START, PERIOD_END)
        await vr_steps.clear_writer(page)
        await vr_steps.set_docu_status(page)
        await vr_steps.set_gwaprvlst(page)
        r = await vr_steps.set_docu_types(page, csteps.DOCU_TYPES_CARD)
        if not r.get("ok"):
            print(f"[FAIL] 전표유형 세팅: {r}")
            return 1
        q = await vr_steps.run_query(page)
        if not q.get("ok") or int(q.get("rowcount") or 0) <= 0:
            print(f"[FAIL] 전표조회승인 0건: {q}")
            return 1
        print(f"[A] 전표조회승인 {q['rowcount']}건", flush=True)

        # ── Phase B — 결의서조회승인(결의구분=카드) 결재번호 맵 ──
        opened_tab = await csteps.open_collect_tab(page)
        if not opened_tab.get("ok"):
            print(f"[FAIL] 결의서조회승인 탭: {opened_tab}")
            return 1
        await csteps.set_collect_dept_all(page)
        await csteps.clear_collect_writer(page)
        await csteps.set_collect_period(page, PERIOD_START, PERIOD_END)
        if not await csteps.set_collect_gubun_card(page):
            print("[FAIL] 결의구분=카드 확인 실패")
            return 1
        if not await csteps.run_collect_query(page):
            print("[FAIL] 결의서조회승인 조회 확인 실패")
            return 1
        pm = await csteps.read_payment_map(page)
        payment_map = pm.get("map") or {}
        print(f"[B] 결재번호 맵 {len(payment_map)}건", flush=True)
        if not payment_map:
            print("[FAIL] 결재번호 맵 0건 — 결제창에 도달할 수 없음")
            return 1
        if not await csteps.switch_back_to_voucher_tab(page):
            print("[FAIL] 전표조회승인 탭 복귀 실패")
            return 1

        idx = None
        rowcount = int(q["rowcount"])
        seen_ab = []
        for i in range(rowcount):
            ab = await vr_steps.read_row_abdocu_no(page, i)
            ab = str(ab).strip() if ab else ""
            seen_ab.append(ab)
            if ab and ab in payment_map:
                idx = i
                break
        if idx is None:
            print(f"[FAIL] 결재번호 맵 매칭 행 없음 — 행 ABDOCU_NO={seen_ab} / 맵 키={list(payment_map.keys())}")
            return 1
        print(f"[C] 대상 행 idx={idx}", flush=True)

        # ── Phase C — 결제창(EAP) 1건만 연다 ──
        await vr_steps.uncheck_all_rows(page)
        await vr_steps.check_row(page, idx)
        child = await vr_steps.open_approval(page)
        if child is None:
            print("[FAIL] 결제창 미출현")
            return 1
        popups_opened += 1
        await vr_steps.poll_child_ready(child)
        print(f"[C] 결제창 열림({popups_opened}/6) url={child.url}", flush=True)

        # ── 참조문서 dialog 오픈 + 광범위 검색(문서번호 미필터 — 여러 행 확보) ──
        opened = await csteps.open_refdoc_dialog(child)
        REPORT["dialog_open"] = opened
        if opened != "opened":
            print(f"[FAIL] 참조문서 dialog 미개방: {opened}")
            await dump_json("refdoc_move_probe_report.json", REPORT)
            return 1
        await csteps.expand_refdoc_filter(child)
        base_state = await csteps.read_refdoc_state(child)
        prev_total = base_state.get("total") if isinstance(base_state, dict) else None
        if not await csteps.run_refdoc_search(child):
            print("[FAIL] 조회 버튼 클릭 실패")
            await dump_json("refdoc_move_probe_report.json", REPORT)
            return 1
        state = await csteps.poll_refdoc_result(child, prev_total=prev_total)
        total = state.get("total")
        print(f"[D] 조회 결과 total={total} noData={state.get('noData')} settled={state.get('settled')}", flush=True)
        REPORT["search_state"] = state
        await child.screenshot(path=str(ARTIFACTS / "refdoc_move_probe_00_search.png"))
        if state.get("noData") or not total:
            print("[FAIL] 참조문서 검색 결과 0건 — 가설 검증 불가(데이터 없음). 마지막 도달 지점=검색 완료.")
            await csteps.close_refdoc_dialog(child)
            await dump_json("refdoc_move_probe_report.json", REPORT)
            return 1

        # ══════════════════════ H1 ══════════════════════
        st = await csteps.read_refdoc_state(child)
        top_box = st.get("topGrid") if isinstance(st, dict) else None
        if not top_box:
            print("[FAIL] topGrid box 미확보")
            await dump_json("refdoc_move_probe_report.json", REPORT)
            return 1
        await click_checkbox(child, top_box, row=0)
        await asyncio.sleep(0.3)
        chk1 = await child.evaluate(cjs.REFDOC_TOP_CHECKED_JS)
        methods = await child.evaluate(GRIDVIEW_METHODS_JS, "top")
        REPORT["h1_checked"] = chk1
        REPORT["h1_gridview_methods"] = methods
        await dump_json("refdoc_move_probe_h1_methods.json", methods)
        log_attempt(
            "H1", "체크박스(+16px) 클릭 → REFDOC_TOP_CHECKED_JS",
            json.dumps(chk1, ensure_ascii=False),
            None if (isinstance(chk1, dict) and chk1.get("ok") and (chk1.get("checked") or 0) >= 1) else "체크반영불가",
        )
        if isinstance(methods, dict) and methods.get("ok"):
            print(f"[H1] gridView 메서드 {methods['methodCount']}개, 체크/선택 관련 후보={methods['relevant']}", flush=True)
        else:
            print(f"[H1] gridView 메서드 덤프 실패: {methods}", flush=True)
        await child.screenshot(path=str(ARTIFACTS / "refdoc_move_probe_h1_checked.png"))

        # ══════════════════════ H2 ══════════════════════
        move_before = await child.evaluate(MOVE_BTNS_STATE_JS)
        REPORT["h2_buttons_before"] = move_before
        n_candidates = move_before.get("count", 0) if isinstance(move_before, dict) and move_before.get("ok") else 0
        print(f"[H2] move 버튼 후보 {n_candidates}개: {json.dumps(move_before, ensure_ascii=False)[:500]}", flush=True)

        h2_trials: list[dict] = []
        h2_success: dict | None = None
        for index in range(n_candidates):
            await ensure_row_checked(child, row=0)
            res = await try_move(child, index, "mouse")
            h2_trials.append(res)
            log_attempt(
                "H2", f"버튼 index={index} 실마우스클릭 pre={res.get('pre')} after={res.get('after')}",
                f"grew={res.get('grew')}", None if res.get("grew") else "미이동(원인 추정: 아래 H3~H5 로 분리)",
            )
            await child.screenshot(path=str(ARTIFACTS / f"refdoc_move_probe_h2_btn{index}_mouse.png"))
            if res.get("grew"):
                h2_success = res
                if CONFIRM_MODE:
                    # P1~P5 는 '선택 목록 정확히 1건' 상태에서 확인을 눌러야 한다 — el.click()
                    # 비교로 2건째를 더 만들지 않는다(H2 el.click() 비교는 기본 모드 전용).
                    break
                # el.click() 비교는 성공 버튼에 대해서만 — **새 행(row1)** 을 체크한다(row0 은
                # 이미 선택 목록에 있어 재사용하면 중복방지와 미작동을 구분할 수 없다).
                chk_before_el = await ensure_row_checked(child, row=1)
                res2 = await try_move(child, index, "el.click")
                h2_trials.append(res2)
                log_attempt(
                    "H2",
                    f"버튼 index={index} el.click() 비교(직전 체크상태={chk_before_el}) "
                    f"pre={res2.get('pre')} after={res2.get('after')}",
                    f"grew={res2.get('grew')}",
                )
                await child.screenshot(path=str(ARTIFACTS / f"refdoc_move_probe_h2_btn{index}_elclick.png"))
                break
        REPORT["h2_trials"] = h2_trials
        REPORT["h2_success"] = h2_success
        print(f"[H2] 성공 조합 = {h2_success and {'index': h2_success['index'], 'method': h2_success['method']}}", flush=True)

        if not CONFIRM_MODE:
            await run_h3_h6(child, methods, n_candidates, h2_success)
        elif h2_success:
            # ══════════════════════ P1~P3 — 확인 클릭 + EAP 본문 첨부표시(같은 팝업) ══════════
            await run_p1_p5(child)

            # ══════════════════════ P4 — 상신 없이 close → 같은 전표로 재오픈 → 영속성 재확인 ══
            confirmed_ok = isinstance(REPORT.get("p1_confirm_result"), dict) and REPORT["p1_confirm_result"].get("ok")
            if confirmed_ok:
                await vr_steps.close_child(child)
                print(f"[P4] 결제창 close(상신 없음) → 같은 전표(idx={idx}) 재오픈 시도", flush=True)
                await vr_steps.settle_parent_after_child_close(page, child)
                await vr_steps.uncheck_all_rows(page)
                await vr_steps.check_row(page, idx)
                child2 = await vr_steps.open_approval(page)
                if child2 is None:
                    log_attempt("P4", "같은 전표 재오픈", "실패(결제창 미출현)", "재오픈불가")
                else:
                    popups_opened += 1
                    await vr_steps.poll_child_ready(child2)
                    print(f"[P4] 재오픈 결제창({popups_opened}/6) url={child2.url}", flush=True)
                    reread = await child2.evaluate(EAP_BODY_STATE_JS)
                    REPORT["p4_reopened_state"] = reread
                    persisted = bool(reread.get("docNos")) or (reread.get("noneMarker") is False)
                    log_attempt(
                        "P4", "재오픈 결제창의 EAP 본문 상태(영속성)", json.dumps(reread, ensure_ascii=False),
                        "첨부 표시 유지" if persisted else "첨부 표시 소멸/미확인",
                    )
                    await child2.screenshot(path=str(ARTIFACTS / "refdoc_confirm_probe_p4_reopened.png"))
                    await vr_steps.close_child(child2)
                    child = None  # 아래 finally 가 이미 닫힌 원본 child 를 재-close 하지 않도록.
        else:
            log_attempt("P1", "H2 미성공 — 확인 클릭 대상 없음", "스킵")
            await csteps.close_refdoc_dialog(child)

    finally:
        if child is not None:
            try:
                await vr_steps.close_child(child)
                note = "상신/보관 미클릭" + ("" if not CONFIRM_MODE else " (확인은 CONFIRM_MODE 에서 클릭했을 수 있음)")
                print(f"[정리] 결제창 닫음({note})", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[경고] 결제창 닫기 실패(무시): {exc}", flush=True)
        REPORT["popups_opened"] = popups_opened
        await dump_json("refdoc_move_probe_report.json", REPORT)
        print(f"\n[artifact] {ARTIFACTS / 'refdoc_move_probe_report.json'}", flush=True)
        await browser.close()
        await pw.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
