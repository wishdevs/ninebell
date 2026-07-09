"""출장(국내/자차) 결의서입력 — detail 그리드 채움 스텝(진입 후 본문 문서 폼 조작).

card 와 다르게 코드 필드가 문서 폼 코드피커가 아니라 **detail RealGrid(index 1) 셀**이다
(프로브 P7). 따라서 코드 셀은 nbkit `OPEN_DETAIL_CELL_EDITOR_JS`(showEditor)+`DETAIL_EDITOR_
MAGNIFIER_JS`(돋보기 실클릭)로 피커 팝업을 연 뒤, card 가 승격한 nbkit 피커 프리미티브
(PICKER_SEARCH/READ_MULTI/SELECT/APPLY)를 그대로 재사용한다. 금액/적요는 setValue 직접 세팅.

⚠ 모든 detail 조작은 **마지막(현재) 행**을 대상으로 한다 — F3 신규 행은 맨 아래에 추가되고,
   fill_rows 는 행을 추가한 직후 그 행을 채운다(OPEN_EVDN_EDITOR_JS 의 '항상 마지막 행' 불변과
   동일 — 2패스에서 기존 행을 덮어쓰던 사고 재발 방지). 그래서 스텝은 명시 row 인덱스를 받지 않는다.
⚠ 저장(F7)은 여기서 하지 않는다 — card `steps.save_document`(F7 게이트) 재사용.

dump_partners 는 예외적으로 **카드 진입 문맥**(code_sync._run_entry_chain, CARD_WIN)에서
partner_cd 코드피커를 열어 전량 덤프한다(프로브 P4-보충) — Track B `_sync_partners` 계약.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from nbkit.browser.actions import mouse_click
from nbkit.omnisol import js_lib, selectors
from nbkit.omnisol.codepicker import (
    _norm,
    _picker_search,
    _wait_picker_rows_stable,
)

from . import js

logger = logging.getLogger(__name__)

# ── 피커 컬럼 / 검색어 상수(프로브 실측) ──────────────────────────────────────────
PARTNER_FIELDS = ["PARTNER_CD", "PARTNER_NM", "PARTNER_FG_NM", "BIZR_NO"]
BUDGET_FIELDS = ["BG_CD", "BG_NM", "BIZPLAN_NM", "BGACCT_NM"]
PROJECT_FIELDS = ["PJT_NO", "PJT_NM", "WBS_NO"]

# 예산단위 조합 규칙(D8): 부서(BG_NM) + cost_type 접두 + "여비교통비-국내출장"(BGACCT_NM 레벨).
_COST_PREFIX: dict[str, str] = {"판관비": "(판)", "제조원가": "(제)"}
TRIP_BGACCT_BASE = "여비교통비-국내출장"
# 예산 피커 검색어 — "국내출장" 검색 시 33행(부서×판/제)으로 좁혀진다(프로브 P6). 그 안에서
# 부서+BGACCT 정확매칭으로 단건 확정. "여비교통비"는 132행이라 더 넓다.
BUDGET_SEARCH_KW = "국내출장"

# 코드 셀 에디터를 여는 필드명(이름 컬럼으로 연다 — 프로브에서 NM/CD 둘 다 동작 확인).
PARTNER_CELL = "PARTNER_NM"
BUDGET_CELL = "BG_NM"
PROJECT_CELL = "PJT_NM"
BFC_PARTNER_CELL = "BFC_PARTNER_NM"


# ══════════════════════════════════════════════════════════════════════════════
# 순수 매칭 헬퍼(브라우저 불필요 — 단위 테스트 대상)
# ══════════════════════════════════════════════════════════════════════════════
def bgacct_name_for_cost_type(cost_type: str | None) -> str:
    """cost_type('판관비'|'제조원가') → 예산계정명 '(판)/(제)여비교통비-국내출장'.

    알 수 없는 cost_type 이면 ValueError(한국어) — 임의 접두 금지(잘못된 예산계정 방지).
    """
    prefix = _COST_PREFIX.get((cost_type or "").strip())
    if not prefix:
        raise ValueError(f"알 수 없는 비용구분입니다: {cost_type!r} (판관비/제조원가)")
    return f"{prefix}{TRIP_BGACCT_BASE}"


def pick_partner_row(
    options: list[dict], name: str, code: str | None = None
) -> tuple[dict | None, str | None]:
    """거래처 후보에서 PARTNER_NM **완전일치** 행 선택. 반환 (row, None) | (None, 한국어오류).

    - 완전일치 0건: 무매칭 오류(후보 나열).
    - code 주어짐: 완전일치 중 PARTNER_CD 일치를 우선(통행료 거래처 = 카탈로그 코드 확정).
    - code 없음/무해당: 완전일치가 단일 코드로 수렴하면 채택, 다건이면 모호 오류(임의선택 금지).
    """
    exact = [o for o in options if _norm(o.get("PARTNER_NM")) == _norm(name)]
    if not exact:
        cands = ", ".join(o.get("PARTNER_NM", "") for o in options[:6]) or "없음"
        return None, f"거래처 '{name}' 일치 없음(후보: {cands})"
    if code:
        by_code = [o for o in exact if str(o.get("PARTNER_CD")) == str(code)]
        if by_code:
            return by_code[0], None
    uniq = {str(o.get("PARTNER_CD")) for o in exact}
    if len(uniq) == 1:
        return exact[0], None
    cands = ", ".join(f"{o.get('PARTNER_NM')}({o.get('PARTNER_CD')})" for o in exact[:6])
    return None, f"거래처 '{name}' 후보 여러 건({cands}) — 코드로 특정 필요"


# 부서명 정규화 — 공백에 더해 구분기호('/·-')도 제거해 'user.department'(예 '인사/기획팀')와
# 예산 그리드 BG_NM(예 '인사기획팀')을 매칭한다. card 의 norm_code_name/dept_matches_budget_name
# 과 동일 취지(_norm 은 공백만 제거해 '/'가 남아 무매칭되던 실측 버그, 2026-07-06 스모크 검출).
_DEPT_SEP_RE = re.compile(r"[\s/·\-]+")


def _norm_dept(s: object) -> str:
    return _DEPT_SEP_RE.sub("", str(s or "")).lower()


def _budget_cands_desc(matches: list[dict]) -> str:
    return ", ".join(
        f"{o.get('BG_NM')}/{o.get('BIZPLAN_NM')}/{o.get('BGACCT_NM')}" for o in matches[:6]
    )


def pick_budget_row(
    options: list[dict], department: str, bgacct_nm: str
) -> tuple[dict | None, str | None]:
    """예산단위 후보에서 (BG_NM=부서) × (BGACCT_NM=bgacct_nm) 매칭 단건 선택.

    반환 (row, None) | (None, 한국어오류). 무매칭·다중(BG_CD 다름)은 오류(임의선택 금지).
    부서 매칭은 (1) 구분기호 무시 **완전일치** 1순위 → (2) 없으면 **부분포함**(단건일 때만) 폴백.
    '인사/기획팀' 은 BG_NM '인사기획팀' 과 완전일치(구분기호 제거)한다. 부분포함 폴백을 쓰면
    실제 매칭된 BG_NM 을 로그로 남긴다(리뷰 반영: 부분포함 오선택 방지 + 추적). BGACCT_NM 정확일치.
    """
    bg_ok = [o for o in options if _norm(o.get("BGACCT_NM")) == _norm(bgacct_nm)]
    if not bg_ok:
        return None, f"예산단위 조합 무매칭: {department} · {bgacct_nm} (후보 {len(options)}건)"
    dn = _norm_dept(department)
    # 1순위: 부서명 정규화 완전일치.
    matches = [o for o in bg_ok if _norm_dept(o.get("BG_NM")) == dn]
    via_partial = False
    if not matches:
        # 2순위: 부분포함(구분기호 무시) — 임의선택 방지 위해 단건일 때만 채택.
        matches = [o for o in bg_ok if dn and (dn in _norm_dept(o.get("BG_NM")) or _norm_dept(o.get("BG_NM")) in dn)]
        via_partial = True
    if not matches:
        return None, f"예산단위 조합 무매칭: {department} · {bgacct_nm} (후보 {len(options)}건)"
    codes = {str(o.get("BG_CD")) for o in matches}
    if len(codes) > 1:
        kind = "부분포함 다중" if via_partial else "다중"
        return None, f"예산단위 조합 {kind}매칭({_budget_cands_desc(matches)}) — 사업계획 확인 필요"
    if via_partial:
        logger.info(
            "예산단위 부분포함 매칭: 부서 '%s' → BG_NM '%s'(BG_CD %s)",
            department, matches[0].get("BG_NM"), matches[0].get("BG_CD"),
        )
    return matches[0], None


def pick_project_row(
    options: list[dict], name: str, wbs_no: str | None
) -> tuple[dict | None, str | None]:
    """프로젝트 후보에서 WBS_NO 정확매칭(우선) → 없으면 PJT_NM 완전일치 폴백.

    combo 가 WBS 행 단위(code=PJT_NO|WBS_NO)라 같은 프로젝트의 여러 WBS 를 WBS_NO 로 특정한다.
    반환 (row, None) | (None, 한국어오류). card fill_project_codepicker 로직 이식.
    """
    if wbs_no:
        matches = [o for o in options if _norm(o.get("WBS_NO")) == _norm(wbs_no)]
        if matches:
            return matches[0], None
    matches = [o for o in options if _norm(o.get("PJT_NM")) == _norm(name)]
    if matches:
        return matches[0], None
    return None, f"프로젝트 무매칭: {name} · WBS {wbs_no or '-'} (후보 {len(options)}건)"


def partner_options_to_rows(options: list[dict]) -> list[dict]:
    """거래처 피커 옵션(PARTNER_*) → 카탈로그 행 [{code, name, bizNo}] (PARTNER_CD 유니크)."""
    seen: set[str] = set()
    out: list[dict] = []
    for o in options:
        code = o.get("PARTNER_CD")
        if not code:
            continue
        code = str(code)
        if code in seen:
            continue
        seen.add(code)
        out.append(
            {"code": code, "name": o.get("PARTNER_NM") or "", "bizNo": o.get("BIZR_NO") or ""}
        )
    return out


# ══════════════════════════════════════════════════════════════════════════════
# detail 코드 셀 피커 공용 내부 헬퍼
# ══════════════════════════════════════════════════════════════════════════════
async def _open_detail_cell_picker(page: Any, field_name: str, label: str) -> dict:
    """detail 마지막 행 field_name 셀 → showEditor → 돋보기 실클릭 → 피커 팝업 오픈.

    캔버스 돋보기 클릭은 빗나갈 수 있어 3회 재시도(open_evdn 노드와 동일 패턴).
    반환 {ok:True} | {ok:False, reason}.
    """
    for attempt in range(1, 4):
        op = await page.evaluate(js_lib.OPEN_DETAIL_CELL_EDITOR_JS, field_name)
        if not op.get("ok"):
            continue
        rect = None
        waited = 0
        while waited < 1_000:  # 돋보기 rect 준비 폴링(상한 1s)
            await page.wait_for_timeout(100)
            waited += 100
            rect = await page.evaluate(js_lib.DETAIL_EDITOR_MAGNIFIER_JS)
            if rect:
                break
        if not rect:
            continue
        await mouse_click(page, rect["x"], rect["y"])
        for _ in range(20):  # 팝업 그리드 준비 폴링(rowcount>=0, 상한 ~6s)
            await page.wait_for_timeout(300)
            n = await page.evaluate(js_lib.PICKER_ROWCOUNT_JS)
            if isinstance(n, int) and n >= 0:
                return {"ok": True}
    return {"ok": False, "reason": f"{label} 피커 팝업이 열리지 않았습니다(돋보기 클릭 3회 실패)."}


async def _fail_close(page: Any, reason: str) -> dict:
    """실패 경로 — 열린 피커 팝업을 닫고 오류 반환(안 닫으면 다음 피커가 이 팝업을 오독)."""
    await page.evaluate(js_lib.PICKER_CLOSE_JS)
    await page.wait_for_timeout(400)
    return {"ok": False, "reason": reason}


async def _picker_gone(page: Any, *, cap_ms: int = 1_500, interval_ms: int = 150) -> bool:
    """피커 팝업이 닫혔는지 폴링 — 닫히면 True, cap_ms 내 미닫힘이면 False."""
    waited = 0
    while waited < cap_ms:
        await page.wait_for_timeout(interval_ms)
        waited += interval_ms
        n = await page.evaluate(js_lib.PICKER_ROWCOUNT_JS)
        if not isinstance(n, int) or n < 0:  # 팝업 사라짐(-1) = 닫힘.
            return True
    return False


async def _select_and_apply(
    page: Any, row_index: int, label: str, verify_field: str, expect_value: object
) -> dict:
    """피커 행 선택 → '적용' 실클릭 → **대상 셀 반영 폴링 검증** → 팝업 닫힘 검증.

    반환 {ok} | {ok:False, reason}. 적용 판정은 팝업 닫힘이 아니라 detail 셀(verify_field) 반영으로
    한다(select_evdn_code 의 8s 폴링 미러). '적용' 버튼 미발견·셀 미반영·팝업 미닫힘은 전부 실패로
    승격한다 — 특히 마지막 피커에서 적용을 놓치면 잔존 팝업이 F7 을 삼켜 팬텀 저장을 유발한다.
    """
    sel = await page.evaluate(js_lib.PICKER_SELECT_JS, row_index)
    if not sel.get("ok"):
        return await _fail_close(page, f"{label} 행 선택 실패: {sel}")
    await page.wait_for_timeout(400)
    apply_box = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
    if not apply_box:
        return await _fail_close(page, f"{label} '적용' 버튼을 찾지 못했습니다(피커 팝업 구조 변경?).")
    await mouse_click(page, apply_box["x"], apply_box["y"])
    # 셀 반영 폴링(300ms×27 ≈ 8s) — 정규화 후 완전일치 또는 상호포함(표시명 절삭 대비)이면 반영.
    want = _norm(expect_value)
    actual = ""
    for _ in range(27):
        await page.wait_for_timeout(300)
        rd = await page.evaluate(js.READ_DETAIL_CELL_JS, [verify_field])
        actual = (rd.get("values") or {}).get(verify_field, "")
        cell = _norm(actual)
        if want and (want == cell or (cell and (want in cell or cell in want))):
            break
    else:
        return await _fail_close(page, f"{label} 적용 후 셀 미반영(기대 '{expect_value}'·실제 '{actual}')")
    # 팝업 닫힘 검증 — 잔존 피커 팝업은 F7 을 삼켜 팬텀 저장을 유발한다.
    if not await _picker_gone(page):
        return await _fail_close(page, f"{label} 적용 후 피커 팝업이 닫히지 않았습니다.")
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
# 채움 스텝(그래프 fill_rows 노드가 행별로 호출)
# ══════════════════════════════════════════════════════════════════════════════
async def _fill_partner_cell(
    page: Any, open_field: str, keyword: str, expect_name: str, code: str | None, label: str
) -> dict:
    """거래처류 코드 셀 공용: 셀 피커 열기 → 검색(Enter) → 이름 완전일치 선택 → 적용."""
    op = await _open_detail_cell_picker(page, open_field, label)
    if not op.get("ok"):
        return op
    # 거래처 팝업 검색창(customTextBox)은 클라이언트 필터/정렬이라 Enter 직후 재조회가
    # 정착하기 전 읽으면 필터 전 상단행이 잡히는 레이스가 있다(스모크 1/10 관측). 매칭이
    # 안 나오면 재검색·재독을 최대 3회 반복해 정착을 기다린다(정상 매칭이면 1회에 끝).
    row: dict | None = None
    err: str | None = None
    for attempt in range(3):
        await _picker_search(page, keyword)
        read = await page.evaluate(js_lib.PICKER_READ_MULTI_JS, [PARTNER_FIELDS, 0])
        row, err = pick_partner_row(read.get("options") or [], expect_name, code)
        if not err:
            break
        await page.wait_for_timeout(500)
    if err:
        return await _fail_close(page, err)
    # 검증 셀 = 연 셀(거래처=PARTNER_NM, 상대계정=BFC_PARTNER_NM). 기대값 = 선택 행의 PARTNER_NM.
    fin = await _select_and_apply(page, row["i"], label, open_field, row.get("PARTNER_NM") or expect_name)
    if not fin.get("ok"):
        return fin
    return {"ok": True, "code": row.get("PARTNER_CD"), "name": row.get("PARTNER_NM")}


async def fill_partner(page: Any, code: str, name: str) -> dict:
    """통행료 거래처(공공기관) 셀 채움 — 이름 검색 → 완전일치(코드 우선) 선택. 반환 {ok, code, name}."""
    return await _fill_partner_cell(page, PARTNER_CELL, name, name, code, "거래처")


async def fill_partner_by_search(page: Any, keyword: str) -> dict:
    """거래처 셀에 본인 이름(유류비 지원 행) 검색 → 완전일치 단건 선택. 반환 {ok, code, name}."""
    return await _fill_partner_cell(page, PARTNER_CELL, keyword, keyword, None, "거래처(본인)")


async def fill_bfc_partner(page: Any, name: str) -> dict:
    """⚠ DEPRECATED(사용 금지) — BFC_PARTNER 셀은 getValue 불가 컬럼이라 showEditor 가 본 거래처
    (PARTNER) 셀로 폴백해 거래처를 덮어썼다(2026-07-06 검출). 실 상대계정거래처는 문서 하단 폼
    코드피커다 → :func:`fill_counter_partner` 사용. 함수는 이력 보존용으로 남긴다(호출 금지)."""
    return await _fill_partner_cell(page, BFC_PARTNER_CELL, name, name, None, "상대계정거래처")


async def lookup_partner_code(page: Any, name: str) -> str | None:
    """거래처 팝업에서 이름 검색 → 완전일치 PARTNER_CD 반환(선택/적용 없음·닫기). 상대계정 코드용.

    detail PARTNER 셀 피커로 거래처 팝업을 열어 **검색만** 하고 닫는다(선택/적용 안 함 → 행 추가·
    PARTNER 변경 없음). 반환 code | None(무매칭). 코드는 행별 불변이라 fill_rows 가 1회만 조회한다.
    customTextBox 필터 레이스 대비 재검색 3회.
    """
    if not (await _open_detail_cell_picker(page, PARTNER_CELL, "상대계정거래처(코드조회)")).get("ok"):
        return None
    row: dict | None = None
    err: str | None = None
    for _ in range(3):
        await _picker_search(page, name)
        read = await page.evaluate(js_lib.PICKER_READ_MULTI_JS, [PARTNER_FIELDS, 0])
        row, err = pick_partner_row(read.get("options") or [], name, None)
        if not err:
            break
        await page.wait_for_timeout(500)
    await page.evaluate(js_lib.PICKER_CLOSE_JS)
    await page.wait_for_timeout(400)
    return row.get("PARTNER_CD") if (row and not err) else None


async def set_counter_partner(page: Any, code: str) -> dict:
    """상대계정거래처 = detail 마지막 행 **BFC_PARTNER_CD 직접 setValue**(하단 폼 위젯 우회).

    실측(2026-07-07): 하단 폼 코드피커 '적용'은 활성 detail 에디터에 반영돼 빈 행을 추가하는
    함정이라 사용 금지. 대신 `grid.setValue(row,'BFC_PARTNER_CD',code)` — 행 추가 없이 dataSource
    에 반영되고 **저장 전표에 상대계정거래처로 persist**(실저장+재조회 확인). 반영 코드 검증.
    반환 {ok, after} | {ok:False, reason}.
    """
    r = await page.evaluate(js.SET_BFC_PARTNER_JS, code)
    if not r.get("ok"):
        return {"ok": False, "reason": r.get("reason") or "상대계정거래처 세팅 실패"}
    if str(r.get("after") or "") != str(code):
        return {"ok": False, "reason": f"상대계정거래처 반영 불일치(기대 {code}·실제 {r.get('after')})"}
    return {"ok": True, "after": r.get("after")}


async def fill_budget_fixed(page: Any, department: str, cost_type: str) -> dict:
    """예산단위 셀 = "여비교통비-국내출장" 고정 — 부서 + cost_type(판/제) 조합 정확매칭 선택.

    반환 {ok, code, name} | {ok:False, reason}. 무/다중매칭 시 후보 나열 오류(임의선택 금지).
    """
    try:
        bgacct_nm = bgacct_name_for_cost_type(cost_type)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    op = await _open_detail_cell_picker(page, BUDGET_CELL, "예산단위")
    if not op.get("ok"):
        return op
    await _picker_search(page, BUDGET_SEARCH_KW)
    read = await page.evaluate(js_lib.PICKER_READ_MULTI_JS, [BUDGET_FIELDS, 0])
    row, err = pick_budget_row(read.get("options") or [], department, bgacct_nm)
    if err:
        return await _fail_close(page, err)
    fin = await _select_and_apply(page, row["i"], "예산단위", "BG_NM", row.get("BG_NM"))
    if not fin.get("ok"):
        return fin
    return {
        "ok": True,
        "code": row.get("BG_CD"),
        "name": f"{row.get('BG_NM')} · {row.get('BIZPLAN_NM')} · {row.get('BGACCT_NM')}",
    }


async def fill_project(page: Any, project: dict) -> dict:
    """프로젝트 셀 채움 — PJT_NM 검색 → WBS_NO 정확매칭(폴백 PJT_NM). 반환 {ok, code, name}.

    project = {code(PJT_NO|WBS_NO), name(PJT_NM), wbsNo?} (card 피커와 동일 단위).
    """
    name = (project.get("name") or "").strip()
    wbs_no = (project.get("wbsNo") or "").strip()
    if not wbs_no and "|" in (project.get("code") or ""):
        wbs_no = project["code"].split("|", 1)[1].strip()
    if not name and not wbs_no:
        return {"ok": False, "reason": "프로젝트 정보가 없습니다(name·wbsNo 모두 비어 있음)."}
    op = await _open_detail_cell_picker(page, PROJECT_CELL, "프로젝트")
    if not op.get("ok"):
        return op
    await _picker_search(page, name or wbs_no)
    read = await page.evaluate(js_lib.PICKER_READ_MULTI_JS, [PROJECT_FIELDS, 0])
    row, err = pick_project_row(read.get("options") or [], name, wbs_no)
    if err:
        return await _fail_close(page, err)
    fin = await _select_and_apply(page, row["i"], "프로젝트", "PJT_NM", row.get("PJT_NM"))
    if not fin.get("ok"):
        return fin
    return {"ok": True, "code": row.get("PJT_NO"), "name": row.get("PJT_NM")}


# 금액 세팅 대상 컬럼(프로브 trip_amount, 2026-07-07 실측):
#   - 공급가(거래금액) = SPPRC_AMT2 ← 사용자가 채우라는 필드(정정). primary.
#   - 공급가액 = SPPRC_AMT, 합계 = TOTAL_AMT.
# ⚠ setValue 는 ERP 변경 핸들러를 발화하지 않아 **자동계산 없음**(SPPRC_AMT2 세팅해도 SPPRC_AMT/
#   TOTAL_AMT/마스터 DETAIL_SUM_AMT 는 0 유지, 실측). 국내 자차는 부가세 0 → 세 값이 동일하므로
#   병행 명시 세팅한다(서버가 거래금액에서 파생하면 값이 같아 무해, Phase 6 실저장에서 확정 후 축소).
_AMOUNT_FIELDS: list[tuple[str, str]] = [
    ("SPPRC_AMT2", "공급가(거래금액)"),
    ("SPPRC_AMT", "공급가액"),
    ("TOTAL_AMT", "합계금액"),
]


async def set_transaction_amount(page: Any, amount: int) -> dict:
    """공급가(거래금액)=SPPRC_AMT2 primary + 공급가액·합계 동일값 세팅 + **각 반영 금액 검증**.

    사용자 정정(2026-07-07): 금액은 공급가액이 아니라 '공급가액(거래금액)'(SPPRC_AMT2)에 채운다.
    반환 {ok, after} | {ok:False, reason}. 어느 필드든 반영 금액(콤마 제거)이 요청과 다르면 실패
    (잘못된 금액 저장 방지). 자동계산 없음(setValue 핸들러 미발화) — _AMOUNT_FIELDS 주석 참조.
    """
    primary_after = None
    for field, label in _AMOUNT_FIELDS:
        r = await page.evaluate(js.SET_DETAIL_CELL_JS, {"field": field, "value": amount})
        if not r.get("ok"):
            return {"ok": False, "reason": f"{label}({field}) 세팅 실패: {r.get('reason')}"}
        after_raw = str(r.get("after") or "").replace(",", "").strip()
        if after_raw != str(amount):
            return {"ok": False, "reason": f"{label} 반영 불일치(기대 {amount:,}·실제 {r.get('after')})"}
        if primary_after is None:
            primary_after = r.get("after")
    return {"ok": True, "after": primary_after}


async def type_amount(page: Any, amount: int) -> dict:
    """공급가액(거래금액 SPPRC_AMT2) = **셀 에디터 실 타이핑 + 예산현황 확인**(2026-07-09 규명).

    ⚠ setValue(set_transaction_amount) 는 금액 입력 트리거(예산현황 팝업)를 발화 안 해 파생상태가
    미완 → 저장 시 "데이터베이스 처리 중 오류". 실제로 입력하면 예산현황 팝업이 뜨고 확인해야
    예산집행·분개가 완성돼 저장이 된다. 숫자 에디터를 열어 select_text→타이핑→Tab(커밋·핸들러 발화)
    → 예산현황 확인 → SPPRC_AMT/TOTAL_AMT 자동계산. 반영 검증. 반환 {ok, after}|{ok:False, reason}.
    """
    op = await page.evaluate(js_lib.OPEN_DETAIL_CELL_EDITOR_JS, "SPPRC_AMT2")
    if not op.get("ok"):
        return {"ok": False, "reason": f"금액 에디터 열기 실패: {op.get('reason')}"}
    await page.wait_for_timeout(500)
    rect = await page.evaluate(js.AMOUNT_EDITOR_INPUT_JS)
    if not rect or not rect.get("id"):
        return {"ok": False, "reason": "금액 숫자 에디터(gridDetail_number)를 찾지 못함"}
    loc = page.locator(f'input[id="{rect["id"]}"]')
    await loc.click()
    await page.wait_for_timeout(150)
    await loc.select_text()  # 기존 '0' 선택(Meta+A 는 에디터 닫힘 유발이라 금지).
    await page.wait_for_timeout(100)
    await loc.press_sequentially(str(amount), delay=90)
    await page.wait_for_timeout(200)
    await loc.press("Tab")  # 커밋 → blur/change 로 예산현황 트리거 발화(Enter 보다 확실).
    # 예산현황 팝업 확인(뜨는 모달을 확인/예 로 닫는다).
    modals_seen: list[str] = []
    for _ in range(8):
        await page.wait_for_timeout(600)
        modals = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
        if not modals:
            break
        modals_seen.append(str((modals[0] or {}).get("title") or ""))
        clicked = False
        for label in ("확인", "예"):
            btn = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, label)
            if btn:
                await mouse_click(page, btn["x"], btn["y"])
                clicked = True
                break
        if not clicked:
            break
    after = await page.evaluate(js.READ_AMT_JS)
    got = str(after.get("SPPRC_AMT2") or "").replace(",", "").strip()
    if got != str(amount):
        return {"ok": False, "reason": f"금액 반영 불일치(기대 {amount:,}·실제 {after.get('SPPRC_AMT2')})", "modals": modals_seen}
    return {"ok": True, "after": after, "modals": modals_seen}


async def register_counter_partner(page: Any, self_name: str) -> dict:
    """상대계정거래처 = 작성자 본인 — **부가선택 위젯 🔍 → 검색 → 팝업 행 더블클릭**(2026-07-09 확정).

    실제 상대계정거래처 UI 는 detail 셀이 아니라 하단 부가선택 테이블(내역코드/내역명)이다. BFC_PARTNER_CD
    setValue(set_counter_partner)는 숨김필드만 세팅해 화면 미표시라 폐기. 위젯 🔍 로 거래처 팝업을 열어
    본인명 검색 → 행 더블클릭하면 등록된다. **부작용: detail 빈 행 1개 추가(ERP 동작)** → 호출측이
    `delete_blank_row` 로 제거. 등록 성공 신호 = 빈 행 추가(행수 +1). 반환 {ok}|{ok:False, reason}.
    """
    before = await page.evaluate(js.DETAIL_ROWS_JS)
    before_n = int(before.get("n") or 0)
    row = None
    err = "부가선택 위젯 열기 실패"
    for _ in range(3):
        if not await page.evaluate(js.COUNTER_SCROLL_JS):
            await page.wait_for_timeout(600)
            continue
        await page.wait_for_timeout(600)
        box = await page.evaluate(js.COUNTER_PICKER_BOX_JS)
        if not box:
            await page.wait_for_timeout(600)
            continue
        await mouse_click(page, box["x"], box["y"])
        n = -1
        for _ in range(25):
            await page.wait_for_timeout(300)
            n = await page.evaluate(js_lib.PICKER_ROWCOUNT_JS)
            if isinstance(n, int) and n > 50:
                break
        await _picker_search(page, self_name)
        await page.wait_for_timeout(600)
        rd = await page.evaluate(js_lib.PICKER_READ_MULTI_JS, [PARTNER_FIELDS, 0])
        row, err = pick_partner_row(rd.get("options") or [], self_name, None)
        if not err:
            break
        await page.evaluate(js_lib.PICKER_CLOSE_JS)
        await page.wait_for_timeout(500)
    if not row:
        return {"ok": False, "reason": f"상대계정 본인('{self_name}') 검색 실패: {err}"}
    rr = await page.evaluate(js.PICKER_ROW_RECT_JS, row["i"])
    if not rr:
        return {"ok": False, "reason": "상대계정 팝업 행 좌표 없음"}
    await page.mouse.dblclick(rr["x"], rr["y"])
    # 적용 반영 = detail 빈 행 +1 — 나타날 때까지 폴링(대기 배율에 무관하게 견고).
    for _ in range(20):
        await page.wait_for_timeout(400)
        cur = await page.evaluate(js.DETAIL_ROWS_JS)
        if int(cur.get("n") or 0) > before_n:
            return {"ok": True}
    return {"ok": False, "reason": "상대계정 등록 실패(적용 후 빈 행 미추가 — 미반영 의심)"}


async def delete_blank_row(page: Any) -> dict:
    """상대계정 등록 시 추가된 빈(마지막) detail 행 삭제 — 빈 행 선택 → 툴바 삭제 버튼 + 확인 모달.

    데이터 행(거래처 있는 행)은 유지된다(실측). 빈 행 없으면 no-op. 반환 {ok}|{ok:False, reason}.
    """
    rows = await page.evaluate(js.DETAIL_ROWS_JS)
    before_n = int(rows.get("n") or 0)
    blanks = [r["i"] for r in (rows.get("rows") or []) if not r.get("PARTNER")]
    if not blanks:
        return {"ok": True, "note": "빈 행 없음"}
    bi = max(blanks)  # 마지막(추가된) 빈 행.
    pt = await page.evaluate(js.DETAIL_ROW_CLICK_JS, bi)
    await mouse_click(page, pt["x"], pt["y"])
    await page.wait_for_timeout(1200)  # 빈 행 선택 확정(배율 대비 넉넉히).
    box = await page.evaluate(js.BTN_BOX_JS, selectors.BTN_DELETE)
    if not box:
        return {"ok": False, "reason": "삭제 버튼을 찾지 못함"}
    await mouse_click(page, box["x"], box["y"])
    # 확인 모달 처리 + 행수 감소를 폴링(대기 배율에 무관하게 견고). 20회.
    for _ in range(20):
        await page.wait_for_timeout(500)
        modals = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
        if modals:
            for label in ("예", "확인", "삭제"):
                btn = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, label)
                if btn:
                    await mouse_click(page, btn["x"], btn["y"])
                    break
            continue
        cur = await page.evaluate(js.DETAIL_ROWS_JS)
        if int(cur.get("n") or 99) < before_n:
            return {"ok": True}
    return {"ok": False, "reason": f"빈 행 삭제 실패(행수 {before_n} 유지)"}


async def set_master_total(page: Any, total: int) -> dict:
    """마스터 상세합계금액(DETAIL_SUM_AMT) = 전 행 합계 명시 세팅 + 반영 검증. 반환 {ok, after}.

    setValue 기반 행 채움은 ERP 합계 재계산 핸들러를 발화하지 않아 마스터 합계가 마지막 detail
    행을 누락한다(실측 2026-07-07). 전 행 채운 뒤 총액을 직접 세팅해 저장값을 정합시킨다.
    """
    r = await page.evaluate(js.SET_MASTER_TOTAL_JS, total)
    if not r.get("ok"):
        return {"ok": False, "reason": r.get("reason") or "마스터 합계 세팅 실패"}
    after_raw = str(r.get("after") or "").replace(",", "").strip()
    if after_raw != str(total):
        return {"ok": False, "reason": f"마스터 합계 반영 불일치(기대 {total:,}·실제 {r.get('after')})"}
    return {"ok": True, "after": r.get("after")}


async def set_invoice_date(page: Any, ymd_compact: str) -> dict:
    """(세금)계산서일(START_DT) 셀 = 행별 증빙일(통행료/유류비 결제일) setValue 직접 세팅 + 반영 검증.

    START_DT 는 detail 그리드(index 1) 날짜 셀(헤더 "(세금)계산서일", 프로브 trip_amount_cols 실측).
    compact 'YYYYMMDD' 로 세팅하면 셀은 Date 객체로 보관한다 → 검증은 `READ_DETAIL_DATE_JS`(Date 를
    브라우저 로컬 Y/M/D compact 로 정규화)로 읽어 비교한다. String(Date) 숫자추출은 'Jul' 등이 섞여
    오판하므로 금지(2026-07-07 실측: 'Tue Jul 07 2026 ...' → 잘못된 비교). 반환 {ok, after}|{ok:False}.
    """
    if len(str(ymd_compact or "")) != 8:
        return {"ok": False, "reason": f"계산서일 형식 오류: {ymd_compact!r}"}
    w = await page.evaluate(js.SET_DETAIL_CELL_JS, {"field": "START_DT", "value": ymd_compact})
    if not w.get("ok"):
        return {"ok": False, "reason": w.get("reason") or "계산서일 세팅 실패"}
    r = await page.evaluate(js.READ_DETAIL_DATE_JS, "START_DT")
    got = str(r.get("compact") or "") if r.get("ok") else ""
    if got != ymd_compact:
        detail = r.get("raw") if r.get("ok") else r.get("reason")
        return {"ok": False, "reason": f"계산서일 반영 불일치(기대 {ymd_compact}·실제 {detail})"}
    return {"ok": True, "after": r.get("raw")}


async def set_row_note(page: Any, text: str) -> dict:
    """적요(NOTE_DC) 셀 setValue 직접 세팅 + 반영 검증. 반환 {ok, after}."""
    r = await page.evaluate(js.SET_DETAIL_CELL_JS, {"field": "NOTE_DC", "value": text})
    if not r.get("ok"):
        return {"ok": False, "reason": r.get("reason") or "적요 세팅 실패"}
    return {"ok": True, "after": r.get("after")}


# ══════════════════════════════════════════════════════════════════════════════
# 거래처 카탈로그 덤프(Track B _sync_partners 계약) — 카드 진입 문맥에서 호출
# ══════════════════════════════════════════════════════════════════════════════
# 거래처 팝업 빈검색 상한(프로브: 카드 문맥 500 cap). 정확히 이 값이면 잘렸을 수 있어 페이징한다.
PARTNER_PICKER_CAP = 500


async def dump_partners(page: Any, *, max_rounds: int = 60) -> list[dict]:
    """거래처(partner_cd) 코드피커 빈검색 전량 — 끝행 포커스+ArrowDown 페이징 후 유니크.

    카드 진입 체인(code_sync._run_entry_chain, CARD_WIN) 문맥에서 호출한다(프로브 P4-보충:
    카드 일괄적용 폼에 partner_cd 코드피커 존재). 빈검색 500 cap 이라 projects 와 동일하게
    끝행+ArrowDown 으로 서버 페이징을 태워 전량 로드한다. 반환 [{code, name, bizNo}].
    """
    # 카드 진입 직후 CARD_WIN 일괄적용 폼이 뜨기까지 레이스가 있어 버튼 출현을 폴링(상한 ~9s,
    # 프로브 P4-보충: 진입 후 ~1.5s 뒤 CARD_WIN 준비). 준비되면 클릭해 팝업을 연다.
    box = None
    for _ in range(30):
        box = await page.evaluate(js_lib.picker_btn_js("partner_cd"))
        if box:
            break
        await page.wait_for_timeout(300)
    if not box:
        logger.warning("거래처 코드피커(partner_cd) 버튼 없음 — 카드 문맥 확인 필요")
        return []
    await page.mouse.click(box["x"], box["y"])
    await _wait_picker_rows_stable(page, cap_ms=3_000)
    await _picker_search(page, "")
    prev = await page.evaluate(js_lib.PICKER_ROWCOUNT_JS)
    stable = 0
    for rnd in range(1, max_rounds + 1):
        f = await page.evaluate(js_lib.PICKER_FOCUS_LAST_JS)
        if not f.get("ok"):
            logger.warning("거래처 스크롤 r%d — 끝행 포커스 실패: %s", rnd, f)
            break
        for _ in range(30):
            await page.keyboard.press("ArrowDown", delay=30)
        await page.wait_for_timeout(3_000)
        cur = await page.evaluate(js_lib.PICKER_ROWCOUNT_JS)
        logger.info("거래처 스크롤 r%d — rows=%s(prev=%s) stable=%d", rnd, cur, prev, stable)
        if not isinstance(cur, int) or cur <= prev:
            stable += 1
            if stable >= 3:
                break
            await page.wait_for_timeout(2_000)
        else:
            stable = 0
        prev = max(prev, cur if isinstance(cur, int) else prev)
    read = await page.evaluate(js_lib.PICKER_READ_MULTI_JS, [PARTNER_FIELDS, 0])
    await page.evaluate(js_lib.PICKER_CLOSE_JS)
    await page.wait_for_timeout(400)
    return partner_options_to_rows(read.get("options") or [])
