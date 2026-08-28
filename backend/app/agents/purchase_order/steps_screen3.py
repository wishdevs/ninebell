"""화면 ③ 구매발주일괄입력[나인벨] 스텝 — D8(구매요청 팝업 → 거래처 변경 → 적용) / D9(납기·비고 → 저장).

실측 근거: e2e/purchase_order_screen3_ops_probe.py(2026-08-28 헤디드 run2) + 사용자 시연 영상.
⚠ 💾 저장은 되돌릴 수단이 없는 비가역 — 노드의 confirm HITL 뒤에서만 호출된다(사용자 승인 2026-08-28 (a)).
"""

from __future__ import annotations

import re
from typing import Any

from nbkit.omnisol import latency, selectors, verify

from . import js, js_screen3 as j3
from .steps import POLL_MS
from .steps_write import (
    click_by_id,
    click_dialog_button,
    pick_code_document,
    scan_dialog,
    set_text_verified,
)

PO_TYPE_FIELD = "s_po_tp_cd"
PO_TYPE_NAME = "원재료"
BTN_REQ = "btn_req"
POPUP_PRQ_FIELD = "s_purreq_no"
POPUP_VENDOR_FIELD = "s_chg_partner_cd"
POPUP_APPLY_BTN = "btn_apply"
DUE_FIELD = "BFDEDT_DT"
DUE_APPLY_BTN = "btnApplyDT"
PSEUDO_VENDORS = ("가공품", "판금품")
PURDOC_PREFIX = "PO"  # 발주번호 접두 — ❓(저장 성공 신호는 PURDOC_NO 컬럼 채워짐으로 판정)
POPUP_CAP_MS = 20_000
SAVE_CAP_MS = 40_000
MASTER_HEADER_PX = 30
MASTER_ROW_PX = 32


def vendor_keyword(name: str) -> str:
    """거래처 코드피커 검색어 — 법인 접두/괄호 제거 후 첫 토큰('주식회사 해룡엔지니어링' → '해룡엔지니어링')."""
    s = re.sub(r"주식회사|\(주\)|（주）|㈜|유한회사", " ", name or "")
    toks = [t for t in s.replace(",", " ").split() if len(t) >= 2]
    return toks[0] if toks else (name or "").strip()


def norm(s: object) -> str:
    """거래처명 비교용 정규화 — 공백·법인 접두·괄호 제거."""
    return re.sub(r"\s+|주식회사|\(주\)|（주）|㈜", "", str(s or ""))


def vendor_group_for(unit: dict, vendor_name: str) -> dict | None:
    """마스터 거래처명 ↔ 계획서 vendorGroups[].vendor 부분일치(정규화) — 없으면 None."""
    target = norm(vendor_name)
    if not target:
        return None
    for g in unit.get("vendorGroups") or []:
        v = norm(g.get("vendor") or g.get("vendorClass"))
        if v and (v in target or target in v):
            return g
    return None


def plan_vendor_changes(unit: dict, rows: list[dict]) -> dict[str, list[int]]:
    """팝업 행(PRINCIPALPARTN_NM) 중 의사 거래처(가공품/판금품) → 계획서 실거래처명별 행 인덱스 묶음."""
    by_class = {g.get("vendorClass"): g.get("vendor") for g in unit.get("vendorGroups") or []}
    out: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        cls = str(r.get("PRINCIPALPARTN_NM") or "").strip()
        if cls in PSEUDO_VENDORS and by_class.get(cls):
            out.setdefault(str(by_class[cls]), []).append(i)
    return out


async def ensure_po_type(page: Any) -> dict:
    cur = await page.evaluate(js.INPUT_VALUE_JS, PO_TYPE_FIELD)
    if cur and PO_TYPE_NAME in str(cur):
        return {"ok": True, "unchanged": True}
    return await pick_code_document(page, PO_TYPE_FIELD, PO_TYPE_NAME)


async def _wait_popup(page: Any, present: bool, *, cap_ms: int = POPUP_CAP_MS) -> bool:
    waited = 0
    cap = latency.budget_ms(cap_ms)
    while waited < cap:
        st = await page.evaluate(j3.POPUP_PRESENT_JS) or {}
        if bool(st.get("present")) == present and (not present or "구매요청" in (st.get("title") or "")):
            return True
        await verify.DEFAULT_SLEEP(POLL_MS / 1000)
        waited += POLL_MS
    return False


