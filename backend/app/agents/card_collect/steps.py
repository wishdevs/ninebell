"""법인카드 승인내역 정리 — 스텝 함수(진입 후 카드팝업 조작). js.py 프리미티브 사용.

각 함수는 Playwright page 를 받아 조작하고 결과를 반환한다(LangGraph 노드가 이 함수들을 호출).
⚠ 저장(F7)은 save_document(page, confirm=True) 로만, 명시적 confirm 일 때만 실행한다.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
import re
import time
from datetime import date
from typing import Any

from nbkit.omnisol import js_lib, verify

from . import js

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# 확인(verify) 규율 — 값을 세팅/조작한 스텝은 **반영을 확인**하고서야 ok 를 돌려준다.
#   불일치(리더로 읽었는데 값이 다름) = 하드 실패(대상·데이터를 정의하는 값일 때).
#   보조 조건(범위만 넓히는 값)·확인 불가(리더가 필드/위젯을 못 읽음) = 경고 후 진행.
# 재시도·대기는 nbkit.omnisol.verify 커널이 담당(즉시 1회 + 점증 대기 3회, **실시간**).
#
# ⚠ 이 에이전트의 구조적 위험(2026-07-27 감사): card-collect 는 delay_scale=0.15 로 등록돼
#   러너(_ScaledPage)가 **모든 page.wait_for_timeout 을 0.15배**로 줄인다. 그런데 기존 폴링
#   상한은 대부분 `waited += 300` 같은 **명목 카운터**라 상한이 통째로 1/6.7 로 붕괴했다
#   (조회 20s→3s, '0건 3초 유예'→450ms, 저장 관찰창 3s→450ms). 확인 커널의 대기는
#   asyncio.sleep 실시간이라 이 붕괴가 없다 — 남은 명목 대기도 _real_sleep 으로 옮긴다.
# ══════════════════════════════════════════════════════════════════════════════
# SCOPED_FIELD_VALUE_JS 스코프 — 카드팝업 뒤에 결의서입력 본화면이 살아 있어 동명 라벨/동일
# id 의 wrapper 가 배경에도 있을 수 있다. win 으로 팝업을 먼저 고정하지 않으면 배경을 읽는다.
CARD_WIN_TITLE = "법인카드"
CARD_NO_FIELD = ".dews-multicodepicker-text"  # 카드팝업 카드번호 멀티코드피커 표시 input
BUDGET_SCOPE = "#bg_cd-wrapper"  # picker_btn_js 와 동일한 주소지정(#{field}-wrapper)
PROJECT_SCOPE = "#pjt_cd-wrapper"
PERIOD_FIELD = "#period"  # 승인일 periodpicker(리더 폴백: period_startinput/_endinput)


async def _real_sleep(seconds: float) -> None:
    """실시간 대기 — ``page.wait_for_timeout`` 은 delay_scale 로 줄어들어 상한이 붕괴한다.

    확인 커널과 **같은** 대기 구현(:data:`verify.DEFAULT_SLEEP`)을 쓴다(단위 테스트는
    conftest 가 이 값을 no-op 으로 갈아끼워 실패 경로가 실시간을 태우지 않게 한다).
    """
    await verify.DEFAULT_SLEEP(seconds)


def _verdict(res: verify.Confirmed, **ok_extra: Any) -> dict:
    """확인 결과를 스텝 반환 dict 로 — 불일치는 실패, 확인 불가는 warn 을 얹은 성공."""
    if res:
        return {"ok": True, **ok_extra}
    if res.unknown:
        return {"ok": True, "warn": res.reason, **ok_extra}
    return {"ok": False, "reason": res.reason}


def _unreadable(v: Any) -> bool:
    """SCOPED_FIELD_VALUE_JS 가 null = 스코프/필드 미발견(값이 틀린 게 아니라 확인 불가)."""
    return v is None


def _not_int(v: Any) -> bool:
    """POPUP_COUNT_JS 가 int 를 못 돌려줌 = 팝업 개수 확인 불가."""
    return not isinstance(v, int)


def _text(v: Any) -> str:
    return " ".join(str("" if v is None else v).split())


async def _popup_count(page: Any) -> int:
    """보이는 k-window 개수(확인 불가면 -1) — 팝업 개폐 확인의 before 스냅샷."""
    try:
        n = await page.evaluate(js_lib.POPUP_COUNT_JS)
    except Exception:  # noqa: BLE001 — 확인 코드가 런을 죽이지 않는다.
        return -1
    return n if isinstance(n, int) else -1

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
def owner_name_variants(
    userid: str | None, display_name: str | None = None, job_title: str | None = None
) -> list[str]:
    """본인 카드 매칭 키 변형 목록 — 로그인ID + 프로필 순수 이름 + "이름 직책".

    패널 이름이 "석대현 프로"처럼 직책을 달고 있어(사용자 확정 2026-07-29) 카드명 괄호
    "(석대현)"과 소유자 컬럼 "석대현 프로" 표기를 모두 잡으려면 변형 전부가 필요하다.
    중복 제거·빈 값 제외, 순서 보존.
    """
    variants = [userid, display_name]
    if display_name and job_title:
        variants.append(f"{display_name} {job_title}")
    out: list[str] = []
    for v in variants:
        s = (v or "").strip()
        if s and s not in out:
            out.append(s)
    return out


async def select_all_cards(page: Any, owner_name: str | list[str] | None = None) -> dict:
    """카드번호 돋보기 → '카드' 서브팝업 선택 → 적용. 반환 {ok, n, checked, by}.

    선택 규칙(사용자 확정 2026-07-04): owner_name(로그인ID 문자열 또는 이름 변형 목록 —
    owner_name_variants 참조)이 주어지면 그 이름과 일치하는 카드만 선택하고, 일치 0건이면
    기존 로직인 **전체선택**으로 폴백한다(공용카드·빈 소유자 대비). by='name'|'all'.
    매칭은 CARD_OWNR_NM/KOR_NM/PARTNER_NM 정확일치 + 카드명 괄호 '(이름)' 포함 —
    실측(2026-07-29) 이 ERP 는 소유자/관리사원 컬럼을 채우지 않아 카드명
    FINPRODUCT_NM("…법인카드(석대현)-2826")의 괄호가 유일한 소유자 표기다
    (CARD_SUB_SELECT_BY_NAME_JS 참조).

    ⚠ 증빙유형 01 적용 직후 법인카드 팝업이 **로딩 중**('데이터 처리 중')일 수 있다 — 돋보기
    버튼 출현을 폴링(실측 2026-07-04: 폴링 세분화 후 '돋보기 버튼 없음' 레이스).

    확인 4지점(2026-07-27):
      (1) 돋보기 출현 — 명목 카운터(상한 10s→실제 1.5s 붕괴) 대신 확인 커널 HEAVY.
      (2) 서브팝업 **개수 증가** — 안 뜬 걸 모르면 다음 단계의 'non-법인카드 최근 k-window'
          셀렉터가 잔여 팝업(예산현황 등)을 서브팝업으로 오독한다.
      (3) 체크 **수** 대조 — JS 가 이미 읽어온 checked 를 n/matched 와 맞춰본다. 안 보면
          'checkAll 은 호출됐지만 그리드가 비어 0장 체크'가 성공으로 통과한다.
      (4) '적용' 후 서브팝업 **닫힘** — 예전엔 상한 내 안 닫혀도 {ok:True} 를 돌려줬다.
    카드번호 필드 표시값(폼 반영)은 리더 스코프가 미실측이라 **경고 수준**으로만 본다.
    """
    warns: list[str] = []
    # (1) 돋보기 버튼 출현 — 실시간 재시도(delay_scale 무관).
    found = await verify.confirm(
        lambda: page.evaluate(js.CARD_SEARCH_BTN_JS),
        lambda v: bool(v),
        timing=verify.HEAVY,
        what="카드번호 돋보기 버튼",
        expected="(좌표)",
    )
    if not found:
        return {"ok": False, "reason": "돋보기 버튼 없음(법인카드 팝업 아님?)"}
    box = found.actual
    before = await _popup_count(page)
    await page.mouse.click(box["x"], box["y"])
    # (2) 서브팝업이 실제로 떴는지 개수 증가로 확정.
    if before < 0:
        warns.append("팝업 개수 확인 불가 — 카드 서브팝업 오픈 미확인")
    else:
        opened = await verify.confirm_popup_count(
            page, more_than=before, timing=verify.ASYNC, unknown_when=_not_int
        )
        if opened.mismatch:
            return {"ok": False, "reason": f"카드 서브팝업이 열리지 않았습니다 — {opened.reason}"}
        if opened.unknown:
            warns.append(opened.reason)
    # 서브팝업 그리드 준비 폴링(check-first: 준비됐으면 즉시 진행). 대기는 실시간 스케줄.
    # ⚠ 여기서 n>0 을 요구한다 — 예전엔 ok:true 면 n==0(빈 그리드)도 통과해 0장 선택이 됐다.
    by = "all"
    sel: dict = {}
    for wait_ms in verify.ASYNC:
        if wait_ms:
            await _real_sleep(wait_ms / 1000)
        owners = [owner_name] if isinstance(owner_name, str) else list(owner_name or [])
        owners = [o.strip() for o in owners if o and o.strip()]
        if owners:
            # 본인 이름 매칭 우선 — matched>0 이면 그것으로 확정, matched==0 이면 전체선택 폴백.
            r = await page.evaluate(js.CARD_SUB_SELECT_BY_NAME_JS, owners)
            if r.get("ok") and r.get("n", 0) > 0:
                if r.get("matched", 0) > 0:
                    sel, by = r, "name"
                    break
                r = await page.evaluate(js.CARD_SUB_SELECT_ALL_JS)  # 매칭 0 → 전체선택
                if r.get("ok") and r.get("n", 0) > 0:
                    sel = r
                    break
        else:
            r = await page.evaluate(js.CARD_SUB_SELECT_ALL_JS)
            if r.get("ok") and r.get("n", 0) > 0:
                sel = r
                break
    if not sel.get("ok"):
        return {"ok": False, "reason": f"서브팝업 카드선택 실패(카드 0장 포함): {sel}"}
    # (3) JS 가 이미 돌려준 checked 를 판정에 편입 — 추가 왕복 0으로 '0장 체크' 사고를 막는다.
    want = sel.get("matched") if by == "name" else sel.get("n")
    checked = sel.get("checked")
    if not isinstance(checked, int) or checked < 0:
        warns.append("카드 체크 수 확인 불가(getCheckedRows 미지원) — 선택 반영 미확인")
    elif checked != want:
        return {
            "ok": False,
            "reason": f"카드 체크 불일치(기대 {want}장·실제 {checked}장) — 잘못된 범위 적용 차단",
        }
    apply_box = await page.evaluate(js.CARD_SUB_APPLY_BTN_JS)
    if not apply_box:
        return {"ok": False, "reason": "서브팝업 '적용' 버튼 없음", "n": sel.get("n")}
    await page.mouse.click(apply_box["x"], apply_box["y"])
    # (4) 적용 후 서브팝업 닫힘 — 안 닫히면 선택이 폼에 안 붙었을 수 있다(하드 실패).
    #     ⚠ '적용' 재클릭(reapply)은 이중 적용 위험이라 하지 않는다 — 대기 후 재확인만.
    closed = await verify.confirm(
        lambda: page.evaluate(js.CARD_SUB_EXISTS_JS),
        lambda v: not v,
        timing=verify.ASYNC,
        what="카드 서브팝업 닫힘",
        expected="닫힘",
    )
    if not closed:
        return {"ok": False, "reason": f"'적용' 후 카드 서브팝업이 닫히지 않았습니다 — {closed.reason}"}
    # 폼 반영(카드번호 필드 표시값) — 팝업 안 체크 성공이 폼 적용을 보증하지 않는다(§10).
    # ⚠ 카드번호 wrapper id 가 미실측이라 '법인카드 팝업 안 첫 멀티코드피커 표시값'으로만
    #   본다 — 엉뚱한 필드를 읽을 여지가 있어 **경고 수준**(soft)이다.
    disp = await verify.confirm(
        lambda: page.evaluate(
            js_lib.SCOPED_FIELD_VALUE_JS, {"win": CARD_WIN_TITLE, "selector": CARD_NO_FIELD}
        ),
        lambda v: bool(_text(v)),
        timing=verify.ASYNC,
        what="카드번호 표시값",
        expected="(비어있지 않음)",
        unknown_when=_unreadable,
    )
    if not disp:
        warns.append(disp.reason)
    out: dict = {
        "ok": True,
        "n": sel.get("n"),
        "checked": sel.get("checked"),
        "by": by,
        "display": disp.actual,
        "verified": bool(disp),  # False = 폼 반영 **미확인**(완료로 단정하지 않는다)
    }
    if warns:
        out["warn"] = " / ".join(warns)
    return out


# ── 승인일 세팅 + 조회 ───────────────────────────────────────────────────────────
async def set_period(page: Any, start: str, end: str) -> dict:
    """승인일 기간 세팅 + **위젯 왕복 후 값 재확인**. 반환 {ok, start, end, display} | {ok:False, reason}.

    ⚠ PERIOD_SET_JS 의 readback 은 value setter 직후 **같은 tick** 이라, dews periodpicker 의
    change 핸들러가 값을 되돌리거나 재포맷하는 경우를 못 잡는다 — 기간이 틀리면 수집 대상
    자체가 달라지므로(대상 정의 값) 리더로 재확인하고 불일치는 **하드 실패**로 다룬다.
    되돌려지는 성격의 값이라 재시도 때는 **재세팅**(reapply)한다.
    """
    payload = [start, end]
    r = await page.evaluate(js.PERIOD_SET_JS, payload)
    if not (r.get("start") == start and r.get("end") == end):
        return {"ok": False, "reason": f"승인일 기간 세팅 실패(즉시 readback {r})", **r}
    want = {start.replace("-", ""), end.replace("-", "")}

    def reflected(v: Any) -> bool:
        if not (isinstance(v, dict) and v.get("found")):
            return False
        return want <= {re.sub(r"\D", "", str(s)) for s in (v.get("values") or [])}

    chk = await verify.confirm(
        lambda: page.evaluate(js_lib.PERIOD_VALUE_JS, PERIOD_FIELD),
        reflected,
        timing=verify.INSTANT,
        what="승인일 기간",
        expected=f"{start}~{end}",
        reapply=lambda: page.evaluate(js.PERIOD_SET_JS, payload),
        unknown_when=lambda v: not (isinstance(v, dict) and v.get("found")),
    )
    values = chk.actual.get("values") if isinstance(chk.actual, dict) else None
    return _verdict(chk, start=r.get("start"), end=r.get("end"), display=values)


async def run_query(page: Any) -> int:
    """조회 클릭 후 그리드가 **새 결과로 확정**될 때까지 확인 커널(HEAVY)로 대기.

    반환 행 수(0 가능 — 대상 없음도 정상 결과, -1=버튼/그리드 확인 실패).

    확인 2지점(2026-07-27):
      * **클릭 전 rowcount 스냅샷** — 직전 조회 결과(스테일 그리드)를 새 결과로 오인하지
        않는다. 2차(불공) 재조회는 1차 결과가 그대로 남은 상태에서 실행되므로 특히 중요.
      * 대기를 확인 커널로 이관 — 기존 폴링은 `waited += 300` 명목 카운터라 delay_scale 0.15
        에서 상한 20s→3s, '0건 3초 유예'→450ms 로 붕괴했다(서버 응답 도착 전 0건 확정 =
        조회 0건 오판의 1순위 원인). 커널 대기는 asyncio.sleep 실시간이라 스케일 무관.

    판정: 값이 **직전과 달라지면** 즉시 확정, 같으면 스케줄을 전부 소진한 뒤에만 확정한다
    (진짜 0건이 상한을 전부 태우지 않도록 양수/0 을 구분하지 않고 '변화'로 본다).
    """
    box = await page.evaluate(js.QUERY_BTN_JS)
    if not box:
        return -1
    before = await page.evaluate(js.ROWCOUNT_JS)
    # 그리드를 못 읽었으면(-1) 0 으로 본다 — 그래야 클릭 후의 0 을 '변화'로 오인하지 않는다.
    base = before if isinstance(before, int) and before >= 0 else 0
    await page.mouse.click(box["x"], box["y"])
    reads = {"n": 0}

    def settled(v: Any) -> bool:
        if not isinstance(v, int) or v < 0:
            return False
        reads["n"] += 1
        if v != base:
            return True  # 새 결과 도착 — 즉시 확정.
        return reads["n"] >= len(verify.HEAVY)  # 무변화는 전체 대기를 소진한 뒤에만 인정.

    chk = await verify.confirm(
        lambda: page.evaluate(js.ROWCOUNT_JS),
        settled,
        timing=verify.HEAVY,
        what="조회 결과 rowcount",
        expected=f"직전({base}건)과 구분되는 확정값",
    )
    rows = chk.actual
    return rows if isinstance(rows, int) and rows >= 0 else -1


async def read_rows(page: Any, limit: int = 200) -> list[dict]:
    r = await page.evaluate(js.READ_ROWS_JS, limit)
    return r.get("list") or []


# ── 적요(행별 인라인) ─────────────────────────────────────────────────────────────
def _row_note_is(v: Any, row: int, text: str) -> bool:
    """READ_ROWS_JS 결과에서 row 행의 NOTE_DC 가 text 인지."""
    if not (isinstance(v, dict) and isinstance(v.get("list"), list)):
        return False
    want = _text(text)
    for r in v["list"]:
        if r.get("i") == row:
            return _text(r.get("NOTE_DC")) == want
    return False


def _rows_unreadable(v: Any) -> bool:
    return not (isinstance(v, dict) and isinstance(v.get("list"), list))


async def set_note(page: Any, row: int, text: str) -> dict:
    """행 적요(NOTE_DC) 세팅 + **반영 확인**. 반환 {ok, after} | {ok, warn} | {ok:False, reason}.

    ⚠ NOTE_SET_JS 는 setValue 뒤 되읽은 값을 ``after`` 로 **이미 돌려주는데** 예전 호출부는
    ok 만 봤다 — 캔버스 그리드가 값을 무시·절삭·재포맷해도 성공으로 통과했다(적요는 전표에
    남는 데이터라 하드 실패 대상). after 가 다르면 재세팅 후 그리드에서 재확인한다.
    """
    r = await page.evaluate(js.NOTE_SET_JS, [row, text])
    if not (isinstance(r, dict) and r.get("ok")):
        return r if isinstance(r, dict) else {"ok": False, "reason": f"적요 세팅 실패: {r}"}
    after = r.get("after")
    if _text(after) == _text(text):
        return {"ok": True, "after": after}
    chk = await verify.confirm(
        lambda: page.evaluate(js.READ_ROWS_JS, row + 1),
        lambda v: _row_note_is(v, row, text),
        timing=verify.INSTANT,
        what=f"{row + 1}행 적요",
        expected=text,
        reapply=lambda: page.evaluate(js.NOTE_SET_JS, [row, text]),
        unknown_when=_rows_unreadable,
    )
    return _verdict(chk, after=after)


async def verify_notes(page: Any, rows: list[int], text: str) -> dict:
    """일괄적용 **직전** 그룹 행들의 적요가 살아 있는지 재확인(cascade). 반환 스텝 dict.

    OMNISOL_NOTES §10 의 연쇄 규율 — 'A 가 B 를 바꾸면 A 확인 뒤 B 재확인'. 적요를 넣은 뒤
    예산단위·프로젝트 피커의 '적용'이 그리드/폼을 리로드하면 앞서 넣은 적요가 되돌려질 수
    있는데, 일괄적용 직전 재확인이 없으면 **적요 없는 전표**가 조용히 반영된다.
    되돌려지는 성격이라 재시도 때 그룹 행 전체를 **재세팅**한다.
    """
    if not rows:
        return {"ok": True}

    async def _reapply() -> None:
        for row in rows:
            await page.evaluate(js.NOTE_SET_JS, [row, text])

    chk = await verify.confirm(
        lambda: page.evaluate(js.READ_ROWS_JS, max(rows) + 1),
        lambda v: all(_row_note_is(v, row, text) for row in rows),
        timing=verify.INSTANT,
        what=f"{len(rows)}행 적요 생존",
        expected=text,
        reapply=_reapply,
        unknown_when=_rows_unreadable,
    )
    return _verdict(chk)


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


# ── 코드피커 개폐 확인 래퍼(공용 엔진은 그대로 두고 card_collect 쪽에서 감싼다) ──────
# ⚠ 코드피커/모달 JS 는 전부 '최근 열린 non-법인카드 k-window' 를 대상으로 한다(js_lib 코드피커
#   헤더). 이 규칙은 잔여 팝업이 하나라도 남으면 즉시 오작동한다 — js.py:BUDGET_CONFIRM_JS 주석에
#   '예산현황 창이 남아 다음 행 코드피커가 그 창을 읽어 검색 0건'이라는 실측 사고가 기록돼 있다.
#   열기=개수 증가 / 닫기=개수 복귀로 스테일 팝업 오독을 차단한다(voucher_receivable 과 동일 처방).
async def _open_picker_verified(page: Any, field_id: str) -> dict:
    """코드피커 열기 + **팝업 개수 증가**로 새 팝업 오픈 확정. 반환 {ok, before, warn?} | {ok:False, reason}."""
    before = await _popup_count(page)
    if not await _open_picker(page, field_id):
        return {"ok": False, "reason": f"{field_id} 버튼 없음(피커 미오픈)"}
    if before < 0:
        return {"ok": True, "before": before, "warn": f"{field_id} 팝업 개수 확인 불가 — 오픈 미확인"}
    opened = await verify.confirm_popup_count(
        page, more_than=before, timing=verify.ASYNC, unknown_when=_not_int
    )
    if opened.mismatch:
        return {
            "ok": False,
            "reason": f"{field_id} 피커 팝업이 열리지 않았습니다(잔여 팝업 오독 위험) — {opened.reason}",
        }
    out: dict = {"ok": True, "before": before}
    if opened.unknown:
        out["warn"] = opened.reason
    return out


async def _close_picker_verified(page: Any, before: int) -> None:
    """피커 닫기 + 팝업 개수 복귀 확인(고정 400ms 대기 대체).

    안 닫힌 피커가 남으면 다음 '최근 non-법인카드 k-window' 조작이 그 창을 읽는다.
    이 헬퍼는 **실패 경로/카탈로그 경로** 전용이라 미확인은 경고 로그만 남긴다(soft).
    """
    await page.evaluate(js.PICKER_CLOSE_JS)
    if before < 0:
        return
    gone = await verify.confirm_popup_count(
        page, less_than=before + 1, timing=verify.ASYNC, unknown_when=_not_int
    )
    if not gone:
        logger.warning("코드피커가 닫히지 않았을 수 있습니다 — %s", gone.reason)


async def _confirm_picker_closed(page: Any, before: int, label: str) -> dict:
    """'적용' 클릭 후 피커 팝업이 **닫혔는지** 개수 복귀로 확정. 반환 {ok, reason?|warn?}.

    ⚠ 기존 _wait_picker_closed 는 page.wait_for_timeout 기반 명목 상한 1.5s 라 delay_scale
    0.15 에서 실상한 ~225ms 로 붕괴했고, 미닫힘이어도 **아무 것도 보고하지 않았다**. 적용이
    폼에 안 붙은 채 다음 피커로 넘어가면 그 창을 읽어 0건이 되므로 하드 실패로 다룬다.
    """
    if before < 0:
        await _wait_picker_closed(page)  # 개수를 못 읽는 세션 — 기존 폴백(확인 불가).
        return {"ok": True, "warn": f"{label} 피커 닫힘 확인 불가(팝업 개수 미확인)"}
    gone = await verify.confirm_popup_count(
        page, less_than=before + 1, timing=verify.ASYNC, unknown_when=_not_int
    )
    if gone.mismatch:
        return {
            "ok": False,
            "reason": f"{label} 피커가 '적용' 후에도 닫히지 않았습니다(선택 미반영 가능) — {gone.reason}",
        }
    return {"ok": True, "warn": gone.reason} if gone.unknown else {"ok": True}


async def _confirm_picker_display(page: Any, scope: str, label: str) -> dict:
    """코드피커 선택이 **카드팝업 폼에 붙었는지** 표시값으로 확인. 반환 {display, verified, warn?}.

    ⚠ 기존 반환의 code/name 은 팝업에서 **읽은 후보 행 값**이지 폼 반영값이 아니다 — 적용이
    안 붙어도 그 이름이 로그·현황표에 '반영됨'으로 찍혔다. 표시 포맷(코드/명칭/조합)은 미실측
    이라 정확일치를 요구하지 않고 **비어있지 않음**만 본다. 리더가 스코프를 못 찾으면(null)
    확인 불가 — 어느 쪽이든 하드 실패가 아니라 경고 후 진행(soft)이다.
    """
    chk = await verify.confirm(
        lambda: page.evaluate(
            js_lib.SCOPED_FIELD_VALUE_JS, {"win": CARD_WIN_TITLE, "scope": scope}
        ),
        lambda v: bool(_text(v)),
        timing=verify.ASYNC,
        what=f"{label} 표시값",
        expected="(비어있지 않음)",
        unknown_when=_unreadable,
    )
    out: dict = {"display": chk.actual, "verified": bool(chk)}
    if not chk:
        out["warn"] = chk.reason
    return out


# ── 코드 카탈로그 덤프(코드피커 전량 읽기) ─────────────────────────────────────────
async def dump_budget_units(page: Any) -> list[dict]:
    """예산단위(bg_cd) 코드피커 빈검색 전량 — **조합 행 그대로**(디둡 없음).

    선택 단위는 BG명 단독이 아니라 (예산단위명 × 사업계획명 × 예산계정명) 조합 행이다
    (사용자 정정 2026-07-02 — BG만 남기면 부서 리스트에 불과함). 반환
    [{code(BG|BIZPLAN|BGACCT 복합), name(BG_NM), bizplanCd, bizplanNm, bgacctCd, bgacctNm}].
    그리드의 DEPT_NM 은 행별 소속이 아니라 로그인 사용자 부서 반복이라 읽지 않는다.
    """
    op = await _open_picker_verified(page, "bg_cd")
    if not op.get("ok"):
        # 잘못된 팝업(잔여 확인창)을 읽으면 오염된 카탈로그가 조용히 저장된다 — 읽지 않는다.
        logger.warning("예산단위 카탈로그 덤프 중단 — %s", op.get("reason"))
        return []
    if op.get("warn"):
        logger.warning("예산단위 카탈로그 덤프 — %s", op["warn"])
    await _picker_search(page, "")
    read = await page.evaluate(
        js.PICKER_READ_MULTI_JS,
        [["BG_CD", "BG_NM", "BIZPLAN_CD", "BIZPLAN_NM", "BGACCT_CD", "BGACCT_NM"], 0],
    )
    await _close_picker_verified(page, op["before"])
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
    op = await _open_picker_verified(page, "pjt_cd")
    if not op.get("ok"):
        # 잘못된 팝업을 읽으면 빈/오염된 검색결과가 그대로 사용자에게 간다 — 읽지 않는다.
        logger.warning("프로젝트 카탈로그 덤프 중단 — %s", op.get("reason"))
        return []
    if op.get("warn"):
        logger.warning("프로젝트 카탈로그 덤프 — %s", op["warn"])
    await _picker_search(page, keyword or "")
    read = await page.evaluate(js.PICKER_READ_MULTI_JS, [_PROJECT_FIELDS, 0])
    await _close_picker_verified(page, op["before"])
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
        op = await _open_picker_verified(page, "pjt_cd")
        if not op.get("ok"):
            logger.warning("프로젝트 스크롤 덤프 중단 — %s", op.get("reason"))
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
            # 서버 페이징(+500)이 **도착했는지**를 확인으로 판정 — 고정 3s(+무증가 시 2s)는
            # delay_scale 0.15 에서 450ms/300ms 로 줄어, 페이지가 오기 전에 '무증가'로 보고
            # 3회 만에 조기 종료(카탈로그 결손)했다. 커널 대기는 실시간이라 이 붕괴가 없다.
            grew = await verify.confirm(
                lambda: page.evaluate(js.PICKER_ROWCOUNT_JS),
                lambda n: isinstance(n, int) and n > prev,
                timing=verify.HEAVY,
                what=f"프로젝트 팝업 추가 로드(r{rnd})",
                expected=f">{prev}",
            )
            cur = grew.actual if isinstance(grew.actual, int) else prev
            logger.info("프로젝트 스크롤 r%d — rows=%s total=%s stable=%d", rnd, cur, server_total, stable)
            if not grew:
                stable += 1
                if stable >= 3:
                    break
            else:
                stable = 0
            prev = max(prev, cur)
        read = await page.evaluate(js.PICKER_READ_MULTI_JS, [_PROJECT_FIELDS, 0])
        await _close_picker_verified(page, op["before"])
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
    op = await _open_picker_verified(page, "pjt_cd")
    if not op.get("ok"):
        logger.warning("프로젝트 스윕 덤프 중단 — %s", op.get("reason"))
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
    await _close_picker_verified(page, op["before"])
    return list(by_code.values()), cap_hit


# ── 예산단위 조합 선택(BG × 사업계획 × 예산계정 특정 행) ─────────────────────────────
async def fill_budget_codepicker(page: Any, combo: dict) -> dict:
    """예산단위 피커에서 (BG_NM, BIZPLAN_NM, BGACCT_NM) 조합이 정확히 일치하는 행을 선택.

    combo = {name(BG_NM), bizplanNm, bgacctNm}. 선택 단위가 조합 행이므로(BG 동일해도
    예산계정이 다르면 다른 선택) 이름 3개를 정규화 비교해 그 행 인덱스를 고른다.
    bizplanNm/bgacctNm 이 비어 있으면 기존 fill_codepicker(BG명 매칭)로 폴백(하위호환).
    반환 {ok, code, name, display, verified} | {ok:False, reason}.

    확인 3지점(2026-07-27): 팝업 **오픈**(개수 증가) / '적용' 버튼 존재·팝업 **닫힘**(개수 복귀)
    / 폼 표시값. 예전엔 적용 버튼이 없거나 팝업이 안 닫혀도 무조건 {ok:True, code, name} 을
    돌려줘 **선택이 폼에 안 붙었는데도** 그 이름이 로그·현황표에 '반영됨'으로 찍혔다.
    """
    bg_nm = (combo.get("name") or "").strip()
    bizplan = (combo.get("bizplanNm") or "").strip()
    bgacct = (combo.get("bgacctNm") or "").strip()
    if not (bizplan or bgacct):
        return await fill_codepicker(page, "bg_cd", bg_nm, "BG_CD", "BG_NM")

    op = await _open_picker_verified(page, "bg_cd")
    if not op.get("ok"):
        return {"ok": False, "reason": op.get("reason")}
    before = op["before"]
    warns: list[str] = [op["warn"]] if op.get("warn") else []

    async def _fail(reason: str) -> dict:
        await _close_picker_verified(page, before)
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
    # 고정 400ms 대기 → '적용' 버튼 출현 확인으로 대체(대기가 곧 확인이 되는 자리).
    ab = await verify.confirm(
        lambda: page.evaluate(js.PICKER_APPLY_BTN_JS),
        lambda v: bool(v),
        timing=verify.ASYNC,
        what="예산단위 피커 '적용' 버튼",
        expected="(좌표)",
    )
    if not ab:
        return await _fail("예산단위 피커 '적용' 버튼 없음 — 선택이 폼에 반영되지 않았습니다")
    await page.mouse.click(ab.actual["x"], ab.actual["y"])
    closed = await _confirm_picker_closed(page, before, "예산단위")
    if not closed.get("ok"):
        return await _fail(closed["reason"])
    if closed.get("warn"):
        warns.append(closed["warn"])
    disp = await _confirm_picker_display(page, BUDGET_SCOPE, "예산단위")
    if disp.get("warn"):
        warns.append(disp["warn"])
    out: dict = {
        "ok": True,
        "code": chosen.get("BG_CD"),
        "name": f"{chosen.get('BG_NM')} · {chosen.get('BIZPLAN_NM')} · {chosen.get('BGACCT_NM')}",
        "display": disp.get("display"),
        "verified": disp.get("verified"),  # False = 폼 반영 **미확인**
    }
    if warns:
        out["warn"] = " / ".join(warns)
    return out


# ── 프로젝트 WBS 행 선택(PJT_NM 검색 → WBS_NO 정확 일치) ─────────────────────────────
async def fill_project_codepicker(page: Any, combo: dict) -> dict:
    """프로젝트 피커에서 PJT_NM 검색 후 WBS_NO 가 정확히 일치하는 WBS 행을 선택.

    combo = {name(PJT_NM), wbsNo}. 카탈로그가 WBS 행 단위라 같은 프로젝트에 여러 WBS 요소가
    있어(선택이 달라짐) WBS_NO 로 정확히 고른다. wbsNo 가 없으면 fill_codepicker(PJT_NM 매칭)로
    폴백(구 PJT_NO 즐겨찾기·WBS 미지정 하위호환). 반환 {ok, code, name, display, verified} |
    {ok:False, reason}. 확인 지점은 fill_budget_codepicker 와 동일(오픈·닫힘·폼 표시값).
    """
    pjt_nm = (combo.get("name") or "").strip()
    wbs_no = (combo.get("wbsNo") or "").strip()
    if not wbs_no:
        return await fill_codepicker(page, "pjt_cd", pjt_nm, "PJT_NO", "PJT_NM")

    op = await _open_picker_verified(page, "pjt_cd")
    if not op.get("ok"):
        return {"ok": False, "reason": op.get("reason")}
    before = op["before"]
    warns: list[str] = [op["warn"]] if op.get("warn") else []

    async def _fail(reason: str) -> dict:
        await _close_picker_verified(page, before)
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
    ab = await verify.confirm(
        lambda: page.evaluate(js.PICKER_APPLY_BTN_JS),
        lambda v: bool(v),
        timing=verify.ASYNC,
        what="프로젝트 피커 '적용' 버튼",
        expected="(좌표)",
    )
    if not ab:
        return await _fail("프로젝트 피커 '적용' 버튼 없음 — 선택이 폼에 반영되지 않았습니다")
    await page.mouse.click(ab.actual["x"], ab.actual["y"])
    closed = await _confirm_picker_closed(page, before, "프로젝트")
    if not closed.get("ok"):
        return await _fail(closed["reason"])
    if closed.get("warn"):
        warns.append(closed["warn"])
    disp = await _confirm_picker_display(page, PROJECT_SCOPE, "프로젝트")
    if disp.get("warn"):
        warns.append(disp["warn"])
    out: dict = {
        "ok": True,
        "code": chosen.get("PJT_NO"),
        "name": chosen.get("PJT_NM"),
        "display": disp.get("display"),
        "verified": disp.get("verified"),  # False = 폼 반영 **미확인**
    }
    if warns:
        out["warn"] = " / ".join(warns)
    return out


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
    # 판정(CARD_WIN_EXISTS_JS = 팝업이 실제로 사라짐)은 원래 옳았다 — 대기만 확인 커널로 옮긴다.
    # ⚠ 기존 폴링은 명목 상한 1.5s 라 delay_scale 0.15 에서 실상한 ~225ms 로 붕괴해, 느린
    #   세션에서 정상 닫힘을 실패로 오판했다(커널 대기는 실시간이라 이 붕괴가 없다).
    closed = await verify.confirm(
        lambda: page.evaluate(js.CARD_WIN_EXISTS_JS),
        lambda v: not v,
        timing=verify.ASYNC,
        what="법인카드 팝업 닫힘",
        expected="닫힘",
    )
    if closed:
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
    before = await _popup_count(page)
    await page.mouse.click(box["x"], box["y"])
    # 일괄적용 → '예산현황' 확인창(확인/취소) 이 뜬다. '확인'으로 draft 반영을 완료한다.
    # ⚠ draft(메모리) 완료일 뿐 F7 저장 아님. 미처리 시 창이 남아 다음 행 코드피커가 그 창을
    #   읽어 검색 0건이 된다(js.py BUDGET_CONFIRM_JS 주석의 실측 사고). 예전엔 못 눌러도
    #   {ok:True, budget_confirm:False} 로 성공 보고했다 — 출현했는데 못 닫으면 하드 실패.
    # ⚠ BUDGET_CONFIRM_JS 는 '찾으면 클릭'까지 하는 액션 리더다(읽기 전용 리더가 없다) —
    #   커널의 read 로 쓰되 재시도가 곧 재클릭 시도라는 뜻이며, 이미 닫힌 창은 n:0 을 낸다.
    async def _click_budget_confirm() -> Any:
        return await page.evaluate(js.BUDGET_CONFIRM_JS)

    def ok_when_clicked(v: Any) -> bool:
        return bool(isinstance(v, dict) and v.get("clicked"))

    warns: list[str] = []

    if before < 0:
        # 팝업 개수를 못 읽는 세션 — 확인창 처리는 best-effort, 미클릭은 경고 후 진행.
        cf = await verify.confirm(
            _click_budget_confirm, ok_when_clicked, timing=verify.ASYNC,
            what="'예산현황' 확인 버튼 클릭", expected="clicked",
        )
        clicked = bool(cf)
        if not clicked:
            warns.append("팝업 개수 확인 불가 + '예산현황' 확인창 미관측 — draft 반영 미확인")
        out: dict = {"ok": True, "budget_confirm": clicked}
        if warns:
            out["warn"] = " / ".join(warns)
        return out

    opened = await verify.confirm_popup_count(
        page, more_than=before, timing=verify.ASYNC, unknown_when=_not_int
    )
    if not opened:
        # 상한 내 미출현 = 확인 불가(세션/데이터에 따라 안 뜰 수 있다) → 경고 후 진행.
        return {"ok": True, "budget_confirm": False, "warn": "'예산현황' 확인창 미출현 — draft 반영 미확인"}
    cf = await verify.confirm(
        _click_budget_confirm, ok_when_clicked, timing=verify.ASYNC,
        what="'예산현황' 확인 버튼 클릭", expected="clicked",
    )
    if not cf:
        return {"ok": False, "reason": f"'예산현황' 확인창을 닫지 못했습니다 — {cf.reason}"}
    gone = await verify.confirm_popup_count(
        page, less_than=before + 1, timing=verify.ASYNC, unknown_when=_not_int
    )
    if gone.mismatch:
        return {"ok": False, "reason": f"'예산현황' 확인 후에도 창이 남아 있습니다 — {gone.reason}"}
    if gone.unknown:
        warns.append(gone.reason)
    out: dict = {"ok": True, "budget_confirm": True}
    if warns:
        out["warn"] = " / ".join(warns)
    return out


# 차단 모달 일괄 해제는 nbkit.omnisol.modals 로 승격(2026-07-05) — 재수출 shim.
from nbkit.omnisol.modals import dismiss_blocking_modals  # noqa: E402, F401 — 하위호환 재수출


async def dismiss_modals_verified(page: Any, rounds: int = 3) -> dict:
    """차단 모달 정리 + **실제로 줄었는지** 팝업 개수로 확인. 반환 {cleared, warn?}.

    ⚠ 닫은 목록만 로그로 남기면 '닫았다고 보고했는데 남아 있는' 상태를 못 잡는다 — 남은 모달이
    뒤이은 close_card_popup/F3/증빙유형 조작을 가로챈다(실측 TypeError, pass2 주석 참조).
    카드팝업 자체도 k-window 라 '0개'로는 판정할 수 없어 **감소**로만 판정하고, 미감소는
    경고 후 진행한다(soft — 이 정리는 방어적 조치이고 후속 스텝이 각자 자기 조건을 확인한다).
    """
    before = await _popup_count(page)
    cleared = await dismiss_blocking_modals(page, rounds=rounds)
    out: dict = {"cleared": list(cleared or [])}
    if not cleared or before < 0:
        return out
    gone = await verify.confirm_popup_count(
        page, less_than=before, timing=verify.ASYNC, unknown_when=_not_int
    )
    if not gone:
        out["warn"] = f"모달 {len(cleared)}건을 닫았다고 보고했으나 팝업이 줄지 않았습니다 — {gone.reason}"
    return out


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
    t0 = time.monotonic()
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
            elapsed = int((time.monotonic() - t0) * 1000)
            return {"ok": True, "checked": chk.get("checked"), "late_modals": dismissed[:4],
                    "clicks": clicks, "iters": it, "elapsed_ms": elapsed}
        await page.wait_for_timeout(150)
        if (time.monotonic() - t0) > 45:
            break
    modals = await page.evaluate(js.MODALS_SNAPSHOT_JS)
    return {"ok": False, "reason": "적용 후 카드팝업이 닫히지 않음", "modals": modals,
            "clicks": clicks, "elapsed_ms": int((time.monotonic() - t0) * 1000)}


# 저장(F7) 거부를 알리는 오류/에러 모달 판별. 실측 모달 title 은 '오류'뿐 아니라 '에러'
# (회계일 마감 등)로도 뜬다 — 둘 다 잡아야 미저장을 성공으로 오판하지 않는다.
_ERR_MODAL_TITLE_HINTS = ("오류", "에러", "경고", "실패")
# 마감된 회계월에 저장 시도 — 재시도로 못 고치는 확정 실패(관리자 마감 해제 필요).
_CLOSED_PERIOD_HINTS = ("회계일이 마감", "마감되어", "마감된")

# F7 후 관찰 창(초) — **실시간**. 명목 카운터였을 때 delay_scale 0.15 에서 3s→450ms 로
# 붕괴해 오류 모달을 보기 전에 성공으로 오판할 수 있었다(주석 참조).
_SAVE_POLL_S = 0.5
_SAVE_MIN_OBSERVE_S = 3.0
_SAVE_CAP_S = 16.0


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
    # ⚠ F7 직후 모달이 뜨기까지 ~1-2s 걸리므로, '모달 없음' 종료 판정은 최소 관찰 창(3s)
    #   이후에만 허용한다. 이 대기는 **실시간**이어야 한다 — 예전엔 page.wait_for_timeout
    #   명목 카운터라 delay_scale 0.15 에서 관찰 창 3s→450ms, 상한 16s→2.4s 로 붕괴해
    #   **오류 모달이 뜨기도 전에 저장 성공으로 오판**할 수 있었다(공지 팝업 관찰창이 같은
    #   이유로 무너진 2026-07-26 선례와 동형). 저장 클릭·게이트는 그대로 두고 대기만 옮긴다.
    t0 = time.monotonic()
    polls = 0
    while True:
        await _real_sleep(_SAVE_POLL_S)
        polls += 1
        # 실시간 경과. (실시간 대기가 주입 무효화된 단위 테스트에서는 명목 카운터가 대신 센다.)
        elapsed = max(time.monotonic() - t0, polls * _SAVE_POLL_S)
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
            if elapsed >= _SAVE_CAP_S:
                break  # 상한 소진(모달이 계속 뜨는 경우) — 아래 판정으로 넘긴다.
            continue
        if toasts:
            break  # 검증 토스트 확인됨 — 저장 실패로 즉시 종료.
        if elapsed >= _SAVE_MIN_OBSERVE_S:
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
