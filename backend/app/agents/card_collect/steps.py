"""법인카드 승인내역 정리 — 스텝 함수(진입 후 카드팝업 조작). js.py 프리미티브 사용.

각 함수는 Playwright page 를 받아 조작하고 결과를 반환한다(LangGraph 노드가 이 함수들을 호출).
⚠ 저장(F7)은 save_document(page, confirm=True) 로만, 명시적 confirm 일 때만 실행한다.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
from datetime import date
from typing import Any

from . import js

logger = logging.getLogger(__name__)

# ── D2: 승인일 기간 계산 ─────────────────────────────────────────────────────────
# 오늘이 매월 10일 미만(1~9일)이면 전월(1일~말일), 10일부터는 당월(1일~오늘).
# (규칙 변경 2026-07-04: 3일 기준 → 10일 기준, 사용자 확정)
# 2026-07-06: 에이전트 설정 '회계시점 결정일(acct_cutoff_day)'로 파라미터화 —
# 설정 N = "N일까지 전월, N+1일부터 당월"(현행 동작은 N=9 와 동치, 스키마 기본값 9).
DAY_CUTOFF = 10


def compute_period(today: date, cutoff_day: int | None = None) -> tuple[str, str]:
    """(start, end) YYYY-MM-DD. cutoff_day 일까지=전월 전체, 그 다음 날부터=당월 1일~오늘.

    cutoff_day 미지정(None)이면 레거시 규칙(DAY_CUTOFF=10 미만=전월) 유지 — 하위호환.
    """
    is_prev = today.day <= cutoff_day if cutoff_day is not None else today.day < DAY_CUTOFF
    if is_prev:
        year = today.year - 1 if today.month == 1 else today.year
        month = 12 if today.month == 1 else today.month - 1
        last = calendar.monthrange(year, month)[1]
        return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last:02d}"
    return f"{today.year:04d}-{today.month:02d}-01", today.isoformat()


def period_month_end(period_start: str) -> tuple[str, str]:
    """기간 시작일(YYYY-MM-01)의 그 달 **말일** — (compact 'YYYYMMDD', dashed 'YYYY-MM-DD').

    회계일 규칙(사용자 확정 2026-07-04): 전월 수집이면 전월 말일, 당월 수집이면 당월 말일.
    compact 는 그리드 setValue 용(대시 형식은 셀을 비우는 함정 — SET_ACCT_DATE_JS 참조).
    """
    y, m = int(period_start[:4]), int(period_start[5:7])
    last = calendar.monthrange(y, m)[1]
    return f"{y:04d}{m:02d}{last:02d}", f"{y:04d}-{m:02d}-{last:02d}"


# set_acct_date 는 app.agents.common.doc_steps 로 승격(2026-07-06, 출장 공용) — 재수출 shim.
# card 노드(query.py)의 steps.set_acct_date 호출과 테스트 monkeypatch 를 그대로 보존한다.
from app.agents.common.doc_steps import set_acct_date  # noqa: E402, F401 — 하위호환 재수출


# ── 카드 선택(본인 카드 우선, 없으면 전체) ─────────────────────────────────────────
async def select_all_cards(page: Any, owner_name: str | None = None) -> dict:
    """카드번호 돋보기 → '카드' 서브팝업 선택 → 적용. 반환 {ok, n, checked, by}.

    선택 규칙(사용자 확정 2026-07-04): owner_name(=로그인ID=사용자명)이 주어지면 소유자
    (CARD_OWNR_NM)/관리사원(KOR_NM)이 그 이름과 일치하는 카드만 선택하고, 일치 0건이면
    기존 로직인 **전체선택**으로 폴백한다(공용카드·빈 소유자 대비). by='name'|'all'.

    ⚠ 증빙유형 01 적용 직후 법인카드 팝업이 **로딩 중**('데이터 처리 중')일 수 있다 — 돋보기
    버튼 출현을 폴링(실측 2026-07-04: 폴링 세분화 후 '돋보기 버튼 없음' 레이스).
    """
    box = None
    waited = 0
    while waited < 10_000:  # 팝업 로딩 폴링(상한 10s)
        box = await page.evaluate(js.CARD_SEARCH_BTN_JS)
        if box:
            break
        await page.wait_for_timeout(300)
        waited += 300
    if not box:
        return {"ok": False, "reason": "돋보기 버튼 없음(법인카드 팝업 아님?)"}
    await page.mouse.click(box["x"], box["y"])
    # 서브팝업 그리드 준비 폴링(check-first: 준비됐으면 즉시 진행, 아니면 150ms 간격 재시도).
    by = "all"
    sel: dict = {}
    waited = 0
    while waited < 6_000:
        if owner_name and (owner_name or "").strip():
            # 본인 이름 매칭 우선 — matched>0 이면 그것으로 확정, matched==0 이면 전체선택 폴백.
            r = await page.evaluate(js.CARD_SUB_SELECT_BY_NAME_JS, owner_name)
            if r.get("ok") and r.get("n", 0) > 0:
                if r.get("matched", 0) > 0:
                    sel, by = r, "name"
                    break
                sel = await page.evaluate(js.CARD_SUB_SELECT_ALL_JS)  # 매칭 0 → 전체선택
                if sel.get("ok"):
                    break
        else:
            sel = await page.evaluate(js.CARD_SUB_SELECT_ALL_JS)
            if sel.get("ok"):
                break
        await page.wait_for_timeout(150)
        waited += 150
    if not sel.get("ok"):
        return {"ok": False, "reason": f"서브팝업 카드선택 실패: {sel}"}
    apply_box = await page.evaluate(js.CARD_SUB_APPLY_BTN_JS)
    if not apply_box:
        return {"ok": False, "reason": "서브팝업 '적용' 버튼 없음", "n": sel.get("n")}
    await page.mouse.click(apply_box["x"], apply_box["y"])
    # 적용 후 서브팝업 닫힘 폴링(고정 1000ms 대체) — 닫히는 즉시 진행, 상한 2s.
    closed_waited = 0
    while closed_waited < 2_000:
        await page.wait_for_timeout(150)
        closed_waited += 150
        if not await page.evaluate(js.CARD_SUB_EXISTS_JS):
            break
    return {"ok": True, "n": sel.get("n"), "checked": sel.get("checked"), "by": by}


# ── 승인일 세팅 + 조회 ───────────────────────────────────────────────────────────
async def set_period(page: Any, start: str, end: str) -> dict:
    r = await page.evaluate(js.PERIOD_SET_JS, [start, end])
    ok = r.get("start") == start and r.get("end") == end
    return {"ok": ok, **r}


async def run_query(page: Any, timeout_polls: int = 20) -> int:
    """조회 클릭 후 rowcount 가 '안정'될 때까지 폴링. 반환 행 수(0 가능, -1=클릭 실패).

    느린 그리드에서 0을 실제 0건으로 오인하지 않도록, 같은 양수가 **3회 연속**(600ms 안정창)
    관측될 때까지 기다린다. 300ms 간격 폴링(기존 1s) — 상한은 timeout_polls 초로 동일.
    """
    box = await page.evaluate(js.QUERY_BTN_JS)
    if not box:
        return -1
    await page.mouse.click(box["x"], box["y"])
    prev = -2
    stable = 0
    rows = -1
    waited = 0
    for _ in range(timeout_polls * 1000 // 300):
        await page.wait_for_timeout(300)
        waited += 300
        rows = await page.evaluate(js.ROWCOUNT_JS)
        if isinstance(rows, int) and rows == prev and (rows > 0 or waited >= 3_000):
            # 양수는 즉시 안정 인정, 0건은 3초 유예 후 안정 인정 — 진짜 빈 결과에서
            # 상한(20s)을 전부 태우지 않는다(실측 2026-07-04: 0건 조회가 20s 소모).
            stable += 1
            if stable >= 2:  # 직전 포함 3회 연속 동일
                break
        else:
            stable = 0
        prev = rows
    return rows if isinstance(rows, int) else -1


async def read_rows(page: Any, limit: int = 200) -> list[dict]:
    r = await page.evaluate(js.READ_ROWS_JS, limit)
    return r.get("list") or []


# ── 적요(행별 인라인) ─────────────────────────────────────────────────────────────
async def set_note(page: Any, row: int, text: str) -> dict:
    return await page.evaluate(js.NOTE_SET_JS, [row, text])


# ── 코드피커(예산단위/계정/프로젝트) ──────────────────────────────────────────────
# 공용 엔진은 nbkit.omnisol.codepicker 로 승격(2026-07-05) — 여기서는 재수출만 한다.
# 아래 잔여 함수들(fill_budget_codepicker 등)의 bare-name 호출과 테스트의
# monkeypatch.setattr(steps, ...) 는 이 모듈 전역을 통해 그대로 동작한다.
from nbkit.omnisol.codepicker import (  # noqa: E402, F401 — 하위호환 재수출(엔진은 nbkit 단일소스)
    _norm,
    _open_picker,
    _picker_search,
    _wait_picker_closed,
    _wait_picker_rows_stable,
    fill_codepicker,
)


# ── 코드 카탈로그 덤프(코드피커 전량 읽기) ─────────────────────────────────────────
async def dump_budget_units(page: Any) -> list[dict]:
    """예산단위(bg_cd) 코드피커 빈검색 전량 — **조합 행 그대로**(디둡 없음).

    선택 단위는 BG명 단독이 아니라 (예산단위명 × 사업계획명 × 예산계정명) 조합 행이다
    (사용자 정정 2026-07-02 — BG만 남기면 부서 리스트에 불과함). 반환
    [{code(BG|BIZPLAN|BGACCT 복합), name(BG_NM), bizplanCd, bizplanNm, bgacctCd, bgacctNm}].
    그리드의 DEPT_NM 은 행별 소속이 아니라 로그인 사용자 부서 반복이라 읽지 않는다.
    """
    if not await _open_picker(page, "bg_cd"):
        return []
    await _picker_search(page, "")
    read = await page.evaluate(
        js.PICKER_READ_MULTI_JS,
        [["BG_CD", "BG_NM", "BIZPLAN_CD", "BIZPLAN_NM", "BGACCT_CD", "BGACCT_NM"], 0],
    )
    await page.evaluate(js.PICKER_CLOSE_JS)
    await page.wait_for_timeout(400)
    seen: set[str] = set()
    out: list[dict] = []
    for o in read.get("options") or []:
        bg = o.get("BG_CD")
        if not bg:
            continue
        code = f"{bg}|{o.get('BIZPLAN_CD') or ''}|{o.get('BGACCT_CD') or ''}"
        if code in seen:
            continue
        seen.add(code)
        out.append(
            {
                "code": code,
                "name": o.get("BG_NM") or "",
                "bizplanCd": o.get("BIZPLAN_CD") or "",
                "bizplanNm": o.get("BIZPLAN_NM") or "",
                "bgacctCd": o.get("BGACCT_CD") or "",
                "bgacctNm": o.get("BGACCT_NM") or "",
            }
        )
    return out


# 프로젝트 팝업(H_PS_WBS_MST) 은 WBS 하위행 단위다. 카탈로그도 WBS 행 단위로 수집한다
# — code 는 PJT_NO|WBS_NO 복합키(전사 WBS_NO 단독 유니크가 offline 미검증 + WBS 없는
# 프로젝트-레벨 행 충돌 대비), 팝업 데이터셋 내 유일성 보장·WBS 세분성 유지(원시 ~2,358행).
_PROJECT_FIELDS = ["PJT_NO", "PJT_NM", "USE_YN", "PARTNER_NM", "WBS_NO", "WBS_NM", "VIEW_WBS_NM", "WBS_LOC"]


async def dump_projects(page: Any, keyword: str | None) -> list[dict]:
    """프로젝트(pjt_cd) 코드피커 검색(빈검색=초기 500행) → (PJT_NO|WBS_NO) 유니크.

    반환 [{code,name,pjtNo,wbsNo,wbsNm,loc,useYn,partnerNm}] — WBS 하위행 단위.
    ⚠ 팝업 캡(500행) — 전량 수집은 prefix sweep 합집합.
    """
    if not await _open_picker(page, "pjt_cd"):
        return []
    await _picker_search(page, keyword or "")
    read = await page.evaluate(js.PICKER_READ_MULTI_JS, [_PROJECT_FIELDS, 0])
    await page.evaluate(js.PICKER_CLOSE_JS)
    await page.wait_for_timeout(400)
    return _dedupe_projects(read.get("options") or [])


def _dedupe_projects(options: list[dict]) -> list[dict]:
    """WBS 행 단위 정규화 — code=PJT_NO|WBS_NO 복합, name=PJT_NM(주 표시·검색).

    wbsNm 은 VIEW_WBS_NM(표시명) 우선, 없으면 WBS_NM. loc=WBS_LOC.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for o in options:
        pjt = o.get("PJT_NO")
        if not pjt:
            continue
        wbs = o.get("WBS_NO") or ""
        code = f"{pjt}|{wbs}"
        if code in seen:
            continue
        seen.add(code)
        out.append(
            {
                "code": code,
                "name": o.get("PJT_NM") or "",
                "pjtNo": pjt,
                "wbsNo": wbs,
                "wbsNm": o.get("VIEW_WBS_NM") or o.get("WBS_NM") or "",
                "loc": o.get("WBS_LOC") or "",
                "useYn": o.get("USE_YN") or "",
                "partnerNm": o.get("PARTNER_NM") or "",
            }
        )
    return out


