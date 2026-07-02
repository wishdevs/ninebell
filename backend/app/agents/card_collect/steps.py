"""법인카드 승인내역 정리 — 스텝 함수(진입 후 카드팝업 조작). js.py 프리미티브 사용.

각 함수는 Playwright page 를 받아 조작하고 결과를 반환한다(LangGraph 노드가 이 함수들을 호출).
⚠ 저장(F7)은 save_document(page, confirm=True) 로만, 명시적 confirm 일 때만 실행한다.
"""

from __future__ import annotations

import calendar
import re
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


async def run_query(page: Any, timeout_polls: int = 20) -> int:
    """조회 클릭 후 rowcount 가 '안정'될 때까지 폴링. 반환 행 수(0 가능, -1=클릭 실패).

    느린 그리드에서 0을 실제 0건으로 오인하지 않도록, 같은 값이 2회 연속 관측될 때까지 기다린다
    (그동안 상한 폴링). 대부분 수 초 내 안정된다(리뷰 #8).
    """
    box = await page.evaluate(js.QUERY_BTN_JS)
    if not box:
        return -1
    await page.mouse.click(box["x"], box["y"])
    prev = -2
    rows = -1
    for _ in range(timeout_polls):
        await page.wait_for_timeout(1_000)
        rows = await page.evaluate(js.ROWCOUNT_JS)
        if isinstance(rows, int) and rows > 0 and rows == prev:
            break  # 양수로 안정 → 확정.
        prev = rows
    return rows if isinstance(rows, int) else -1


async def read_rows(page: Any, limit: int = 200) -> list[dict]:
    r = await page.evaluate(js.READ_ROWS_JS, limit)
    return r.get("list") or []


# ── 적요(행별 인라인) ─────────────────────────────────────────────────────────────
async def set_note(page: Any, row: int, text: str) -> dict:
    return await page.evaluate(js.NOTE_SET_JS, [row, text])


# ── 코드피커(예산단위/계정/프로젝트) ──────────────────────────────────────────────
def _norm(s: object) -> str:
    return re.sub(r"\s+", "", str(s or "")).lower()


# field_id: bg_cd(예산단위)/acct_cd(계정)/pjt_cd(프로젝트). code/name 필드는 팝업 컬럼.
async def fill_codepicker(
    page: Any,
    field_id: str,
    keyword: str,
    code_field: str,
    name_field: str,
    *,
    allow_default: bool = False,
) -> dict:
    """코드피커 버튼→팝업→keyword 검색→**이름 매칭** 선택→적용. 반환 {ok, code, name} | {ok:False,reason}.

    ⚠ 무매칭 시 임의(index 0) 선택 금지 — 잘못된 코드가 전표에 기록되면 위험(리뷰 HIGH #1).
    - keyword 있음: 이름에 keyword 를 포함하는 후보만. 정확히 1건이면 선택, 여러 건이면 ambiguous 실패,
      0건이면 (allow_default 이고 전체목록이 1건일 때만) 그 1건, 아니면 무매칭 실패(후보 반환).
    - keyword 없음: 목록이 1건이면 선택(예: 계정=예산단위로 자동축소), 아니면 keyword 필요.
    allow_default 는 계정(acct_cd)처럼 상위 선택으로 자동축소되는 필드에만 True 로 준다.
    """
    box = await page.evaluate(js.picker_btn_js(field_id))
    if not box:
        return {"ok": False, "reason": f"{field_id} 버튼 없음"}
    await page.mouse.click(box["x"], box["y"])
    await page.wait_for_timeout(1_500)

    async def _fail(reason: str, **extra: Any) -> dict:
        # 실패 시 열린 코드피커 팝업을 닫는다 — 안 닫으면 다음 코드피커가 이 팝업을 읽어 오작동한다.
        await page.evaluate(js.PICKER_CLOSE_JS)
        await page.wait_for_timeout(400)
        return {"ok": False, "reason": reason, **extra}

    if keyword:
        s = await page.evaluate(js.PICKER_SEARCH_JS, keyword)
        if s.get("ok"):
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(1_200)
    read = await page.evaluate(js.PICKER_READ_JS, [code_field, name_field, 25])
    opts = read.get("options") or []

    chosen: dict | None = None
    if keyword:
        k = _norm(keyword)
        matches = [o for o in opts if k and k in _norm(o.get("name"))]
        uniq_codes = {o.get("code") for o in matches}
        if len(uniq_codes) == 1:
            # 1건 또는 동일 코드로 수렴하는 중복 후보(예: 예산단위 '경영 본부' 7행 모두 code 2000
            # — BIZPLAN 조합만 다르고 BG_CD 는 동일) → 사실상 단일 선택이므로 확정(임의선택 아님).
            chosen = matches[0]
        elif len(matches) > 1:
            cands = ", ".join(sorted({o.get("name", "") for o in matches})[:6])
            return await _fail(f"'{keyword}' 후보 여러 건({cands}) — 더 구체적으로", ambiguous=True)
        elif allow_default:
            # 무매칭 → 기본목록(빈검색) 재조회. 자동축소 **단일**이면 채택(예: 계정=예산단위 연동),
            # 다건이면 실패(임의선택 금지). ⚠ index0 blind pick 아님(리뷰 HIGH #1).
            await page.evaluate(js.PICKER_SEARCH_JS, "")
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(1_000)
            dflt = (await page.evaluate(js.PICKER_READ_JS, [code_field, name_field, 25])).get("options") or []
            if len(dflt) == 1:
                chosen = dflt[0]
            else:
                return await _fail(f"'{keyword}' 무매칭·자동후보 {len(dflt)}건 — 계정명을 확인")
        else:
            cands = ", ".join(o.get("name", "") for o in opts[:6]) or "없음"
            return await _fail(f"'{keyword}' 일치 없음(후보: {cands})", rows=read.get("rows"))
    else:
        if len(opts) == 1:
            chosen = opts[0]
        else:
            return await _fail(f"{field_id} keyword 필요(후보 {len(opts)}건)")

    sel = await page.evaluate(js.PICKER_SELECT_JS, chosen["i"])
    if not sel.get("ok"):
        return await _fail(f"{field_id} 행 선택 실패: {sel}")
    await page.wait_for_timeout(400)
    apply_box = await page.evaluate(js.PICKER_APPLY_BTN_JS)
    if apply_box:
        await page.mouse.click(apply_box["x"], apply_box["y"])
        await page.wait_for_timeout(1_000)
    return {"ok": True, "code": chosen["code"], "name": chosen["name"]}


