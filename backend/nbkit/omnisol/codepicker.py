"""dews 코드피커 공용 엔진 — 열기/검색/행 안정 대기/이름 매칭 선택/적용/닫힘.

card_collect 에서 승격(2026-07-05) — 모든 옴니솔 에이전트 공용. 로직은 card_collect
실전 검증본 그대로(동작 불변)이며, in-page JS 는 :mod:`nbkit.omnisol.js_lib` 단일 소스를
쓴다. 하위호환: :mod:`app.agents.card_collect.steps` 가 같은 이름들을 재수출(shim)한다.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from nbkit.omnisol import js_lib

logger = logging.getLogger("nbkit.omnisol.codepicker")

# 코드피커 버튼 출현 폴링 — 컨테이너 느린 렌더(--disable-dev-shm-usage)나 '증빙 확인 중' 모달로
# 버튼(#{field}-wrapper)이 지연 출현하는 환경 대비(2026-07-10 규명, 실측 ~0.5s). 넉넉히 6s.
_OPEN_BTN_POLLS = 24
_OPEN_BTN_INTERVAL_MS = 250

# underscore 이름들도 shim(card_collect.steps)이 재수출하므로 안정 인터페이스로 유지한다.
__all__ = [
    "_norm",
    "_open_picker",
    "_picker_search",
    "_wait_picker_closed",
    "_wait_picker_rows_stable",
    "fill_codepicker",
]


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

    ⚠ cap/min 은 **실시간(monotonic)** 으로 잰다 — CARD_DELAY_SCALE 로 wait_for_timeout 이
    줄어도 서버 재조회를 기다리는 실제 상한은 그대로 유지해야 한다(명목 카운터면 스케일 0.2 에서
    실상한이 ~600ms 로 쪼그라들어 빈 그리드를 '후보 0건'으로 오판. 2026-07-04 실측). 폴 간격만
    스케일되고 상한은 불변 → 피커는 스케일 무관하게 안전, 나머지 대기만 극단 축소 가능.
    """
    prev: int | None = None
    prev_elapsed = 0.0
    last = -1
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1000 < cap_ms:
        await page.wait_for_timeout(interval_ms)
        n = await page.evaluate(js_lib.PICKER_ROWCOUNT_JS)
        elapsed = (time.monotonic() - t0) * 1000
        if isinstance(n, int) and n >= 0:
            last = n
            # 두 관측이 모두 min_ms 이후(직전 관측 시각 기준) + 양수 + 동일할 때만 조기 안정.
            if n > 0 and n == prev and prev_elapsed >= min_ms:
                return n
            prev, prev_elapsed = n, elapsed
        else:
            prev, prev_elapsed = None, 0.0
    return last


async def _wait_picker_closed(page: Any, *, cap_ms: int = 1_500, interval_ms: int = 150) -> None:
    """'적용' 클릭 후 피커 팝업이 닫힐 때까지 폴링(고정 1000ms 대체)."""
    waited = 0
    while waited < cap_ms:
        await page.wait_for_timeout(interval_ms)
        waited += interval_ms
        n = await page.evaluate(js_lib.PICKER_ROWCOUNT_JS)
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
    box = await page.evaluate(js_lib.picker_btn_js(field_id))
    if not box:
        return {"ok": False, "reason": f"{field_id} 버튼 없음"}
    await page.mouse.click(box["x"], box["y"])
    await _wait_picker_rows_stable(page, cap_ms=3_000)  # 팝업 오픈+그리드 준비(고정 1.5s 대체)

    async def _fail(reason: str, **extra: Any) -> dict:
        # 실패 시 열린 코드피커 팝업을 닫는다 — 안 닫으면 다음 코드피커가 이 팝업을 읽어 오작동한다.
        await page.evaluate(js_lib.PICKER_CLOSE_JS)
        await page.wait_for_timeout(400)
        return {"ok": False, "reason": reason, **extra}

    if keyword:
        s = await page.evaluate(js_lib.PICKER_SEARCH_JS, keyword)
        if s.get("ok"):
            await page.keyboard.press("Enter")
            # 서버 재조회 안정 대기(고정 1.2s 대체) — min_ms 로 옛 rowcount 오인 방지.
            await _wait_picker_rows_stable(page, cap_ms=2_000, min_ms=600)
    read = await page.evaluate(js_lib.PICKER_READ_JS, [code_field, name_field, 25])
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
            await page.evaluate(js_lib.PICKER_SEARCH_JS, "")
            await page.keyboard.press("Enter")
            await _wait_picker_rows_stable(page, cap_ms=2_000, min_ms=600)
            dflt = (await page.evaluate(js_lib.PICKER_READ_JS, [code_field, name_field, 25])).get("options") or []
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

    sel = await page.evaluate(js_lib.PICKER_SELECT_JS, chosen["i"])
    if not sel.get("ok"):
        return await _fail(f"{field_id} 행 선택 실패: {sel}")
    await page.wait_for_timeout(400)
    apply_box = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
    if apply_box:
        await page.mouse.click(apply_box["x"], apply_box["y"])
        await _wait_picker_closed(page)  # 팝업 닫힘 폴링(고정 1s 대체)
    return {"ok": True, "code": chosen["code"], "name": chosen["name"]}


# ── 코드 카탈로그 덤프용 저수준 헬퍼(열기/재검색) ─────────────────────────────────
async def _open_picker(page: Any, field_id: str) -> bool:
    """코드피커 버튼 좌표 클릭 → 팝업 오픈·그리드 준비 폴링(고정 1.8s 대체). 성공 True.

    버튼(#{field}-wrapper .dews-codepicker-button)이 렌더될 때까지 폴링한다 — 컨테이너의 느린
    렌더(--disable-dev-shm-usage)나 '증빙 확인 중' 모달로 버튼이 지연 출현하면 예전엔 box=None
    즉시 실패로 0행이 됐다(프로젝트 카탈로그 동기화 prod 0건 원인, 2026-07-10 규명).
    """
    box = None
    for i in range(_OPEN_BTN_POLLS):
        box = await page.evaluate(js_lib.picker_btn_js(field_id))
        if box:
            if i:
                logger.info("코드피커 '%s' 버튼 %d회 폴링 후 출현(~%dms)", field_id, i, i * _OPEN_BTN_INTERVAL_MS)
            break
        await page.wait_for_timeout(_OPEN_BTN_INTERVAL_MS)
    if not box:
        logger.warning("코드피커 '%s' 버튼 미출현(폴링 %d회 소진) — 팝업 미오픈", field_id, _OPEN_BTN_POLLS)
        return False
    await page.mouse.click(box["x"], box["y"])
    await _wait_picker_rows_stable(page, cap_ms=3_000)
    return True


async def _picker_search(page: Any, keyword: str) -> None:
    """열린 코드피커 팝업에 keyword 를 넣고 Enter 로 서버 재조회(안정 폴링, 고정 1.2s 대체)."""
    await page.evaluate(js_lib.PICKER_SEARCH_JS, keyword)
    await page.keyboard.press("Enter")
    await _wait_picker_rows_stable(page, cap_ms=2_000, min_ms=600)