# 프로젝트 팝업 로드 캡(초기/검색당 최대 로드 행). 정확히 이 값이면 결과가 잘렸을 수 있음.
PROJECT_PICKER_CAP = 500


async def dump_projects_scroll(
    page: Any, *, max_rounds: int = 60
) -> tuple[list[dict], int | None, int]:
    """프로젝트(pjt_cd) 팝업 서버 페이징을 **끝행 포커스+ArrowDown** 으로 전량 로드해 수집.

    팝업 그리드는 서버 페이징(500/페이지)이다. 프로브(2026-07-02): DOM 스크롤/페이징
    API/End 키는 무효, **setCurrent(마지막 행)+ArrowDown 연타가 라운드당 +500 결정적**.
    조회 XHR 응답의 total 을 캡처해 목표치로 삼는다. total(실측 2,358)은 WBS 하위행 포함
    **원시 행 수**이며, dedupe 키가 PJT_NO|WBS_NO 복합이라 dedupe 후 행 수도 원시와 거의
    같다(WBS 세분성 유지). 완결 판정은 원시 로드 행 수(raw_loaded)로만 한다.
    반환 (dedupe된 rows, server_total|None, raw_loaded).
    """
    server_total: int | None = None

    def _on_response(resp):
        nonlocal server_total
        if "H_PS_WBS_MST_C_search_list" not in resp.url:
            return

        async def _read():
            nonlocal server_total
            try:
                body = await resp.json()
                t = int(body.get("total") or 0)
                if t > 0:
                    server_total = t
            except Exception:  # noqa: BLE001 — total 캡처 실패는 무해(무증가 판정 폴백)
                pass

        asyncio.ensure_future(_read())

    page.on("response", _on_response)
    try:
        if not await _open_picker(page, "pjt_cd"):
            return [], None, 0
        await _picker_search(page, "")
        prev = await page.evaluate(js.PICKER_ROWCOUNT_JS)
        stable = 0
        for rnd in range(1, max_rounds + 1):
            if server_total and prev >= server_total:
                break  # 전량 로드 완료.
            f = await page.evaluate(js.PICKER_FOCUS_LAST_JS)
            if not f.get("ok"):
                logger.warning("프로젝트 스크롤 r%d — 끝행 포커스 실패: %s", rnd, f)
                break
            for _ in range(30):
                await page.keyboard.press("ArrowDown", delay=30)
            await page.wait_for_timeout(3_000)
            cur = await page.evaluate(js.PICKER_ROWCOUNT_JS)
            logger.info("프로젝트 스크롤 r%d — rows=%s total=%s stable=%d", rnd, cur, server_total, stable)
            if cur <= prev:
                stable += 1
                if stable >= 3:
                    break
                await page.wait_for_timeout(2_000)
            else:
                stable = 0
            prev = max(prev, cur)
        read = await page.evaluate(js.PICKER_READ_MULTI_JS, [_PROJECT_FIELDS, 0])
        await page.evaluate(js.PICKER_CLOSE_JS)
        await page.wait_for_timeout(400)
        raw_loaded = read.get("rows") if isinstance(read.get("rows"), int) else prev
        return _dedupe_projects(read.get("options") or []), server_total, raw_loaded
    finally:
        page.remove_listener("response", _on_response)


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
        read = await page.evaluate(js.PICKER_READ_MULTI_JS, [_PROJECT_FIELDS, 0])
        if read.get("rows") == PROJECT_PICKER_CAP:
            cap_hit.append(kw or "(빈검색)")
        for row in _dedupe_projects(read.get("options") or []):
            by_code.setdefault(row["code"], row)
    await page.evaluate(js.PICKER_CLOSE_JS)
    await page.wait_for_timeout(400)
    return list(by_code.values()), cap_hit