# ── 코드 카탈로그 덤프(코드피커 전량 읽기) ─────────────────────────────────────────
async def _open_picker(page: Any, field_id: str) -> bool:
    """코드피커 버튼 좌표 클릭 → 팝업 오픈 대기. 성공 True."""
    box = await page.evaluate(js.picker_btn_js(field_id))
    if not box:
        return False
    await page.mouse.click(box["x"], box["y"])
    await page.wait_for_timeout(1_800)
    return True


async def _picker_search(page: Any, keyword: str) -> None:
    """열린 코드피커 팝업에 keyword 를 넣고 Enter 로 서버 재조회."""
    await page.evaluate(js.PICKER_SEARCH_JS, keyword)
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(1_200)


async def dump_budget_units(page: Any) -> list[dict]:
    """예산단위(bg_cd) 코드피커 빈검색 전량 → 유니크 (BG_CD,BG_NM). 반환 [{code,name,deptNm}].

    피커는 로그인 사용자 부서로 서버필터됨(DEPT_NM 동일). 중복행(BIZPLAN 조합만 다름)은
    (BG_CD) 기준 최초 1건만 남긴다(첫 DEPT_NM 보존).
    """
    if not await _open_picker(page, "bg_cd"):
        return []
    await _picker_search(page, "")
    read = await page.evaluate(js.PICKER_READ_MULTI_JS, [["BG_CD", "BG_NM", "DEPT_NM"], 0])
    await page.evaluate(js.PICKER_CLOSE_JS)
    await page.wait_for_timeout(400)
    seen: set[str] = set()
    out: list[dict] = []
    for o in read.get("options") or []:
        code = o.get("BG_CD")
        if not code or code in seen:
            continue
        seen.add(code)
        out.append({"code": code, "name": o.get("BG_NM") or "", "deptNm": o.get("DEPT_NM") or ""})
    return out


async def dump_projects(page: Any, keyword: str | None) -> list[dict]:
    """프로젝트(pjt_cd) 코드피커 검색(빈검색=초기 500행) → (PJT_NO) 유니크. 반환 [{code,name,useYn}].

    ⚠ 팝업 캡(500행). 전량 수집은 서비스에서 prefix sweep 으로 합집합한다.
    """
    if not await _open_picker(page, "pjt_cd"):
        return []
    await _picker_search(page, keyword or "")
    read = await page.evaluate(js.PICKER_READ_MULTI_JS, [["PJT_NO", "PJT_NM", "USE_YN"], 0])
    await page.evaluate(js.PICKER_CLOSE_JS)
    await page.wait_for_timeout(400)
    return _dedupe_projects(read.get("options") or [])


