"""출장(국내/자차) 결의서입력 — detail 그리드 채움 스텝(진입 후 본문 문서 폼 조작).

card 와 다르게 코드 필드가 문서 폼 코드피커가 아니라 **detail RealGrid(index 1) 셀**이다
(프로브 P7). 따라서 코드 셀은 nbkit `OPEN_DETAIL_CELL_EDITOR_JS`(showEditor)+`DETAIL_EDITOR_
MAGNIFIER_JS`(돋보기 실클릭)로 피커 팝업을 연 뒤, card 가 승격한 nbkit 피커 프리미티브
(PICKER_SEARCH/READ_MULTI/SELECT/APPLY)를 그대로 재사용한다. 금액/적요는 setValue 직접 세팅.

⚠ 모든 detail 조작은 **마지막(현재) 행**을 대상으로 한다 — F3 신규 행은 맨 아래에 추가되고,
   fill_rows 는 행을 추가한 직후 그 행을 채운다(OPEN_EVDN_EDITOR_JS 의 '항상 마지막 행' 불변과
   동일 — 2패스에서 기존 행을 덮어쓰던 사고 재발 방지). 그래서 스텝은 명시 row 인덱스를 받지 않는다.
⚠ 저장(F7)은 여기서 하지 않는다 — card `steps.save_document`(F7 게이트) 재사용.

확인 규율(OMNISOL_NOTES §10, `nbkit.omnisol.verify`): **세팅·클릭 호출의 성공은 반영의 증거가
아니다.** 이 파일의 스텝은 값을 넣은 뒤 반드시 리더로 재독해 확인한다 —
  * 팝업 생명주기는 **개수 변화**(POPUP_COUNT_JS)로 본다. `PICKER_ROWCOUNT_JS` 는 '최상단 비-법인
    카드 k-window'를 잡으므로, 앞 피커가 안 닫혔으면 새 팝업이 안 떠도 스테일 팝업이 ready 로
    읽힌다(voucher 부서팝업 46행 오독과 동종 구조).
  * 그리드 셀 반영은 `js_lib.GRID_CELL_VALUE_JS`(Date/콤마 정규화 포함)로 재독한다.
  * 파괴적 액션(F6 삭제)만은 예외 — **확인 불가면 진행이 아니라 스킵**한다(아래 delete_blank_row).
반환 dict 컨벤션: {"ok": bool, "reason"?: 하드 실패 사유, "warn"?: 확인 불가 경고}. 노드는
ok=False 면 단락하고, warn 은 로그로 노출한다(반영을 단정하지 않는다).

dump_partners 는 예외적으로 **카드 진입 문맥**(code_sync._run_entry_chain, CARD_WIN)에서
partner_cd 코드피커를 열어 전량 덤프한다(프로브 P4-보충) — Track B `_sync_partners` 계약.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from nbkit.browser.actions import mouse_click
from nbkit.omnisol import js_lib, selectors, verify
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
async def _popup_count(page: Any) -> int:
    """보이는 k-window 팝업 개수(읽기 전용). 못 읽으면 0 으로 본다(개수 변화 판정의 기준선)."""
    n = await page.evaluate(js_lib.POPUP_COUNT_JS)
    return n if isinstance(n, int) else 0


def _cell_matches(want: str, actual: object) -> bool:
    """셀 재독값이 기대값에 도달했는지 — 정규화 완전일치 또는 상호포함(표시명 절삭 대비)."""
    cell = _norm(actual)
    return bool(want) and (want == cell or (bool(cell) and (want in cell or cell in want)))


def _read_detail_cell(page: Any, field: str):
    """detail 그리드(index 1) 마지막 행의 한 필드 재독 코루틴 팩토리(verify.confirm read 인자)."""
    return lambda: page.evaluate(js_lib.GRID_CELL_VALUE_JS, {"index": 1, "field": field})


def _cell_unreadable(v: Any) -> bool:
    """GRID_CELL_VALUE_JS 가 ok:false = 그리드/행을 못 읽음 → '값이 틀림'이 아니라 확인 불가."""
    return not (isinstance(v, dict) and v.get("ok"))


async def _close_picker_verified(page: Any) -> str | None:
    """피커 팝업 닫기 + **팝업 개수 감소 확인**. 정상이면 None, 미닫힘이면 경고 문구 반환.

    ⚠ 닫힘을 `PICKER_ROWCOUNT_JS<0`(최상단 팝업 소멸)으로 보면 아래에 잔존 팝업이 있을 때
    오판한다 — 개수 변화로만 확정한다. 잔존 팝업은 다음 피커의 오독(최상단 규칙)과 F7 삼킴
    (팬텀 저장)의 직접 원인이라 '닫았다'를 단정하면 안 된다.
    """
    before = await _popup_count(page)
    await page.evaluate(js_lib.PICKER_CLOSE_JS)
    if before <= 0:  # 애초에 열린 팝업이 없다 — 닫을 것도 없음.
        return None
    chk = await verify.confirm_popup_count(
        page,
        less_than=before,
        timing=verify.ASYNC,
        reapply=lambda: page.evaluate(js_lib.PICKER_CLOSE_JS),
    )
    return None if chk else chk.reason


async def _open_detail_cell_picker(page: Any, field_name: str, label: str) -> dict:
    """detail 마지막 행 field_name 셀 → showEditor → 돋보기 실클릭 → 피커 팝업 오픈.

    캔버스 돋보기 클릭은 빗나갈 수 있어 3회 재시도(open_evdn 노드와 동일 패턴).
    반환 {ok:True} | {ok:False, reason}.

    ⚠ 오픈 판정은 **팝업 개수 증가**로 한다. 예전처럼 `PICKER_ROWCOUNT_JS>=0`(최상단 비-법인카드
      k-window 의 행수)만 보면, 앞 피커가 안 닫혀 있을 때 새 팝업이 안 떠도 **스테일 팝업**이
      ready 로 읽혀 그대로 통과한다(그 뒤 검색·선택이 엉뚱한 팝업에 나간다). 개수가 늘어난 것을
      확인한 뒤에야 '그리드가 응답 가능한지'(rowcount>=0)를 본다.
    """

    async def _open_editor() -> Any:
        return await page.evaluate(js_lib.OPEN_DETAIL_CELL_EDITOR_JS, field_name)

    async def _click_magnifier() -> None:
        # 재시도 때는 rect 를 다시 읽는다 — 에디터가 닫혔다 열리면 좌표가 바뀐다.
        r = await page.evaluate(js_lib.DETAIL_EDITOR_MAGNIFIER_JS)
        if r:
            await mouse_click(page, r["x"], r["y"])

    for attempt in range(3):
        # ⚠ 재시도 전에 **직전 시도가 남긴 팝업을 닫는다**. 안 닫으면 다음 시도의 기준선(before)이
        #   이미 +1 이라 '개수 증가'가 스테일 팝업으로 충족돼 오픈 확인이 무력화된다.
        if attempt:
            await _close_picker_verified(page)
        before = await _popup_count(page)
        op = await _open_editor()
        if not op.get("ok"):
            continue
        # 돋보기 rect 준비 — 고정 100ms×10 폴링을 커널 재시도로 대체(대기가 실시간이라
        # delay_scale 로 관찰창이 쪼그라들지 않는다). 안 뜨면 에디터를 다시 연다.
        mag = await verify.confirm(
            lambda: page.evaluate(js_lib.DETAIL_EDITOR_MAGNIFIER_JS),
            lambda r: isinstance(r, dict) and r.get("x") is not None,
            timing=verify.ASYNC,
            what=f"{label} 셀 돋보기 좌표",
            expected="rect",
            reapply=_open_editor,
        )
        if not mag:
            continue
        await mouse_click(page, mag.actual["x"], mag.actual["y"])
        opened = await verify.confirm_popup_count(
            page, more_than=before, timing=verify.ASYNC, reapply=_click_magnifier
        )
        if not opened:
            continue
        ready = await verify.confirm(
            lambda: page.evaluate(js_lib.PICKER_ROWCOUNT_JS),
            lambda n: isinstance(n, int) and n >= 0,
            timing=verify.ASYNC,
            what=f"{label} 피커 그리드 준비",
            expected=">=0",
        )
        if ready:
            return {"ok": True}
    return {"ok": False, "reason": f"{label} 피커 팝업이 열리지 않았습니다(돋보기 클릭 3회 실패)."}


async def _fail_close(page: Any, reason: str) -> dict:
    """실패 경로 — 열린 피커 팝업을 닫고 오류 반환(안 닫으면 다음 피커가 이 팝업을 오독).

    닫힘까지 확인하되, 실패해도 **원래 실패 사유를 덮지 않는다**(보조 조건 = 경고 덧붙임).
    재시도 루프(저장 재시도 → menu_nav 재진입)에서 잔존 팝업이 다음 사이클로 넘어가는 것을 막는다.
    """
    warn = await _close_picker_verified(page)
    if warn:
        reason = f"{reason} / ⚠ 실패 정리 중 피커 팝업 미닫힘: {warn}"
    return {"ok": False, "reason": reason}


async def _search_and_pick(
    page: Any, keyword: str, fields: list[str], pick: Any, *, rounds: int = 3
) -> tuple[dict | None, str | None]:
    """피커 검색 → **그리드 응답 확인** → 후보 읽기 → pick(options). 무매칭이면 재검색(rounds 회).

    ⚠ 팝업 검색창(customTextBox)은 클라이언트 필터/서버 재조회라 Enter 직후 정착 전에 읽으면
      **필터 전 상단행**이 잡힌다(스모크 1/10 관측). 정착 전 읽기가 우연히 완전일치를 만들면
      틀린 행을 확정하므로, 읽기 전에 그리드가 응답 가능한지 확인하고 무매칭이면 재검색으로
      정착을 기다린다(정상 매칭이면 1회에 끝나 추가 지연 0).
    """
    row: dict | None = None
    err: str | None = "검색 결과를 읽지 못했습니다"
    for _ in range(rounds):
        await _picker_search(page, keyword)
        await verify.confirm(
            lambda: page.evaluate(js_lib.PICKER_ROWCOUNT_JS),
            lambda n: isinstance(n, int) and n >= 0,
            timing=verify.ASYNC,
            what=f"'{keyword}' 검색 결과 그리드",
            expected=">=0",
            reapply=lambda: _picker_search(page, keyword),
        )
        read = await page.evaluate(js_lib.PICKER_READ_MULTI_JS, [fields, 0])
        row, err = pick(read.get("options") or [])
        if not err:
            break
    return row, err


async def _select_and_apply(
    page: Any, row_index: int, label: str, verify_field: str, expect_value: object
) -> dict:
    """피커 행 선택 → '적용' 실클릭 → **대상 셀 반영 확인** → 팝업 닫힘 확인.

    반환 {ok} | {ok:True, warn} | {ok:False, reason}. 적용 판정은 팝업 닫힘이 아니라 detail
    셀(verify_field) 반영으로 한다(select_evdn_code 미러). '적용' 버튼 미발견·셀 값 불일치·팝업
    미닫힘은 전부 하드 실패다 — 특히 마지막 피커에서 적용을 놓치면 잔존 팝업이 F7 을 삼켜
    팬텀 저장을 유발한다.

    ⚠ 재시도 때 **'적용'을 다시 클릭**한다(reapply). 튕겨나간 적용은 기다린다고 붙지 않는다 —
      기존 8s 폴링은 '대기 후 재확인'만 해서 이 경우를 영영 못 살렸다.
    ⚠ 셀을 **읽지 못하는**(그리드 미접근) 경우는 '값이 틀림'이 아니라 확인 불가로 분류해 warn 을
      달고 진행한다(리더 오탐이 멀쩡한 플로우를 끊지 않게 하는 안전판).
    """
    sel = await page.evaluate(js_lib.PICKER_SELECT_JS, row_index)
    if not sel.get("ok"):
        return await _fail_close(page, f"{label} 행 선택 실패: {sel}")
    # 선택 확정 대기 — RealGrid 캔버스라 '행이 선택됐다'를 읽을 리더가 없다(확인 불가한 자리의
    # 대기는 유지한다). 적용 자체는 아래에서 셀 반영으로 확인한다.
    await page.wait_for_timeout(400)
    apply_box = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
    if not apply_box:
        return await _fail_close(page, f"{label} '적용' 버튼을 찾지 못했습니다(피커 팝업 구조 변경?).")
    before = await _popup_count(page)

    async def _click_apply() -> None:
        await mouse_click(page, apply_box["x"], apply_box["y"])

    await _click_apply()
    want = _norm(expect_value)
    chk = await verify.confirm(
        _read_detail_cell(page, verify_field),
        lambda v: not _cell_unreadable(v) and _cell_matches(want, (v.get("raw") or {}).get(verify_field)),
        timing=verify.ASYNC,
        what=f"{label} 셀({verify_field}) 반영",
        expected=expect_value,
        reapply=_click_apply,
        unknown_when=_cell_unreadable,
    )
    if chk.mismatch:
        return await _fail_close(page, f"{label} 적용 후 셀 미반영 — {chk.reason}")
    out: dict = {"ok": True}
    if not chk:  # 확인 불가 — 반영을 단정하지 않고 경고만 남긴다.
        out["warn"] = chk.reason
    # 팝업 닫힘 확인 — 개수 감소로 본다(잔존 팝업은 F7 을 삼켜 팬텀 저장을 유발).
    closed = await verify.confirm_popup_count(page, less_than=before, timing=verify.ASYNC)
    if not closed:
        return await _fail_close(page, f"{label} 적용 후 피커 팝업이 닫히지 않았습니다 — {closed.reason}")
    return out


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
    row, err = await _search_and_pick(
        page, keyword, PARTNER_FIELDS, lambda opts: pick_partner_row(opts, expect_name, code)
    )
    if err or not row:
        return await _fail_close(page, err or f"거래처 '{expect_name}' 후보를 읽지 못했습니다")
    # 검증 셀 = 연 셀(거래처=PARTNER_NM, 상대계정=BFC_PARTNER_NM). 기대값 = 선택 행의 PARTNER_NM.
    fin = await _select_and_apply(page, row["i"], label, open_field, row.get("PARTNER_NM") or expect_name)
    if not fin.get("ok"):
        return fin
    out = {"ok": True, "code": row.get("PARTNER_CD"), "name": row.get("PARTNER_NM")}
    if fin.get("warn"):
        out["warn"] = fin["warn"]
    return out


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

    ⚠ 닫기는 **닫힘까지 확인**한다(잔존 팝업이 다음 피커에 오독되는 것이 이 함수의 유일한 부작용
      위험이라, 고정 400ms 로 '닫았다'를 단정하지 않는다). 미닫힘은 경고 로그만 남긴다 — 이 함수는
      조회 전용이라 반환 계약(code|None)을 바꾸지 않는다.
    """
    if not (await _open_detail_cell_picker(page, PARTNER_CELL, "상대계정거래처(코드조회)")).get("ok"):
        return None
    row, err = await _search_and_pick(
        page, name, PARTNER_FIELDS, lambda opts: pick_partner_row(opts, name, None)
    )
    warn = await _close_picker_verified(page)
    if warn:
        logger.warning("상대계정 코드조회 팝업 미닫힘: %s", warn)
    if err:
        logger.warning("상대계정 코드조회 무매칭('%s'): %s", name, err)
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
    # 검색 정착 확인 + 무매칭 재검색 — 정착 전 1회 읽기는 33행으로 좁혀지기 전의 전량(132행+)을
    # 읽어 '다중매칭' 오류나 필터 전 행 오선택을 만든다(거래처와 동일 레이스, 안전판이 없었다).
    row, err = await _search_and_pick(
        page, BUDGET_SEARCH_KW, BUDGET_FIELDS, lambda opts: pick_budget_row(opts, department, bgacct_nm)
    )
    if err or not row:
        return await _fail_close(page, err or "예산단위 후보를 읽지 못했습니다")
    fin = await _select_and_apply(page, row["i"], "예산단위", "BG_NM", row.get("BG_NM"))
    if not fin.get("ok"):
        return fin
    out = {
        "ok": True,
        "code": row.get("BG_CD"),
        "name": f"{row.get('BG_NM')} · {row.get('BIZPLAN_NM')} · {row.get('BGACCT_NM')}",
    }
    if fin.get("warn"):
        out["warn"] = fin["warn"]
    return out


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
    # 예산단위와 같은 이유로 검색 정착 확인 + 무매칭 재검색(정착 전 읽기 → WBS 오선택 방지).
    row, err = await _search_and_pick(
        page, name or wbs_no, PROJECT_FIELDS, lambda opts: pick_project_row(opts, name, wbs_no)
    )
    if err or not row:
        return await _fail_close(page, err or "프로젝트 후보를 읽지 못했습니다")
    fin = await _select_and_apply(page, row["i"], "프로젝트", "PJT_NM", row.get("PJT_NM"))
    if not fin.get("ok"):
        return fin
    out = {"ok": True, "code": row.get("PJT_NO"), "name": row.get("PJT_NM")}
    if fin.get("warn"):
        out["warn"] = fin["warn"]
    return out


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
    async def _open_editor() -> Any:
        return await page.evaluate(js_lib.OPEN_DETAIL_CELL_EDITOR_JS, "SPPRC_AMT2")

    op = await _open_editor()
    if not op.get("ok"):
        return {"ok": False, "reason": f"금액 에디터 열기 실패: {op.get('reason')}"}
    # 숫자 에디터 input 준비 확인 — 예전엔 고정 500ms 뒤 **1회만** 읽고 없으면 즉시 실패했다.
    # 그 500ms 는 워크플로우 delay_scale(0.4)에서 200ms 로 줄어 느린 세션에서 조기 실패했다.
    # 커널 재시도(실시간 대기) + 재시도마다 에디터 재오픈으로 대체한다.
    ed = await verify.confirm(
        lambda: page.evaluate(js.AMOUNT_EDITOR_INPUT_JS),
        lambda r: isinstance(r, dict) and bool(r.get("id")),
        timing=verify.ASYNC,
        what="금액 숫자 에디터(gridDetail_number)",
        expected="input id",
        reapply=_open_editor,
    )
    if not ed:
        return {"ok": False, "reason": "금액 숫자 에디터(gridDetail_number)를 찾지 못함"}
    rect = ed.actual
    loc = page.locator(f'input[id="{rect["id"]}"]')
    await loc.click()
    await page.wait_for_timeout(150)
    await loc.select_text()  # 기존 '0' 선택(Meta+A 는 에디터 닫힘 유발이라 금지).
    await page.wait_for_timeout(100)
    await loc.press_sequentially(str(amount), delay=90)
    await page.wait_for_timeout(200)
    await loc.press("Tab")  # 커밋 → blur/change 로 예산현황 트리거 발화(Enter 보다 확실).
    # 예산현황 팝업 확인(뜨는 모달을 확인/예 로 닫는다).
    # ⚠ 예전엔 버튼을 누른 뒤 **닫혔는지 보지 않았고**, 버튼을 못 찾으면 break 로 빠져나와
    #   잔존 모달을 안고 다음 단계(적요·상대계정·최종 F7)로 진행했다. 잔존 k-window 는 이후
    #   피커 오독(최상단 규칙)과 F7 삼킴(팬텀 저장)의 직접 원인이다 → 클릭마다 개수 감소를
    #   확인하고, 끝까지 남아 있으면 하드 실패로 끊는다.
    modals_seen: list[str] = []
    for _ in range(8):
        await page.wait_for_timeout(600)
        modals = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
        if not modals:
            break
        modals_seen.append(str((modals[0] or {}).get("title") or ""))
        before = await _popup_count(page)
        clicked = False
        for label in ("확인", "예"):
            btn = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, label)
            if btn:
                await mouse_click(page, btn["x"], btn["y"])
                clicked = True
                break
        if not clicked:
            # 정확일치('확인'/'예') 실패 — 라벨 변형·에러성 모달('닫기' 등) 느슨 매칭 폴백
            # (2026-07-30: 3에이전트 동시 실패, 표준 조합 재현 전부 정상 → 변형 모달 가설).
            # '닫기'로 닫힌 에러 모달(예산 초과 등)은 금액이 미반영일 수 있으나, 아래 반영
            # 검증(READ_AMT)이 불일치를 하드 실패로 잡으므로 성공 위장은 없다.
            btn = await page.evaluate(js.MODAL_BTN_LOOSE_JS)
            if btn:
                await mouse_click(page, btn["x"], btn["y"])
                clicked = True
        if not clicked:
            break
        await verify.confirm_popup_count(page, less_than=before, timing=verify.ASYNC)
    left = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
    if left:
        # 진단 강화(2026-07-30): 남은 모달의 **버튼 목록**까지 사유에 담는다 — 다음 실패에서
        # 어떤 변형 모달이었는지 로그만으로 확정할 수 있게(재현 실패로 원인 미상였던 교훈).
        desc = " / ".join(
            f"{str((m or {}).get('title') or '')}〔버튼: {', '.join((m or {}).get('buttons') or []) or '없음'}〕"
            for m in left[:3]
        )
        return {
            "ok": False,
            "reason": f"금액 입력 후 확인 모달이 닫히지 않았습니다([{desc}]) — 잔존 팝업은 이후 피커 오독·F7 삼킴을 유발합니다.",
            "modals": modals_seen,
        }
    # 반영 금액 확인 — 재시도 안전판(자동계산이 늦게 붙는 세션 대비). 불일치는 하드 실패.
    chk = await verify.confirm(
        lambda: page.evaluate(js.READ_AMT_JS),
        lambda v: isinstance(v, dict)
        and str(v.get("SPPRC_AMT2") or "").replace(",", "").strip() == str(amount),
        timing=verify.INSTANT,
        what="거래금액(SPPRC_AMT2)",
        expected=amount,
    )
    after = chk.actual if isinstance(chk.actual, dict) else {}
    if not chk:
        return {
            "ok": False,
            "reason": f"금액 반영 불일치(기대 {amount:,}·실제 {after.get('SPPRC_AMT2')})",
            "modals": modals_seen,
        }
    return {"ok": True, "after": after, "modals": modals_seen}