# ── 예산단위 조합 선택(BG × 사업계획 × 예산계정 특정 행) ─────────────────────────────
async def fill_budget_codepicker(page: Any, combo: dict) -> dict:
    """예산단위 피커에서 (BG_NM, BIZPLAN_NM, BGACCT_NM) 조합이 정확히 일치하는 행을 선택.

    combo = {name(BG_NM), bizplanNm, bgacctNm}. 선택 단위가 조합 행이므로(BG 동일해도
    예산계정이 다르면 다른 선택) 이름 3개를 정규화 비교해 그 행 인덱스를 고른다.
    bizplanNm/bgacctNm 이 비어 있으면 기존 fill_codepicker(BG명 매칭)로 폴백(하위호환).
    반환 {ok, code, name} | {ok:False, reason}.
    """
    bg_nm = (combo.get("name") or "").strip()
    bizplan = (combo.get("bizplanNm") or "").strip()
    bgacct = (combo.get("bgacctNm") or "").strip()
    if not (bizplan or bgacct):
        return await fill_codepicker(page, "bg_cd", bg_nm, "BG_CD", "BG_NM")

    if not await _open_picker(page, "bg_cd"):
        return {"ok": False, "reason": "bg_cd 버튼 없음"}

    async def _fail(reason: str) -> dict:
        await page.evaluate(js.PICKER_CLOSE_JS)
        await page.wait_for_timeout(400)
        return {"ok": False, "reason": reason}

    await _picker_search(page, bg_nm)
    read = await page.evaluate(
        js.PICKER_READ_MULTI_JS, [["BG_CD", "BG_NM", "BIZPLAN_NM", "BGACCT_NM"], 0]
    )
    opts = read.get("options") or []
    matches = [
        o
        for o in opts
        if _norm(o.get("BG_NM")) == _norm(bg_nm)
        and _norm(o.get("BIZPLAN_NM")) == _norm(bizplan)
        and _norm(o.get("BGACCT_NM")) == _norm(bgacct)
    ]
    if not matches:
        return await _fail(
            f"예산단위 조합 무매칭: {bg_nm} · {bizplan} · {bgacct} (후보 {len(opts)}건)"
        )
    chosen = matches[0]  # 완전 동일 조합 다건은 사실상 같은 선택.
    sel = await page.evaluate(js.PICKER_SELECT_JS, chosen["i"])
    if not sel.get("ok"):
        return await _fail(f"예산단위 행 선택 실패: {sel}")
    await page.wait_for_timeout(400)
    apply_box = await page.evaluate(js.PICKER_APPLY_BTN_JS)
    if apply_box:
        await page.mouse.click(apply_box["x"], apply_box["y"])
        await _wait_picker_closed(page)  # 팝업 닫힘 폴링(고정 1s 대체)
    return {
        "ok": True,
        "code": chosen.get("BG_CD"),
        "name": f"{chosen.get('BG_NM')} · {chosen.get('BIZPLAN_NM')} · {chosen.get('BGACCT_NM')}",
    }


