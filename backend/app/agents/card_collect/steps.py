"""법인카드 승인내역 정리 — 스텝 함수(진입 후 카드팝업 조작). js.py 프리미티브 사용.

각 함수는 Playwright page 를 받아 조작하고 결과를 반환한다(LangGraph 노드가 이 함수들을 호출).
⚠ 저장(F7)은 save_document(page, confirm=True) 로만, 명시적 confirm 일 때만 실행한다.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
import re
from datetime import date
from typing import Any

from . import js

logger = logging.getLogger(__name__)

# ── D2: 승인일 기간 계산 ─────────────────────────────────────────────────────────
# 오늘이 매월 3일 이하(포함)면 전월(1일~말일), 4일부터는 당월(1일~오늘).
# (규칙 변경 2026-07-04: 기존 10일 기준 → 3일 기준, 사용자 확정)
DAY_CUTOFF = 4


def compute_period(today: date) -> tuple[str, str]:
    """(start, end) YYYY-MM-DD. 3일 이하=전월 전체, 4일부터=당월 1일~오늘."""
    if today.day < DAY_CUTOFF:
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


async def set_acct_date(page: Any, ymd_compact: str, expect_display: str) -> dict:
    """마스터(결의서) 0행 회계일(ACTG_DT) 설정 + 표시값 검증. 반환 {ok, display}|{ok:False, reason}.

    프로브 실측(2026-07-04): F3 직후 마스터 행 1개 존재, ds.setValue(0,'ACTG_DT','YYYYMMDD')
    로 설정되고 표시값이 dashed 로 확인된다.
    """
    r = await page.evaluate(js.SET_ACCT_DATE_JS, ymd_compact)
    if not r.get("ok"):
        return {"ok": False, "reason": r.get("reason") or "회계일 설정 실패"}
    if (r.get("display") or "") != expect_display:
        return {
            "ok": False,
            "reason": f"회계일 표시값 불일치(기대 {expect_display}·실제 {r.get('display')!r})",
        }
    return {"ok": True, "display": r.get("display")}


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
def _norm(s: object) -> str:
    return re.sub(r"\s+", "", str(s or "")).lower()


# ── 조건 대기 헬퍼(속도 최적화) ──────────────────────────────────────────────────
# 고정 wait_for_timeout(1200~1800ms) 을 조건 폴링으로 대체 — worst-case 상한은 유지하되
# 준비되는 즉시 진행한다(행당 픽커 채움 ~14s → ~6-8s, 실측 기반 최적화 2026-07-04).
async def _wait_picker_rows_stable(
    page: Any, *, cap_ms: int = 3_000, interval_ms: int = 200, min_ms: int = 0
) -> int:
    """피커 그리드 rowcount 가 준비(>=0)되고 2회 연속 동일해질 때까지 폴링.

    min_ms: 안정 판정의 **두 관측이 모두** 이 시간 이후여야 한다 — 검색(Enter) 직후 서버
    재조회가 도착하기 전의 '옛 rowcount 안정'을 새 결과로 오인하는 것을 방지. 반환 마지막
    rowcount(-1=팝업 없음 그대로 종료 — 호출부의 기존 실패 경로가 처리).

    ⚠ **0행은 조기 안정으로 인정하지 않는다** — 검색 직후 그리드가 잠깐 비는(재조회 중)
    상태를 '결과 0건'으로 오판해 후보 0건으로 전량 실패하던 실전 회귀(2026-07-04, 40/40행
    '예산단위 조합 무매칭 후보 0건'). 진짜 0건 검색은 cap 소진 후 0을 반환한다.
    """
    prev: int | None = None
    waited = 0
    last = -1
    while waited < cap_ms:
        await page.wait_for_timeout(interval_ms)
        waited += interval_ms
        n = await page.evaluate(js.PICKER_ROWCOUNT_JS)
        if isinstance(n, int) and n >= 0:
            last = n
            # 직전 관측(waited-interval)도 min_ms 이후 + 양수일 때만 조기 안정 인정.
            if n > 0 and waited - interval_ms >= min_ms and n == prev:
                return n
            prev = n
        else:
            prev = None
    return last


async def _wait_picker_closed(page: Any, *, cap_ms: int = 1_500, interval_ms: int = 150) -> None:
    """'적용' 클릭 후 피커 팝업이 닫힐 때까지 폴링(고정 1000ms 대체)."""
    waited = 0
    while waited < cap_ms:
        await page.wait_for_timeout(interval_ms)
        waited += interval_ms
        n = await page.evaluate(js.PICKER_ROWCOUNT_JS)
        if not isinstance(n, int) or n < 0:  # 팝업 사라짐
            return


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
    await _wait_picker_rows_stable(page, cap_ms=3_000)  # 팝업 오픈+그리드 준비(고정 1.5s 대체)

    async def _fail(reason: str, **extra: Any) -> dict:
        # 실패 시 열린 코드피커 팝업을 닫는다 — 안 닫으면 다음 코드피커가 이 팝업을 읽어 오작동한다.
        await page.evaluate(js.PICKER_CLOSE_JS)
        await page.wait_for_timeout(400)
        return {"ok": False, "reason": reason, **extra}

    if keyword:
        s = await page.evaluate(js.PICKER_SEARCH_JS, keyword)
        if s.get("ok"):
            await page.keyboard.press("Enter")
            # 서버 재조회 안정 대기(고정 1.2s 대체) — min_ms 로 옛 rowcount 오인 방지.
            await _wait_picker_rows_stable(page, cap_ms=2_000, min_ms=600)
    read = await page.evaluate(js.PICKER_READ_JS, [code_field, name_field, 25])
    opts = read.get("options") or []

    chosen: dict | None = None
    if keyword:
        k = _norm(keyword)
        matches = [o for o in opts if k and k in _norm(o.get("name"))]
        uniq_codes = {o.get("code") for o in matches}
        # 포함 매칭이 다건이어도 **이름 완전일치**가 단일 코드로 수렴하면 그것을 선택 —
        # 'SPARES_ACM' 이 'SPARES_ACM KOREA' 에도 포함돼 ambiguous 로 실패하던 문제(실전 런).
        exact = [o for o in matches if _norm(o.get("name")) == k]
        exact_codes = {o.get("code") for o in exact}
        if len(uniq_codes) == 1:
            # 1건 또는 동일 코드로 수렴하는 중복 후보(예: 예산단위 '경영 본부' 7행 모두 code 2000
            # — BIZPLAN 조합만 다르고 BG_CD 는 동일) → 사실상 단일 선택이므로 확정(임의선택 아님).
            chosen = matches[0]
        elif len(exact_codes) == 1:
            chosen = exact[0]
        elif len(matches) > 1:
            cands = ", ".join(sorted({o.get("name", "") for o in matches})[:6])
            return await _fail(f"'{keyword}' 후보 여러 건({cands}) — 더 구체적으로", ambiguous=True)
        elif allow_default:
            # 무매칭 → 기본목록(빈검색) 재조회. 자동축소 **단일**이면 채택(예: 계정=예산단위 연동),
            # 다건이면 실패(임의선택 금지). ⚠ index0 blind pick 아님(리뷰 HIGH #1).
            await page.evaluate(js.PICKER_SEARCH_JS, "")
            await page.keyboard.press("Enter")
            await _wait_picker_rows_stable(page, cap_ms=2_000, min_ms=600)
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
        await _wait_picker_closed(page)  # 팝업 닫힘 폴링(고정 1s 대체)
    return {"ok": True, "code": chosen["code"], "name": chosen["name"]}


# ── 코드 카탈로그 덤프(코드피커 전량 읽기) ─────────────────────────────────────────
async def _open_picker(page: Any, field_id: str) -> bool:
    """코드피커 버튼 좌표 클릭 → 팝업 오픈·그리드 준비 폴링(고정 1.8s 대체). 성공 True."""
    box = await page.evaluate(js.picker_btn_js(field_id))
    if not box:
        return False
    await page.mouse.click(box["x"], box["y"])
    await _wait_picker_rows_stable(page, cap_ms=3_000)
    return True


async def _picker_search(page: Any, keyword: str) -> None:
    """열린 코드피커 팝업에 keyword 를 넣고 Enter 로 서버 재조회(안정 폴링, 고정 1.2s 대체)."""
    await page.evaluate(js.PICKER_SEARCH_JS, keyword)
    await page.keyboard.press("Enter")
    await _wait_picker_rows_stable(page, cap_ms=2_000, min_ms=600)


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


async def dismiss_blocking_modals(page: Any, *, rounds: int = 6) -> list[dict]:
    """화면을 막는 잔여 확인 모달('예산현황' 등)을 '확인'/'예'로 닫는다.

    실전 실측(2026-07-02 2차 런): 카드팝업 '적용' 후 팝업 닫힘보다 **늦게** '예산현황'
    모달이 떠서, 다음 단계(F3·증빙 코드피커)가 막혀 TypeError 로 실패했다. 확인 계열만
    클릭(취소/아니오 금지). 닫은 모달 스냅샷 목록 반환.

    속도: 첫 체크는 대기 없이 즉시, 이후 400ms 폴링. **2초 연속 조용**하면 종료(지연 모달
    관찰 창 유지, 기존 최소 3s → 2s). 상한 = rounds×1.5s(기존 시그니처 호환).
    """
    seen: list[dict] = []
    cap_ms = rounds * 1_500
    interval = 400
    quiet_needed = 2_000  # 이 시간 동안 모달이 안 뜨면 종료(지연 출현 관찰 창)
    waited = 0
    quiet = 0
    while True:
        modals = await page.evaluate(js.MODALS_SNAPSHOT_JS)  # 첫 체크 즉시(고정 1.5s 선대기 제거)
        if modals:
            quiet = 0
            seen.extend(modals)
            for label in ("확인", "예"):
                btn = await page.evaluate(js.MODAL_BTN_BOX_JS, label)
                if btn:
                    await page.mouse.click(btn["x"], btn["y"])
                    break
        elif quiet >= quiet_needed:
            break
        if waited >= cap_ms:
            break
        await page.wait_for_timeout(interval)
        waited += interval
        if not modals:
            quiet += interval
    return seen


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
            for label in ("예", "확인"):
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
    errors = [m for m in modals_seen if "오류" in (m.get("title") or "")]
    if errors:
        detail = " / ".join((m.get("text") or m.get("title") or "")[:200] for m in errors[:3])
        return {"ok": False, "reason": f"저장(F7)이 ERP 오류로 거부됨: {detail}", "modals_seen": modals_seen[:6]}
    return {"ok": True, "via": "F7", "modals_seen": modals_seen[:6], "pre_modals": pre[:4]}