async def register_counter_partner(page: Any, self_name: str) -> dict:
    """상대계정거래처 = 작성자 본인 — **부가선택 위젯 🔍 → 검색 → 팝업 행 더블클릭**(2026-07-09 확정).

    실제 상대계정거래처 UI 는 detail 셀이 아니라 하단 부가선택 테이블(내역코드/내역명)이다. BFC_PARTNER_CD
    setValue(set_counter_partner)는 숨김필드만 세팅해 화면 미표시라 폐기. 위젯 🔍 로 거래처 팝업을 열어
    본인명 검색 → 행 더블클릭하면 등록된다. **부작용: detail 빈 행 1개 추가(ERP 동작)** → 호출측이
    `delete_blank_row` 로 제거. 반환 {ok}|{ok:True, warn}|{ok:False, reason}.

    ⚠ 등록 성공 판정을 예전엔 **빈 행 +1**(대리 신호)로만 했다 — 행수는 F3 오발·ERP 자동행 같은
      다른 원인으로도 늘어 오통과가 가능했고, 정작 값 자체는 읽지 않았다. 이제 부가선택 행의
      입력값(`js.COUNTER_VALS_JS`)에 본인 이름이 실제로 붙었는지를 성공 근거로 쓰고, 빈 행 +1 은
      **부작용 신호**로만 기록한다(delete_blank_row 가 소거).
    ⚠ 팝업 오픈도 rowcount>50 매직 임계가 아니라 **팝업 개수 증가**로 본다 — 임계 판정은 직전
      피커가 안 닫혔을 때 스테일 팝업을 '열렸다'로 통과시켰고, 임계 미달이어도 그대로 검색으로
      진행해 판정 결과를 아예 쓰지 않았다.
    """
    # 상대계정거래처 항목 존재 확인 — 문서유형에 따라 없을 수 있다(해외 정산서 gubun 54 는 관리항목에
    # 상대계정거래처가 없음, 2026-07-09 실측). 5회 스크롤 시도해도 라벨이 없으면 이 유형은 상대계정을
    # 쓰지 않는 것으로 보고 우아하게 스킵(오등록·오류 대신). 국내 자차는 첫 시도에 바로 발견됨.
    label_present = False
    for _ in range(5):
        if await page.evaluate(js.COUNTER_SCROLL_JS):
            label_present = True
            break
        await page.wait_for_timeout(500)
    if not label_present:
        return {"ok": True, "skipped": True, "reason": "상대계정거래처 항목 없음(문서유형) — 스킵"}

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
        popups_before = await _popup_count(page)
        await mouse_click(page, box["x"], box["y"])
        opened = await verify.confirm_popup_count(
            page,
            more_than=popups_before,
            timing=verify.ASYNC,
            reapply=lambda b=box: mouse_click(page, b["x"], b["y"]),
        )
        if not opened:
            err = f"거래처 팝업이 열리지 않음 — {opened.reason}"
            continue
        row, err = await _search_and_pick(
            page, self_name, PARTNER_FIELDS, lambda opts: pick_partner_row(opts, self_name, None), rounds=1
        )
        if not err:
            break
        await _close_picker_verified(page)
    if not row:
        return {"ok": False, "reason": f"상대계정 본인('{self_name}') 검색 실패: {err}"}
    rr = await page.evaluate(js.PICKER_ROW_RECT_JS, row["i"])
    if not rr:
        return await _fail_close(page, "상대계정 팝업 행 좌표 없음")
    await page.mouse.dblclick(rr["x"], rr["y"])
    # 등록 반영 확인 — 부가선택 행 입력값에 본인 이름이 실제로 붙었는지(대리 신호 아님).
    want = _norm(self_name)
    reg = await verify.confirm(
        lambda: page.evaluate(js.COUNTER_VALS_JS),
        lambda v: isinstance(v, dict)
        and bool(v.get("found"))
        and any(want and want in _norm(x) for x in (v.get("vals") or [])),
        timing=verify.ASYNC,
        what=f"상대계정거래처('{self_name}') 등록",
        expected=self_name,
        # found=False = 문서유형에 항목 자체가 없음 → 확인 불가(기존 '우아한 스킵' 경로와 정합).
        unknown_when=lambda v: not (isinstance(v, dict) and v.get("found")),
    )
    # 빈 행 +1 은 성공 근거가 아니라 **부작용 신호**로만 기록(delete_blank_row 가 소거).
    cur = await page.evaluate(js.DETAIL_ROWS_JS)
    blank_added = int((cur or {}).get("n") or 0) > before_n
    if reg:
        return {"ok": True, "verified": True, "blank_added": blank_added}
    if reg.unknown:
        return {"ok": True, "verified": False, "blank_added": blank_added, "warn": reg.reason}
    return await _fail_close(page, f"상대계정 등록 미반영 — {reg.reason}")