# ── 프로젝트 WBS 행 선택(PJT_NM 검색 → WBS_NO 정확 일치) ─────────────────────────────
async def fill_project_codepicker(page: Any, combo: dict) -> dict:
    """프로젝트 피커에서 PJT_NM 검색 후 WBS_NO 가 정확히 일치하는 WBS 행을 선택.

    combo = {name(PJT_NM), wbsNo}. 카탈로그가 WBS 행 단위라 같은 프로젝트에 여러 WBS 요소가
    있어(선택이 달라짐) WBS_NO 로 정확히 고른다. wbsNo 가 없으면 fill_codepicker(PJT_NM 매칭)로
    폴백(구 PJT_NO 즐겨찾기·WBS 미지정 하위호환). 반환 {ok, code, name} | {ok:False, reason}.
    """
    pjt_nm = (combo.get("name") or "").strip()
    wbs_no = (combo.get("wbsNo") or "").strip()
    if not wbs_no:
        return await fill_codepicker(page, "pjt_cd", pjt_nm, "PJT_NO", "PJT_NM")

    if not await _open_picker(page, "pjt_cd"):
        return {"ok": False, "reason": "pjt_cd 버튼 없음"}

    async def _fail(reason: str) -> dict:
        await page.evaluate(js.PICKER_CLOSE_JS)
        await page.wait_for_timeout(400)
        return {"ok": False, "reason": reason}

    await _picker_search(page, pjt_nm)
    read = await page.evaluate(js.PICKER_READ_MULTI_JS, [["PJT_NO", "PJT_NM", "WBS_NO"], 0])
    opts = read.get("options") or []
    matches = [o for o in opts if _norm(o.get("WBS_NO")) == _norm(wbs_no)]
    if not matches:
        # WBS_NO 무매칭 → PJT_NM 정확 일치로 폴백(WBS 체계 변경/이전 즐겨찾기 대비, 임의선택 아님).
        matches = [o for o in opts if _norm(o.get("PJT_NM")) == _norm(pjt_nm)]
        if not matches:
            return await _fail(f"프로젝트 무매칭: {pjt_nm} · WBS {wbs_no} (후보 {len(opts)}건)")
    chosen = matches[0]
    sel = await page.evaluate(js.PICKER_SELECT_JS, chosen["i"])
    if not sel.get("ok"):
        return await _fail(f"프로젝트 행 선택 실패: {sel}")
    await page.wait_for_timeout(400)
    apply_box = await page.evaluate(js.PICKER_APPLY_BTN_JS)
    if apply_box:
        await page.mouse.click(apply_box["x"], apply_box["y"])
        await _wait_picker_closed(page)  # 팝업 닫힘 폴링(고정 1s 대체)
    return {"ok": True, "code": chosen.get("PJT_NO"), "name": chosen.get("PJT_NM")}