async def open_request_popup(page: Any) -> dict:
    """`구매요청`(#btn_req) → 팝업 출현(자동 조회) 대기."""
    r = await click_by_id(page, BTN_REQ)
    if not r.get("ok"):
        return r
    if not await _wait_popup(page, True):
        return {"ok": False, "reason": "구매요청 팝업이 열리지 않았습니다."}
    # 자동 조회가 끝나 행수가 안정될 때까지(연속 2폴 동일).
    await _wait_popup_rows_stable(page)
    return {"ok": True}


async def _wait_popup_rows_stable(page: Any, *, cap_ms: int = POPUP_CAP_MS) -> int:
    waited = 0
    cap = latency.budget_ms(cap_ms)
    last = None
    while waited < cap:
        n = await page.evaluate(j3.POPUP_GRID_COUNT_JS, 0)
        if n is not None and n >= 0 and n == last:
            return int(n)
        last = n
        await verify.DEFAULT_SLEEP(0.6)
        waited += 600
    return int(last or -1)


async def popup_query_prq(page: Any, prq: str) -> dict:
    """구매요청번호 필드 + trusted Enter → 그 PRQ 라인만(프로브 ✅ 647→84, 팝업 소멸 없음)."""
    before = await page.evaluate(j3.POPUP_GRID_COUNT_JS, 0)
    r = await set_text_verified(page, POPUP_PRQ_FIELD, prq)
    if not r.get("ok"):
        return r
    await page.keyboard.press("Enter")
    await verify.DEFAULT_SLEEP(1.0)
    n = await _wait_popup_rows_stable(page)
    read = await page.evaluate(j3.POPUP_GRID_ROWS_JS, [0, 2000])
    rows = read.get("rows") or []
    other = [x for x in rows if str(x.get("PURREQ_NO") or "").strip() != prq]
    if not rows or other:
        return {
            "ok": False,
            "reason": f"{prq} 조회 결과가 그 요청번호만이 아닙니다(행 {len(rows)}, 타 요청 {len(other)}, 조회 전 {before}).",
            "rows": rows,
        }
    return {"ok": True, "rows": rows, "count": n}


async def popup_apply_vendor(page: Any, row_idxs: list[int], vendor_name: str) -> dict:
    """행 체크 → 변경거래처 코드피커(검색어) → #btn_apply → 체크 행의 CHG_PARTNER_NM 반영 확인."""
    await page.evaluate(j3.POPUP_CHECK_ALL_JS, [0, False])
    c = await page.evaluate(j3.POPUP_CHECK_ROWS_JS, [0, row_idxs])
    got = sorted(int(x) for x in (c.get("checked") or []))
    if not c.get("ok") or got != sorted(row_idxs):
        return {"ok": False, "reason": f"팝업 행 체크 불일치 — 기대 {len(row_idxs)} / 실제 {len(got)}"}
    kw = vendor_keyword(vendor_name)
    p = await pick_code_document(page, POPUP_VENDOR_FIELD, kw)
    if not p.get("ok"):
        return {"ok": False, "reason": f"변경거래처 '{kw}' 선택 실패 — {p.get('reason')}"}
    a = await click_by_id(page, POPUP_APPLY_BTN)
    if not a.get("ok"):
        return a
    await verify.DEFAULT_SLEEP(1.2)
    vals = await page.evaluate(j3.POPUP_FIELDS_JS, [0, row_idxs, ["CHG_PARTNER_NM", "CHG_PARTNER_CD"]])
    bad = [i for i in row_idxs if norm(kw) not in norm((vals.get(str(i)) or vals.get(i) or {}).get("CHG_PARTNER_NM"))]
    if bad:
        sample = (vals.get(str(bad[0])) or vals.get(bad[0]) or {})
        return {"ok": False, "reason": f"변경거래처 적용 미반영 행 {len(bad)}/{len(row_idxs)} — 예 {sample}"}
    codes = {str((vals.get(str(i)) or vals.get(i) or {}).get("CHG_PARTNER_CD")) for i in row_idxs}
    return {"ok": True, "display": p.get("display"), "codes": sorted(codes)}