def _data_rows(snapshot: Any) -> int:
    """detail 스냅샷에서 **데이터 행**(거래처가 붙은 행) 수 — 삭제가 데이터를 지웠는지 판별용."""
    if not isinstance(snapshot, dict):
        return -1
    return sum(1 for r in (snapshot.get("rows") or []) if r.get("PARTNER"))


async def delete_blank_row(page: Any) -> dict:
    """상대계정 등록 시 추가된 빈(마지막) detail 행 삭제 — 빈 행 선택 → 툴바 삭제 버튼 + 확인 모달.

    반환 {ok}|{ok:True, warn}|{ok:False, reason}. 빈 행 없으면 no-op.

    ⚠⚠ **파괴적 액션의 사전 게이트**(표준 실패정책의 의도된 예외). 빈 행 선택은 좌표 추정 클릭
      (`DETAIL_ROW_CLICK_JS`: r.y+34+idx*32+16)에 의존하는데 스크롤·행높이가 달라지면 빗나가
      현재 행이 **데이터 행**이 되고, 그 상태의 F6 은 되돌릴 수 없다. 예전 코드는 클릭 후 고정
      1200ms(배율 0.4 면 480ms)만 기다리고 바로 삭제를 눌렀다. 이제 `GRID_CURRENT_ROW_JS` 로
      현재 행이 의도한 빈 행인지 확인되는 경우에만 삭제하고, **확인 불가여도 진행하지 않는다** —
      빈 행이 남는 것은 되돌릴 수 있고 데이터 행 삭제는 되돌릴 수 없다.
    ⚠ 사후 확인도 행수 감소만 보지 않는다 — **데이터 행 수 보존**까지 함께 본다(어느 행이 지워
      졌는지). 데이터 행이 줄었으면 하드 실패로 드러낸다.
    """
    rows = await page.evaluate(js.DETAIL_ROWS_JS)
    before_n = int(rows.get("n") or 0)
    before_data = _data_rows(rows)
    blanks = [r["i"] for r in (rows.get("rows") or []) if not r.get("PARTNER")]
    if not blanks:
        return {"ok": True, "note": "빈 행 없음"}
    bi = max(blanks)  # 마지막(추가된) 빈 행.
    pt = await page.evaluate(js.DETAIL_ROW_CLICK_JS, bi)
    await mouse_click(page, pt["x"], pt["y"])
    cur = await verify.confirm(
        lambda: page.evaluate(js_lib.GRID_CURRENT_ROW_JS, 1),
        lambda v: isinstance(v, dict) and bool(v.get("ok")) and v.get("current") == bi,
        timing=verify.INSTANT,
        what=f"삭제 대상 빈 행({bi}) 선택",
        expected=bi,
        reapply=lambda: mouse_click(page, pt["x"], pt["y"]),
    )
    if not cur:
        # 불일치·확인 불가 모두 **삭제 스킵**(보수적). 빈 행이 남으면 이후 저장 검증에서
        # 드러나지만(되돌릴 수 있음), 잘못 고른 데이터 행 삭제는 되돌릴 수 없다.
        return {"ok": True, "verified": False, "warn": f"삭제 건너뜀 — {cur.reason}"}
    box = await page.evaluate(js.BTN_BOX_JS, selectors.BTN_DELETE)
    if not box:
        return {"ok": False, "reason": "삭제 버튼을 찾지 못함"}
    await mouse_click(page, box["x"], box["y"])
    # 확인 모달 처리 — 모달이 사라질 때까지(최대 20회). 삭제 반영은 아래에서 별도 확인한다.
    for _ in range(20):
        await page.wait_for_timeout(500)
        modals = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
        if not modals:
            break
        for label in ("예", "확인", "삭제"):
            btn = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, label)
            if btn:
                await mouse_click(page, btn["x"], btn["y"])
                break
    done = await verify.confirm(
        lambda: page.evaluate(js.DETAIL_ROWS_JS),
        lambda v: isinstance(v, dict)
        and int(v.get("n") or -1) == before_n - 1
        and _data_rows(v) == before_data,
        timing=verify.HEAVY,
        what="빈 행 삭제 반영",
        expected=f"행수 {before_n - 1}·데이터행 {before_data}",
        unknown_when=lambda v: not (isinstance(v, dict) and isinstance(v.get("n"), int)),
    )
    if done:
        return {"ok": True, "verified": True}
    if done.unknown:
        return {"ok": True, "verified": False, "warn": f"삭제 반영 {done.reason}"}
    return {"ok": False, "reason": f"빈 행 삭제 실패 — {done.reason}"}


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
    """적요(NOTE_DC) 셀 setValue 직접 세팅 + **셀 재독 대조**. 반환 {ok, after}|{ok:True, warn}.

    ⚠ setValue 의 {ok:true} 는 "호출이 예외 없이 끝났다"까지다 — 형제 세터(계산서일·마스터 합계·
      금액)는 전부 after 를 기대값과 대조하는데 **적요만 대조가 없어**, 적요가 빈 채로 저장되거나
      이전 행 값이 남아도 그대로 통과했다(이 스텝은 경조금·학자금·해외출장이 그대로 import 한다).
      셀을 재독해 대조한다. 셀을 못 읽으면(그리드 미접근) 확인 불가로 분류해 warn 후 진행.
    """
    r = await page.evaluate(js.SET_DETAIL_CELL_JS, {"field": "NOTE_DC", "value": text})
    if not r.get("ok"):
        return {"ok": False, "reason": r.get("reason") or "적요 세팅 실패"}
    want = _norm(text)
    chk = await verify.confirm(
        _read_detail_cell(page, "NOTE_DC"),
        lambda v: not _cell_unreadable(v) and _norm((v.get("raw") or {}).get("NOTE_DC")) == want,
        timing=verify.INSTANT,
        what="적요(NOTE_DC)",
        expected=text,
        unknown_when=_cell_unreadable,
    )
    if chk:
        return {"ok": True, "after": (chk.actual.get("raw") or {}).get("NOTE_DC")}
    if chk.unknown:
        return {"ok": True, "after": r.get("after"), "warn": chk.reason}
    return {"ok": False, "reason": f"적요 반영 불일치 — {chk.reason}"}


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
    popups_before = await _popup_count(page)
    await page.mouse.click(box["x"], box["y"])
    # 오픈은 **개수 증가**로 확인한다(스테일 팝업 오독 차단). 읽기 전용 카탈로그 동기화라
    # 미확인이어도 덤프는 시도하되, 성공을 단정하지 않도록 경고를 남긴다.
    if not await verify.confirm_popup_count(page, more_than=popups_before, timing=verify.ASYNC):
        logger.warning("거래처 팝업 개수 증가 미확인 — 스테일 팝업을 읽을 수 있음(덤프 결과 주의)")
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
    warn = await _close_picker_verified(page)
    if warn:
        logger.warning("거래처 덤프 팝업 미닫힘: %s", warn)
    return partner_options_to_rows(read.get("options") or [])