# ── 카드 팝업 닫기(2패스 증빙유형 전환용) ─────────────────────────────────────────
async def close_card_popup(page: Any) -> dict:
    """법인카드 카드 팝업의 '닫기' 버튼 클릭 후 닫힘 검증. 반환 {ok} | {ok:False, reason}.

    프로브 실측(2026-07-02): 팝업 하단 '닫기' 버튼 클릭으로 정상 닫힘, 이후 같은 행에서
    증빙유형 재선택(open_evdn→select_evdn) 이 F3 없이 동작한다.
    """
    if not await page.evaluate(js.CARD_WIN_EXISTS_JS):
        return {"ok": True, "already": True}  # 이미 닫혀 있음.
    box = await page.evaluate(js.card_button_box_js("닫기"))
    if not box:
        return {"ok": False, "reason": "'닫기' 버튼 없음"}
    await page.mouse.click(box["x"], box["y"])
    # 고정 1.5s 대기 대신 팝업이 닫히는 즉시 진행 — 폴링(상한 1.5s 유지, 동작 동일).
    waited = 0
    while waited < 1_500:
        await page.wait_for_timeout(150)
        waited += 150
        if not await page.evaluate(js.CARD_WIN_EXISTS_JS):
            return {"ok": True}
    return {"ok": False, "reason": "닫기 클릭 후에도 팝업이 남아 있음"}


