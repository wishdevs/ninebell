"""법인카드 승인내역 정리 — 스텝 함수(진입 후 카드팝업 조작). js.py 프리미티브 사용.

각 함수는 Playwright page 를 받아 조작하고 결과를 반환한다(LangGraph 노드가 이 함수들을 호출).
⚠ 저장(F7)은 save_document(page, confirm=True) 로만, 명시적 confirm 일 때만 실행한다.
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Any

from . import js

# ── D2: 승인일 기간 계산 ─────────────────────────────────────────────────────────
# 오늘이 매월 10일 이전이면 전월(1일~말일), 10일 이후(포함)면 당월(1일~오늘).
DAY_CUTOFF = 10


def compute_period(today: date) -> tuple[str, str]:
    """(start, end) YYYY-MM-DD. 10일 이전=전월 전체, 10일 이후=당월 1일~오늘."""
    if today.day < DAY_CUTOFF:
        year = today.year - 1 if today.month == 1 else today.year
        month = 12 if today.month == 1 else today.month - 1
        last = calendar.monthrange(year, month)[1]
        return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last:02d}"
    return f"{today.year:04d}-{today.month:02d}-01", today.isoformat()


# ── 카드 전체선택 ────────────────────────────────────────────────────────────────
async def select_all_cards(page: Any) -> dict:
    """카드번호 돋보기 → '카드' 서브팝업 전체선택 → 적용. 반환 {ok, n}."""
    box = await page.evaluate(js.CARD_SEARCH_BTN_JS)
    if not box:
        return {"ok": False, "reason": "돋보기 버튼 없음(법인카드 팝업 아님?)"}
    await page.mouse.click(box["x"], box["y"])
    await page.wait_for_timeout(1_500)
    sel = await page.evaluate(js.CARD_SUB_SELECT_ALL_JS)
    if not sel.get("ok"):
        return {"ok": False, "reason": f"서브팝업 전체선택 실패: {sel}"}
    apply_box = await page.evaluate(js.CARD_SUB_APPLY_BTN_JS)
    if not apply_box:
        return {"ok": False, "reason": "서브팝업 '적용' 버튼 없음", "n": sel.get("n")}
    await page.mouse.click(apply_box["x"], apply_box["y"])
    await page.wait_for_timeout(1_000)
    return {"ok": True, "n": sel.get("n"), "checked": sel.get("checked")}


# ── 승인일 세팅 + 조회 ───────────────────────────────────────────────────────────
async def set_period(page: Any, start: str, end: str) -> dict:
    r = await page.evaluate(js.PERIOD_SET_JS, [start, end])
    ok = r.get("start") == start and r.get("end") == end
    return {"ok": ok, **r}


async def run_query(page: Any, timeout_polls: int = 8) -> int:
    """조회 클릭 후 rowcount 폴링. 반환 행 수(0 가능)."""
    box = await page.evaluate(js.QUERY_BTN_JS)
    if not box:
        return -1
    await page.mouse.click(box["x"], box["y"])
    rows = -1
    for _ in range(timeout_polls):
        await page.wait_for_timeout(1_200)
        rows = await page.evaluate(js.ROWCOUNT_JS)
        if isinstance(rows, int) and rows >= 0:
            # 그리드가 채워질 시간을 한 번 더 준 뒤 안정값.
            await page.wait_for_timeout(600)
            rows = await page.evaluate(js.ROWCOUNT_JS)
            if rows > 0:
                break
    return rows


async def read_rows(page: Any, limit: int = 200) -> list[dict]:
    r = await page.evaluate(js.READ_ROWS_JS, limit)
    return r.get("list") or []


# ── 적요(행별 인라인) ─────────────────────────────────────────────────────────────
async def set_note(page: Any, row: int, text: str) -> dict:
    return await page.evaluate(js.NOTE_SET_JS, [row, text])


# ── 코드피커(예산단위/계정/프로젝트) ──────────────────────────────────────────────
# field_id: bg_cd(예산단위)/acct_cd(계정)/pjt_cd(프로젝트). code/name 필드는 팝업 컬럼.
async def fill_codepicker(
    page: Any,
    field_id: str,
    keyword: str,
    code_field: str,
    name_field: str,
    pick_index: int = 0,
) -> dict:
    """코드피커 버튼→팝업→keyword 검색→pick_index 행 선택→적용. 반환 {ok, code, name}."""
    box = await page.evaluate(js.picker_btn_js(field_id))
    if not box:
        return {"ok": False, "reason": f"{field_id} 버튼 없음"}
    await page.mouse.click(box["x"], box["y"])
    await page.wait_for_timeout(1_500)
    if keyword:
        s = await page.evaluate(js.PICKER_SEARCH_JS, keyword)
        if s.get("ok"):
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(1_200)
    read = await page.evaluate(js.PICKER_READ_JS, [code_field, name_field, 25])
    opts = read.get("options") or []
    if not opts:
        return {"ok": False, "reason": f"{field_id} 검색결과 0건(keyword={keyword!r})", "rows": read.get("rows")}
    idx = pick_index if 0 <= pick_index < len(opts) else 0
    sel = await page.evaluate(js.PICKER_SELECT_JS, opts[idx]["i"])
    if not sel.get("ok"):
        return {"ok": False, "reason": f"{field_id} 행 선택 실패: {sel}"}
    await page.wait_for_timeout(400)
    apply_box = await page.evaluate(js.PICKER_APPLY_BTN_JS)
    if apply_box:
        await page.mouse.click(apply_box["x"], apply_box["y"])
        await page.wait_for_timeout(1_000)
    return {"ok": True, "code": opts[idx]["code"], "name": opts[idx]["name"]}


# ── 행 반영(일괄적용, 해당 행만 체크) / 저장(F7) ──────────────────────────────────
async def apply_row(page: Any, row: int) -> dict:
    """그 행만 체크 후 '일괄적용' 클릭(그 행에 폼값 반영). ⚠ 저장 아님."""
    chk = await page.evaluate(js.CHECK_ONLY_ROW_JS, row)
    if not chk.get("ok"):
        return {"ok": False, "reason": f"행 체크 실패: {chk}"}
    box = await page.evaluate(js.card_button_box_js("일괄적용"))
    if not box:
        return {"ok": False, "reason": "'일괄적용' 버튼 없음"}
    await page.mouse.click(box["x"], box["y"])
    await page.wait_for_timeout(1_200)
    return {"ok": True}


async def save_document(page: Any, confirm: bool) -> dict:
    """결의서 저장(F7). ⚠ confirm=True 일 때만 실제 클릭(테스트는 항상 False)."""
    if not confirm:
        return {"ok": False, "skipped": True, "reason": "SAVE 게이트 닫힘(테스트 모드)"}
    box = await page.evaluate(js.card_button_box_js("저장"))
    if not box:
        # 저장이 별도 버튼이 아니면 F7 키.
        await page.keyboard.press("F7")
        await page.wait_for_timeout(1_500)
        return {"ok": True, "via": "F7"}
    await page.mouse.click(box["x"], box["y"])
    await page.wait_for_timeout(1_500)
    return {"ok": True, "via": "button"}