def _dedupe_projects(options: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for o in options:
        code = o.get("PJT_NO")
        if not code or code in seen:
            continue
        seen.add(code)
        out.append({"code": code, "name": o.get("PJT_NM") or "", "useYn": o.get("USE_YN") or ""})
    return out


# 프로젝트 팝업 로드 캡(초기/검색당 최대 로드 행). 정확히 이 값이면 결과가 잘렸을 수 있음.
PROJECT_PICKER_CAP = 500


async def dump_projects_sweep(page: Any, prefixes: list[str]) -> tuple[list[dict], list[str]]:
    """프로젝트(pjt_cd) 팝업을 **한 번만 열고** prefix 별로 in-popup 재검색해 합집합 수집.

    팝업 캡(500)으로 빈검색만으론 전량이 안 되므로 접두 스윕으로 채운다. 팝업을 prefix 마다
    다시 열지 않고(비용·상태), 같은 팝업의 검색창을 재질의한다. 반환 (합집합 [{code,name,useYn}],
    정확히 캡(500)을 반환해 잘렸을 가능성이 있는 prefix 목록).
    """
    if not await _open_picker(page, "pjt_cd"):
        return [], []
    by_code: dict[str, dict] = {}
    cap_hit: list[str] = []
    for kw in prefixes:
        await _picker_search(page, kw)
        read = await page.evaluate(js.PICKER_READ_MULTI_JS, [["PJT_NO", "PJT_NM", "USE_YN"], 0])
        if read.get("rows") == PROJECT_PICKER_CAP:
            cap_hit.append(kw or "(빈검색)")
        for row in _dedupe_projects(read.get("options") or []):
            by_code.setdefault(row["code"], row)
    await page.evaluate(js.PICKER_CLOSE_JS)
    await page.wait_for_timeout(400)
    return list(by_code.values()), cap_hit


# ── 행 반영(일괄적용, 해당 행만 체크) / 저장(F7) ──────────────────────────────────
async def apply_row(page: Any, row: int) -> dict:
    """그 행만 체크 후 '일괄적용' 클릭(그 행에 폼값 반영). ⚠ 저장 아님."""
    chk = await page.evaluate(js.CHECK_ONLY_ROW_JS, row)
    if not chk.get("ok"):
        return {"ok": False, "reason": f"행 체크 실패: {chk}"}
    # 정확히 대상 행 1건만 체크됐는지 검증 — 0건/다건이면 일괄적용이 엉뚱한 범위에 반영된다(리뷰 #6).
    if chk.get("checked") != 1:
        return {"ok": False, "reason": f"행 {row} 단일 체크 실패(checked={chk.get('checked')}) — 일괄적용 중단"}
    box = await page.evaluate(js.card_button_box_js("일괄적용"))
    if not box:
        return {"ok": False, "reason": "'일괄적용' 버튼 없음"}
    await page.mouse.click(box["x"], box["y"])
    await page.wait_for_timeout(1_200)
    # 일괄적용 → '예산현황' 확인창(확인/취소) 이 뜬다. '확인'으로 draft 반영을 완료한다.
    # ⚠ draft(메모리) 완료일 뿐 F7 저장 아님. 미처리 시 창이 남아 다음 행 코드피커가 0건이 된다.
    cf = await page.evaluate(js.BUDGET_CONFIRM_JS)
    if cf.get("clicked"):
        await page.wait_for_timeout(900)
    return {"ok": True, "budget_confirm": cf.get("clicked")}


async def save_document(page: Any, confirm: bool) -> dict:
    """결의서 저장(F7). ⚠ confirm=True 일 때만 실제 클릭(테스트는 항상 False).

    ⚠ 저장 경로는 아직 라이브 미검증(테스트가 저장 전까지만) — 카드팝업 내 '저장'이 없으면 결의서
    본화면의 '저장'을 문서 전역에서 찾고, 그래도 없으면 F7. 실제 저장 검증 시 이 경로를 확정해야 한다.
    """
    if not confirm:
        return {"ok": False, "skipped": True, "reason": "SAVE 게이트 닫힘(테스트 모드)"}
    # 팝업 내 → 문서 전역 순으로 '저장' 버튼 탐색.
    box = await page.evaluate(js.card_button_box_js("저장")) or await page.evaluate(
        js.document_button_box_js("저장")
    )
    if box:
        await page.mouse.click(box["x"], box["y"])
        await page.wait_for_timeout(1_500)
        return {"ok": True, "via": "button"}
    await page.keyboard.press("F7")
    await page.wait_for_timeout(1_500)
    return {"ok": True, "via": "F7"}