# ── 행 반영(일괄적용, 해당 행들만 체크) / 저장(F7) ─────────────────────────────────
async def apply_rows(page: Any, rows: list[int]) -> dict:
    """대상 행들만 체크 후 '일괄적용' 1회 — 같은 (예산단위·프로젝트·적요) 그룹을 한 번에
    반영한다(사용자 확정 2026-07-04). ⚠ 저장 아님(draft).

    CHECK_ROWS_JS 는 checkAll(false) 후 지정 행만 체크하므로 이전 그룹 체크가 남지 않는다.
    """
    if not rows:
        return {"ok": False, "reason": "일괄적용 대상 행이 없습니다"}
    chk = await page.evaluate(js.CHECK_ROWS_JS, rows)
    if not chk.get("ok"):
        return {"ok": False, "reason": f"행 체크 실패: {chk}"}
    # 정확히 대상 행들만 체크됐는지 검증 — 0건/과다면 일괄적용이 엉뚱한 범위에 반영된다(리뷰 #6).
    if chk.get("checked") != len(rows):
        return {
            "ok": False,
            "reason": f"행 체크 불일치(요청 {len(rows)}·체크 {chk.get('checked')}) — 일괄적용 중단",
        }
    box = await page.evaluate(js.card_button_box_js("일괄적용"))
    if not box:
        return {"ok": False, "reason": "'일괄적용' 버튼 없음"}
    await page.mouse.click(box["x"], box["y"])
    # 일괄적용 → '예산현황' 확인창(확인/취소) 이 뜬다. '확인'으로 draft 반영을 완료한다.
    # ⚠ draft(메모리) 완료일 뿐 F7 저장 아님. 미처리 시 창이 남아 다음 행 코드피커가 0건이 된다.
    # 고정 1.2s+0.9s → 200ms 폴링(상한 2s)으로 뜨는 즉시 확인(행당 ~1s 단축).
    clicked = False
    waited = 0
    while waited < 2_000:
        await page.wait_for_timeout(200)
        waited += 200
        cf = await page.evaluate(js.BUDGET_CONFIRM_JS)
        if cf.get("clicked"):
            clicked = True
            break
    if clicked:
        await page.wait_for_timeout(300)  # 모달 닫힘 settle(기존 900ms 축소)
    return {"ok": True, "budget_confirm": clicked}


# 차단 모달 일괄 해제는 nbkit.omnisol.modals 로 승격(2026-07-05) — 재수출 shim.
from nbkit.omnisol.modals import dismiss_blocking_modals  # noqa: E402, F401 — 하위호환 재수출