async def popup_bottom_apply(page: Any, row_idxs: list[int]) -> dict:
    """대상 행 체크 → 하단 적용 → '적용하시겠습니까?' [예] → 팝업 닫힘 → 마스터 행수."""
    await page.evaluate(j3.POPUP_CHECK_ALL_JS, [0, False])
    c = await page.evaluate(j3.POPUP_CHECK_ROWS_JS, [0, row_idxs])
    if not c.get("ok") or len(c.get("checked") or []) != len(row_idxs):
        return {"ok": False, "reason": f"하단 적용 전 행 체크 불일치 — 기대 {len(row_idxs)} / 실제 {len(c.get('checked') or [])}"}
    box = await page.evaluate(j3.POPUP_BOTTOM_APPLY_BOX_JS)
    if not box:
        return {"ok": False, "reason": "팝업 하단 '적용' 버튼을 찾지 못했습니다."}
    await page.mouse.click(box["x"], box["y"])
    dlg = await scan_dialog(page, cap_ms=4_000)
    if dlg and dlg.get("buttons"):
        await click_dialog_button(page, "예" if "예" in dlg["buttons"] else dlg["buttons"][0])
    if not await _wait_popup(page, False):
        return {"ok": False, "reason": "하단 적용 후 팝업이 닫히지 않았습니다."}
    await verify.DEFAULT_SLEEP(1.0)
    n = await page.evaluate(j3.MAIN_GRID_COUNT_JS, 0)
    if not isinstance(n, int) or n <= 0:
        return {"ok": False, "reason": "하단 적용 후 본화면 마스터에 행이 생기지 않았습니다."}
    return {"ok": True, "master_rows": n}


async def master_rows(page: Any) -> list[dict]:
    r = await page.evaluate(j3.MAIN_GRID_ROWS_JS, [0, 200])
    return r.get("rows") or []


async def select_master_row(page: Any, idx: int) -> dict:
    """마스터 행 실 마우스 클릭(bbox 헤더 30px + 행 32px) → 디테일 재조회(행수>0) 확인."""
    rect = await page.evaluate(j3.MAIN_GRID_RECT_JS, 0)
    if not rect:
        return {"ok": False, "reason": "마스터 그리드 rect 미발견"}
    x = rect["x"] + 60
    y = rect["y"] + MASTER_HEADER_PX + MASTER_ROW_PX * idx + MASTER_ROW_PX // 2
    await page.mouse.click(x, y)
    waited = 0
    while waited < 8_000:
        n = await page.evaluate(j3.MAIN_GRID_COUNT_JS, 1)
        if isinstance(n, int) and n > 0:
            return {"ok": True, "detail_rows": n}
        await verify.DEFAULT_SLEEP(0.4)
        waited += 400
    return {"ok": False, "reason": f"마스터 {idx}행 클릭 후 디테일이 채워지지 않았습니다."}


async def apply_due_to_detail(page: Any, due: str) -> dict:
    """디테일 전체 체크 → #BFDEDT_DT + #btnApplyDT → BFDEDT_DT 반영(KST 날짜 비교)."""
    c = await page.evaluate(j3.MAIN_CHECK_ALL_JS, [1, True])
    n = c.get("after") or 0
    if not c.get("ok") or n <= 0:
        return {"ok": False, "reason": f"디테일 전체 체크 실패 — {c}"}
    r = await set_text_verified(page, DUE_FIELD, due)
    if not r.get("ok"):
        return r
    a = await click_by_id(page, DUE_APPLY_BTN)
    if not a.get("ok"):
        return a
    await verify.DEFAULT_SLEEP(1.0)
    vals = await page.evaluate(j3.MAIN_FIELDS_JS, [1, list(range(n)), [DUE_FIELD]])
    from .nodes.save_units import _digits  # KST 정규화 공유

    want = _digits(due)
    bad = [i for i in range(n) if _digits((vals.get(str(i)) or vals.get(i) or {}).get(DUE_FIELD)) != want]
    if bad:
        return {"ok": False, "reason": f"납기 {due} 미반영 디테일 행 {len(bad)}/{n}"}
    return {"ok": True, "rows": n}