async def apply_rows_to_document(page: Any, row_indices: list[int]) -> dict:
    """처리한 행들을 체크 → 카드팝업 '적용' → 확인 모달 처리 → 팝업 닫힘·문서 반영.

    프로브 실측(2026-07-02) 수순:
    1. 행 체크(CHECK_ROWS) → '적용' 클릭
    2. '선택' 모달("부가세금액 0 포함하시겠습니까?") → '예' (그리드에서 사용자가 이미 선택한
       행들이므로 포함이 맞다)
    3. 카드팝업 닫힘 + '예산현황' 모달 → '확인' → 결의서 마스터/디테일에 행 반영(문서 미저장)
    반환 {ok, checked} | {ok:False, reason, modals}.
    """
    if not row_indices:
        return {"ok": False, "reason": "적용할 행이 없습니다"}
    chk = await page.evaluate(js.CHECK_ROWS_JS, row_indices)
    if not chk.get("ok") or chk.get("checked") != len(row_indices):
        return {"ok": False, "reason": f"행 체크 실패(요청 {len(row_indices)}·체크 {chk.get('checked')})"}
    box = await page.evaluate(js.card_button_box_js("적용"))
    if not box:
        return {"ok": False, "reason": "카드팝업 '적용' 버튼 없음"}
    await page.mouse.click(box["x"], box["y"])

    # 모달 시퀀스 폴링: '예'(부가세0 포함) → '확인'(예산현황) → 팝업 닫힘. check-first(400ms
    # 선대기 제거) + 간격 축소 — 40행 처리 시 각 모달을 뜨는 즉시 클릭. 상한 45s(대량 행 서버
    # 처리 여유). 계측(clicks/iters/elapsed)을 반환해 다음 런에서 병목 위치를 본다.
    import time as _t
    t0 = _t.monotonic()
    clicks = 0
    for it in range(300):
        yes = await page.evaluate(js.MODAL_BTN_BOX_JS, "예")
        if yes:
            await page.mouse.click(yes["x"], yes["y"])
            clicks += 1
            continue
        ok_btn = await page.evaluate(js.MODAL_BTN_BOX_JS, "확인")
        if ok_btn and "예산" in (ok_btn.get("title") or ""):
            await page.mouse.click(ok_btn["x"], ok_btn["y"])
            clicks += 1
            continue
        if not await page.evaluate(js.CARD_WIN_EXISTS_JS):
            dismissed = await dismiss_blocking_modals(page)
            elapsed = int((_t.monotonic() - t0) * 1000)
            return {"ok": True, "checked": chk.get("checked"), "late_modals": dismissed[:4],
                    "clicks": clicks, "iters": it, "elapsed_ms": elapsed}
        await page.wait_for_timeout(150)
        if (_t.monotonic() - t0) > 45:
            break
    modals = await page.evaluate(js.MODALS_SNAPSHOT_JS)
    return {"ok": False, "reason": "적용 후 카드팝업이 닫히지 않음", "modals": modals,
            "clicks": clicks, "elapsed_ms": int((_t.monotonic() - t0) * 1000)}


# 저장(F7) 거부를 알리는 오류/에러 모달 판별. 실측 모달 title 은 '오류'뿐 아니라 '에러'
# (회계일 마감 등)로도 뜬다 — 둘 다 잡아야 미저장을 성공으로 오판하지 않는다.
_ERR_MODAL_TITLE_HINTS = ("오류", "에러", "경고", "실패")
# 마감된 회계월에 저장 시도 — 재시도로 못 고치는 확정 실패(관리자 마감 해제 필요).
_CLOSED_PERIOD_HINTS = ("회계일이 마감", "마감되어", "마감된")


def _is_closed_period(m: dict) -> bool:
    blob = f"{m.get('title') or ''} {m.get('text') or ''}"
    return any(h in blob for h in _CLOSED_PERIOD_HINTS)


def _is_error_modal(m: dict) -> bool:
    """오류/에러/경고 계열 저장거부 모달이면 True — 성공 오판 방지의 단일 기준."""
    title = (m.get("title") or "").strip()
    if any(h in title for h in _ERR_MODAL_TITLE_HINTS):
        return True
    return _is_closed_period(m)