async def set_master_note(page: Any, idx: int, text: str) -> dict:
    """마스터 RMK_DC 인라인 편집 — 에디터 오픈 → 전체선택 후 타이핑 → Tab → ds 값 독립 확인."""
    o = await page.evaluate(j3.MAIN_OPEN_EDITOR_JS, [idx, "RMK_DC"])
    if not o.get("ok"):
        return {"ok": False, "reason": f"비고 에디터 오픈 실패 — {o}"}
    await verify.DEFAULT_SLEEP(0.6)
    inp = await page.evaluate(j3.MAIN_EDITOR_INPUT_JS)
    if not inp:
        return {"ok": False, "reason": "비고 인라인 에디터 input 을 찾지 못했습니다."}
    await page.mouse.click(inp["x"], inp["y"])
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Meta+A")
    await page.keyboard.type(text, delay=15)
    await page.keyboard.press("Tab")
    await verify.DEFAULT_SLEEP(0.6)
    vals = await page.evaluate(j3.MAIN_FIELDS_JS, [0, [idx], ["RMK_DC"]])
    got = str((vals.get(str(idx)) or vals.get(idx) or {}).get("RMK_DC") or "")
    if got.strip() != text.strip():
        return {"ok": False, "reason": f"비고 커밋 확인 실패 — 기대 {text!r} / 실제 {got!r}"}
    return {"ok": True}


async def click_save_orders(page: Any, expect_rows: int) -> dict:
    """💾 저장 → '저장하시겠습니까?' [예] → 마스터 PURDOC_NO 발급으로 성공 판정(❓ 첫 실측)."""
    box = await page.evaluate(js.BOX_BY_SELECTOR_JS, selectors.BTN_SAVE)
    if not box or box.get("disabled"):
        return {"ok": False, "reason": "저장 버튼을 찾지 못했거나 비활성입니다."}
    await page.mouse.click(box["x"], box["y"])
    seen: list[str] = []
    dlg = await scan_dialog(page, cap_ms=4_000)
    if dlg:
        seen.append(f"dialog:{(dlg.get('text') or '')[:80]}{dlg.get('buttons')}")
        btns = dlg.get("buttons") or []
        if "저장" in (dlg.get("text") or "") or "예" in btns:
            await click_dialog_button(page, "예" if "예" in btns else btns[0])
        elif btns:
            return {"ok": False, "reason": f"저장 시 예상 밖 다이얼로그 — {dlg.get('text')!r}"}
    waited = 0
    cap = latency.budget_ms(SAVE_CAP_MS)
    while waited < cap:
        for s in await page.evaluate(js.SNACKBARS_JS) or []:
            txt = s.get("text") or ""
            if txt and f"snack:{txt}" not in seen:
                seen.append(f"snack:{txt}")
            if ("warning" in (s.get("cls") or "") or "error" in (s.get("cls") or "")) and txt:
                return {"ok": False, "reason": f"저장 실패 — {txt}"}
        rows = await master_rows(page)
        nos = [str(r.get("PURDOC_NO") or "").strip() for r in rows]
        if rows and all(nos):
            return {"ok": True, "numbers": nos}
        for d in await page.evaluate(js.DIALOGS_JS) or []:
            btns = d.get("buttons") or []
            if btns and len(btns) <= 2 and "프로젝트" not in (d.get("title") or ""):
                seen.append(f"dialog:{(d.get('text') or '')[:80]}{btns}")
                await click_dialog_button(page, btns[0])
                if any(w in (d.get("text") or "") for w in ("실패", "오류", "없습니다", "확인해")):
                    return {"ok": False, "reason": f"저장 후 안내 — {d.get('text')!r}"}
        await verify.DEFAULT_SLEEP(POLL_MS / 1000)
        waited += POLL_MS
    rows = await master_rows(page)
    return {
        "ok": False,
        "reason": f"저장 후 발주번호(PURDOC_NO)가 채워지지 않았습니다(마스터 {len(rows)}행, 기대 {expect_rows}) — 관측 {seen[:6]}",
    }