async def save_document(page: Any, confirm: bool) -> dict:
    """결의서 저장(F7) + 확인 모달 처리 + 관찰 결과 반환. confirm=True 일 때만 실행.

    ⚠ 반드시 apply_rows_to_document 로 카드팝업을 닫고 문서에 반영한 뒤 호출한다 —
    팝업(모달)이 열려 있으면 F7 이 본문에 전달되지 않는다(첫 실전 런 실측 실패 원인).
    F7 후 뜨는 모달은 '확인/예' 계열을 클릭하며 텍스트를 수집한다. 저장 성공의 확정
    신호는 아직 미실측 — 관찰 데이터(modals_seen)를 함께 반환하고 verified 로 표시한다.
    """
    if not confirm:
        return {"ok": False, "skipped": True, "reason": "SAVE 게이트 닫힘(테스트 모드)"}
    if await page.evaluate(js.CARD_WIN_EXISTS_JS):
        return {"ok": False, "reason": "카드팝업이 열려 있어 저장 불가(적용 단계 누락)"}
    # 잔여 확인 모달이 남아 있으면 F7 이 삼켜져 미저장인데도 ok 로 오판한다 — 먼저 정리.
    pre = await dismiss_blocking_modals(page, rounds=3)
    await page.keyboard.press("F7")
    modals_seen: list[dict] = []
    toasts_seen: list[str] = []
    # 간격 2s→500ms(상한 16s 유지). ⚠ F7 직후 모달이 뜨기까지 ~1-2s 걸리므로, '모달 없음'
    # 종료 판정은 최소 관찰 창(3s) 이후에만 허용 — 빠른 폴링이 미출현 모달을 놓치지 않게.
    waited = 0
    while waited < 16_000:
        await page.wait_for_timeout(500)
        waited += 500
        # 인라인 검증 토스트('필수 값…')는 모달이 아니라 F7 직후 잠깐 떴다 사라지므로
        # 매 폴링마다 함께 스캔한다(실측: 미저장인데 ok 로 오판하던 원인).
        toasts = await page.evaluate(js.VALIDATION_TOAST_JS)
        if toasts:
            toasts_seen.extend(toasts)
        modals = await page.evaluate(js.MODALS_SNAPSHOT_JS)
        if modals:
            modals_seen.extend(modals)
            # 오류/에러 모달(회계일 마감 등)은 확정 실패 — 닫고 즉시 종료(성공 오판·헛대기 방지).
            # 이 모달은 '예/확인'이 없고 '닫기'만 있어, 아래 성공 확인 루프로는 안 닫힌다.
            if any(_is_error_modal(m) for m in modals):
                for label in ("확인", "닫기"):
                    btn = await page.evaluate(js.MODAL_BTN_BOX_JS, label)
                    if btn:
                        await page.mouse.click(btn["x"], btn["y"])
                        break
                break
            for label in ("예", "확인", "닫기"):
                btn = await page.evaluate(js.MODAL_BTN_BOX_JS, label)
                if btn:
                    await page.mouse.click(btn["x"], btn["y"])
                    break
            continue
        if toasts:
            break  # 검증 토스트 확인됨 — 저장 실패로 즉시 종료.
        if waited >= 3_000:
            break  # 관찰 창 경과 + 모달·토스트 없음 — 저장 시퀀스 종료로 판단.
    # 인라인 검증 토스트(필수값 누락 등) = 미저장. 모달만 보던 시절 ok 로 오판(2026-07-03 실측).
    if toasts_seen:
        detail = " / ".join(dict.fromkeys(toasts_seen))[:300]
        return {
            "ok": False,
            "reason": f"저장(F7)이 검증 실패로 거부됨: {detail}",
            "modals_seen": modals_seen[:6],
            "toasts_seen": list(dict.fromkeys(toasts_seen))[:6],
        }
    # 실전 실측(2026-07-02): 저장 검증 실패 시 '[오류] 승인 건 계정과 다릅니다…' 류의
    # 오류 모달이 뜬다 — 확인만 누르고 성공 보고하면 미저장 가짜 성공. 오류 모달이
    # 하나라도 관찰되면 실패로 반환해 사용자가 원인(모달 전문)을 볼 수 있게 한다.
    errors = [m for m in modals_seen if _is_error_modal(m)]
    if errors:
        detail = " / ".join((m.get("text") or m.get("title") or "")[:200] for m in errors[:3])
        closed = any(_is_closed_period(m) for m in errors)
        return {
            "ok": False,
            "reason": f"저장(F7)이 ERP 오류로 거부됨: {detail}",
            "modals_seen": modals_seen[:6],
            "closed_period": closed,
        }
    return {"ok": True, "via": "F7", "modals_seen": modals_seen[:6], "pre_modals": pre[:4]}
