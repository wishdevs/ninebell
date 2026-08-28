"""구매발주 Phase B — 쓰기 경로 스텝(2026-08-28 개방, 사용자 지시: ETRI-001 헤디드 실행으로 셀프결재까지).

근거 실측: e2e/purchase_order_screen1_dryrun_probe.py(2026-08-26 드라이런 5회) + PROCESS.md D4/D5/D7.
규율: 세팅→독립확인(값을 다시 읽어 판정) · 조회는 기대 상태 도달까지 재시도 후 **명시적 실패** ·
      ⛔ 보관 버튼 미클릭 · 상신은 별도 게이트(nodes/self_approve) 뒤.
⚠ 체크 API 는 **ds(데이터 행) 공간**의 checkRow/getCheckedRows 만 쓴다 — checkItem 계열은 아이템
  인덱스 공간이라 ds 행을 넘기면 다음 발주단위까지 딸려온다(실측 10→99행).
"""

from __future__ import annotations

from typing import Any

from nbkit.omnisol import codepicker, js_lib, latency, selectors, verify

from . import js
from .steps import (
    BOM_LOAD_CAP_MS,
    CHECKBOX_MOVE,
    CHECKBOX_PURCHASE,
    POLL_MS,
    click_lookup,
    read_bom_signature,
    set_checkbox,
)

# 저장위치 2종 — 항상 이 값 고정(사용자 확정 2026-08-25).
# (필드 id, [적용] 버튼 id, 검색어, 반영 컬럼, 기대 코드)
STORAGE_LOCATIONS: tuple[tuple[str, str, str, str, str], ...] = (
    ("n_public_sl_cd", "b_public_sl_cd", "공용자재", "OUT_MV_SL_CD", "1100"),
    ("n_mv_sl_cd", "b_mv_sl_cd", "프로젝트", "IN_MV_SL_CD", "1000"),
)
DUE_DATE_FIELD = "i_bfdedt_dt"
DUE_DATE_APPLY_BTN = "btn_bfdedt_dt"
PURCHASE_REASON_FIELD = "i_rmk_dc"
REQUERY_DIALOG_TEXT = "저장하지 않은 데이터가 있습니다"
SAVE_DIALOG_TEXT = "저장하시겠습니까"
SAVE_SUCCESS_TEXT = "자료가 정상적으로 저장되었습니다"
MOVE_REQ_PREFIX = "IRQ"
PUR_REQ_PREFIX = "PRQ"
DIALOG_SCAN_CAP_MS = 4_000
SAVE_CAP_MS = 40_000
QUERY_TRIES = 3
LEVEL_MODULE = 3


async def scan_dialog(page: Any, *, cap_ms: int = DIALOG_SCAN_CAP_MS) -> dict | None:
    """확인 다이얼로그(k-window 등, 버튼 ≤3)가 뜨면 {title,text,buttons}, 상한 내 미발생 None."""
    waited = 0
    cap = latency.budget_ms(cap_ms)
    while True:
        dialogs = await page.evaluate(js.DIALOGS_JS)
        cand = next(
            (
                d
                for d in (dialogs or [])
                if d.get("buttons")
                and len(d["buttons"]) <= 3
                and "프로젝트" not in (d.get("title") or "")
            ),
            None,
        )
        if cand:
            return cand
        if waited >= cap:
            return None
        await verify.DEFAULT_SLEEP(POLL_MS / 1000)
        waited += POLL_MS


async def click_dialog_button(page: Any, text: str) -> bool:
    """보이는 다이얼로그의 버튼(예/아니요/확인)을 좌표 클릭. 미발견 False."""
    box = await page.evaluate(js.DIALOG_BTN_BOX_JS, text)
    if not box:
        return False
    await page.mouse.click(box["x"], box["y"])
    await verify.DEFAULT_SLEEP(0.5)
    # ✅ 실측(2026-08-28 probe2): dews msgbox(`#dews-msgbox-confirm`, 결재 확인 '전자결재를
    # 진행하시겠습니까?')는 좌표 클릭이 먹지 않고 **로케이터 클릭**만 닫는다. 아직 같은 버튼이
    # 보이면 로케이터로 한 번 더 누른다(초기화/저장 확인창은 좌표 클릭으로 이미 닫혀 no-op).
    if await page.evaluate(js.DIALOG_BTN_BOX_JS, text):
        try:
            await page.get_by_role("button", name=text, exact=True).first.click(timeout=2_000)
        except Exception:  # noqa: BLE001 — role 매칭 실패 시 텍스트 로케이터.
            try:
                await page.get_by_text(text, exact=True).first.click(timeout=2_000)
            except Exception:  # noqa: BLE001
                return False
        await verify.DEFAULT_SLEEP(0.5)
    return True


async def _wait_signature(page: Any, prev: dict | None, accept, *, cap_ms: int) -> dict | None:
    """시그니처가 accept(sig) 를 만족하고 연속 2폴 동일할 때까지 대기. 실패 시 마지막 값."""
    waited = 0
    cap = latency.budget_ms(cap_ms)
    stable: dict | None = None
    last: dict | None = None
    while True:
        sig = await read_bom_signature(page)
        last = sig
        if sig and accept(sig) and (prev is None or sig != prev or accept(prev)):
            if stable == sig:
                return sig
            stable = sig
        else:
            stable = None
        if waited >= cap:
            return last
        await verify.DEFAULT_SLEEP(POLL_MS / 1000)
        waited += POLL_MS


def view_accepts(sig: dict, *, move_only: bool) -> bool:
    """뷰 판정 — 이동요청만: mvY>0 ∧ leafN==0(구매요청 리프 없음; 구조행은 이 뷰에서도 MV_FG='N' —
    ETRI-001 실측 163행 = Y 132 + 구조 N 31) / 구매요청만: count>0 ∧ mvY==0."""
    c = sig.get("count") or 0
    if c <= 0:
        return False
    if move_only:
        return (sig.get("mvY") or 0) > 0 and (sig.get("leafN") or 0) == 0
    return sig.get("mvY") == 0


async def query_view(page: Any, *, move_only: bool, tries: int = QUERY_TRIES) -> dict:
    """체크박스를 맞추고 조회(F2) → 미저장 변경 다이얼로그 [예] → 기대 뷰 반영까지 재시도.

    ⚠ 헤드리스 0.4 배율에선 [예] 뒤 첫 조회가 미반영되고 2회차에 반영된 실측이 있어(드라이런
      3·4·5차) 횟수를 고정하지 않고 기대 상태 도달까지 재시도한다. 끝내 실패하면 명시적 실패 —
      조용히 넘기면 이후 단계 전부가 잘못된 데이터셋 위에서 돈다.
    반환 {"ok", "signature", "attempts", "reason"?}.
    """
    r1 = await set_checkbox(page, CHECKBOX_PURCHASE, not move_only)
    r2 = await set_checkbox(page, CHECKBOX_MOVE, move_only)
    if not r1.get("ok") or not r2.get("ok"):
        return {"ok": False, "reason": (r1.get("reason") or r2.get("reason"))}

    def accept(sig: dict) -> bool:
        return view_accepts(sig, move_only=move_only)

    log: list[dict] = []
    for attempt in range(1, tries + 1):
        prev = await read_bom_signature(page)
        await click_lookup(page)
        dlg = await scan_dialog(page, cap_ms=2_500)
        if dlg and REQUERY_DIALOG_TEXT in (dlg.get("text") or ""):
            await click_dialog_button(page, "예")
        sig = await _wait_signature(page, prev, accept, cap_ms=BOM_LOAD_CAP_MS)
        log.append({"attempt": attempt, "dialog": bool(dlg), "signature": sig})
        if sig and accept(sig):
            return {"ok": True, "signature": sig, "attempts": log}
        await verify.DEFAULT_SLEEP(1.0)
    label = "이동요청만" if move_only else "구매요청만"
    # 진단 — 체크박스 실제 상태 + 잔존 다이얼로그(조회 클릭을 가로채는 안내창 등)를 사유에 싣는다.
    try:
        boxes = {
            lbl: (await page.evaluate(js.CHECKBOX_RECT_JS, lbl) or {}).get("checked")
            for lbl in (CHECKBOX_PURCHASE, CHECKBOX_MOVE)
        }
        dialogs = [(d.get("text") or "")[:80] for d in (await page.evaluate(js.DIALOGS_JS) or [])]
    except Exception:  # noqa: BLE001 — 진단 실패는 사유만 줄인다.
        boxes, dialogs = {}, []
    return {
        "ok": False,
        "attempts": log,
        "reason": (
            f"{label} 조회가 {tries}회 시도에도 반영되지 않았습니다 — {log[-1]['signature']} "
            f"(체크박스 {boxes}, 다이얼로그 {dialogs})"
        ),
    }


async def check_all(page: Any, on: bool) -> dict:
    return await page.evaluate(js.TREEGRID_CHECK_ALL_JS, on)


async def check_rows_exact(page: Any, set_rows: list[int], expected: list[int]) -> dict:
    """SET ds 행들을 checkRow 로 체크(자손 자동 전파) → getCheckedRows 가 expected 와 **정확 일치**해야 ok.

    불일치(초과=다음 발주단위가 딸려옴 / 누락)는 저장 전에 하드 실패 — 화면상 그럴듯해 보여
    사후 추적이 어려운 오염이라 여기서 막는다(드라이런 실측 함정).
    """
    await check_all(page, False)
    res = await page.evaluate(js.TREEGRID_CHECK_ROWS_JS, set_rows)
    if not res.get("ok"):
        return {"ok": False, "reason": f"checkRow 실패 — {res.get('reason') or res.get('err')}"}
    got = sorted(int(x) for x in res.get("checked") or [])
    want = sorted(expected)
    if got != want:
        extra = [i for i in got if i not in want][:10]
        missing = [i for i in want if i not in got][:10]
        return {
            "ok": False,
            "checked": got,
            "reason": (
                f"체크 집합 불일치 — 기대 {len(want)}행/실제 {len(got)}행 "
                f"(초과 {extra}, 누락 {missing})"
            ),
        }
    return {"ok": True, "checked": got}


def descendant_rows(rows: list[dict], set_row: int) -> list[int]:
    """트리 순서 rows(read_bom_rows 반환)에서 ds 행 set_row 의 자손 행(레벨이 더 깊은 연속 행)."""
    by_i = {r["i"]: r for r in rows}
    base = by_i.get(set_row)
    if base is None:
        return []
    base_level = base.get("level") or 0
    out: list[int] = []
    i = set_row + 1
    while i in by_i and (by_i[i].get("level") or 0) > base_level:
        out.append(i)
        i += 1
    return out


def find_set_rows(rows: list[dict], item_codes: list[str]) -> dict:
    """모듈 itemCode 목록 → SET(레벨 3) ds 행. 미발견/중복은 명시 실패 {ok:False, reason}."""
    found: dict[str, list[int]] = {}
    for r in rows:
        if r.get("level") == LEVEL_MODULE:
            code = str(r.get("ITEM_CD") or "").strip()
            if code in item_codes:
                found.setdefault(code, []).append(int(r["i"]))
    missing = [c for c in item_codes if c not in found]
    dup = [c for c, v in found.items() if len(v) > 1]
    if missing:
        return {"ok": False, "reason": f"계획서의 모듈을 그리드에서 찾지 못했습니다 — {missing[:5]}"}
    if dup:
        return {"ok": False, "reason": f"같은 품목코드의 SET 행이 여러 개라 특정할 수 없습니다 — {dup[:5]}"}
    return {"ok": True, "rows": [found[c][0] for c in item_codes]}


async def click_by_id(page: Any, elem_id: str) -> dict:
    box = await page.evaluate(js.BOX_BY_ID_JS, elem_id)
    if not box:
        return {"ok": False, "reason": f"'{elem_id}' 버튼을 찾지 못했습니다."}
    if box.get("disabled"):
        return {"ok": False, "reason": f"'{elem_id}' 버튼이 비활성입니다."}
    await page.mouse.click(box["x"], box["y"])
    await page.wait_for_timeout(900)
    return {"ok": True}


async def pick_code_document(page: Any, field_id: str, keyword: str) -> dict:
    """최상위 폼/필터행 코드피커 — 돋보기(document 스코프) → 검색 → 첫 행 → 적용 → 표시값 확인.

    codepicker._open_picker 는 card_collect 모달 전용이라 여기선 안 먹는다(실측) — 오픈만 직접.
    """
    box = await page.evaluate(js.PICKER_OPEN_BOX_JS, field_id)
    if not box:
        return {"ok": False, "reason": f"'{field_id}' 돋보기를 찾지 못했습니다."}
    # 돋보기 클릭 → **새 k-window 출현을 확인**(개수 증가)할 때까지 대기, 안 열리면 1회 재클릭.
    # (2026-08-28 실측: 직전 [적용] 직후 클릭이 유실돼 피커 없이 검색 → 행 -1 실패)
    before = await page.evaluate(js_lib.POPUP_COUNT_JS)
    opened = False
    for _ in range(2):
        await page.mouse.click(box["x"], box["y"])
        waited = 0
        while waited < 5_000:
            await verify.DEFAULT_SLEEP(0.3)
            waited += 300
            now = await page.evaluate(js_lib.POPUP_COUNT_JS)
            if isinstance(now, int) and isinstance(before, int) and now > before:
                opened = True
                break
        if opened:
            break
    if not opened:
        return {"ok": False, "reason": f"'{field_id}' 코드피커 창이 열리지 않았습니다."}
    await page.wait_for_timeout(600)
    try:
        # 검색 → 검색어를 **포함하는 행**을 찾아 선택(첫 행 맹선택 금지 — 2026-08-28 실측: 검색이
        # 목록을 좁히기 전 첫 행 'ACM Research…' 선택). 못 찾으면 검색 1회 재시도.
        found = {"index": -1}
        for attempt in range(2):
            await codepicker._picker_search(page, keyword)
            await codepicker._wait_picker_rows_stable(page)
            await verify.DEFAULT_SLEEP(0.4)
            found = await page.evaluate(js.PICKER_FIND_ROW_JS, keyword) or {"index": -1}
            if found.get("index", -1) >= 0:
                break
            await verify.DEFAULT_SLEEP(1.0)
        if found.get("index", -1) < 0:
            await page.keyboard.press("Escape")
            return {
                "ok": False,
                "reason": f"'{keyword}' 를 포함하는 행이 없습니다({field_id}, 행 {found.get('rows')}, 첫행 {found.get('sample')}).",
            }
        await page.evaluate(js_lib.PICKER_SELECT_JS, int(found["index"]))
        apply_box = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
        if apply_box:
            await page.mouse.click(apply_box["x"], apply_box["y"])
        await codepicker._wait_picker_closed(page)
    except Exception as exc:  # noqa: BLE001 — 사유를 실패로 승격(조용한 실패 금지).
        await page.keyboard.press("Escape")
        return {"ok": False, "reason": f"코드피커 조작 실패({field_id}): {str(exc)[:120]}"}
    display = await page.evaluate(js.INPUT_VALUE_JS, field_id)
    if not display or keyword not in str(display):
        return {"ok": False, "reason": f"'{field_id}' 표시값이 '{keyword}' 가 아닙니다 — {display!r}"}
    return {"ok": True, "display": display}


async def set_text_verified(page: Any, field_id: str, value: str) -> dict:
    await page.evaluate(js.SET_INPUT_JS, [field_id, value])
    await verify.DEFAULT_SLEEP(0.3)
    got = await page.evaluate(js.INPUT_VALUE_JS, field_id)
    if got != value:
        return {"ok": False, "reason": f"'{field_id}' 입력 확인 실패 — 기대 {value!r} / 실제 {got!r}"}
    return {"ok": True}


async def read_grid_field(page: Any, rows: list[int], field: str) -> dict[int, Any]:
    vals = await page.evaluate(js.TREEGRID_FIELD_JS, [rows, field])
    return {int(k): v for k, v in (vals or {}).items()}


def _is_new_number(before: set[str], now: list[str]) -> list[str]:
    return sorted(set(now) - before)


async def settle_after_save(page: Any, *, cap_ms: int = 4_000) -> None:
    """저장 성공 뒤 정착 — 잔존 안내 다이얼로그(확인 1버튼)를 닫고 로딩 오버레이가 걷힐 때까지 대기.

    저장 직후 뜨는 안내창/로딩이 다음 조회 클릭을 가로채면 그리드가 갱신되지 않는다(2026-08-28
    ETRI-001 실측: 이동요청 저장 직후 '구매요청만' 재조회 3회 미반영).
    """
    from app.agents.voucher_receivable import steps as voucher_steps

    waited = 0
    while waited < cap_ms:
        closed = False
        for d in await page.evaluate(js.DIALOGS_JS) or []:
            btns = d.get("buttons") or []
            if btns and len(btns) <= 2 and "프로젝트" not in (d.get("title") or ""):
                await click_dialog_button(page, btns[0])
                closed = True
        if not closed:
            break
        await verify.DEFAULT_SLEEP(POLL_MS / 1000)
        waited += POLL_MS
    await voucher_steps.wait_loading_overlay_gone(page)
    await verify.DEFAULT_SLEEP(1.0)


async def click_save_and_wait(page: Any, number_prefix: str) -> dict:
    """저장(F7) 실클릭 → '저장하시겠습니까?' [예] → 성공 판정.

    성공 = 새 번호(number_prefix+숫자)가 화면에 나타남(시연 ✅ 상단 자동 발급) **또는** 성공
    스낵바 문구. 경고/오류 스낵바가 먼저 보이면 그 문구로 실패. 상한 내 아무 신호도 없으면 실패
    (미저장이 성공으로 둔갑하는 조용한 실패 금지). 반환 {"ok", "number"?, "reason"?}.
    """
    before = set(await page.evaluate(js.FIND_NUMBERS_JS, number_prefix) or [])
    box = await page.evaluate(js.BOX_BY_SELECTOR_JS, selectors.BTN_SAVE)
    if not box:
        return {"ok": False, "reason": "저장 버튼을 찾지 못했습니다."}
    if box.get("disabled"):
        return {"ok": False, "reason": "저장 버튼이 비활성입니다."}
    await page.mouse.click(box["x"], box["y"])
    dlg = await scan_dialog(page, cap_ms=DIALOG_SCAN_CAP_MS)
    seen: list[str] = []  # 진단 — 관측한 스낵바/다이얼로그 문구(실패 사유에 싣는다)
    seen.append(f"save-btn:{box}")
    seen.append(f"first-dialog:{(dlg or {}).get('text', '')[:80]!r}{(dlg or {}).get('buttons')}")
    if dlg and SAVE_DIALOG_TEXT in (dlg.get("text") or ""):
        await click_dialog_button(page, "예")
    elif dlg:
        return {
            "ok": False,
            "reason": f"저장 시 예상 밖 다이얼로그 — {dlg.get('text')!r} {dlg.get('buttons')}",
        }

    waited = 0
    cap = latency.budget_ms(SAVE_CAP_MS)
    seen_success = False
    while waited < cap:
        for s in await page.evaluate(js.SNACKBARS_JS) or []:
            txt = s.get("text") or ""
            cls = s.get("cls") or ""
            if txt and f"snack:{txt}" not in seen:
                seen.append(f"snack:{txt}")
            if SAVE_SUCCESS_TEXT in txt:
                seen_success = True
            elif ("warning" in cls or "error" in cls) and txt:
                return {"ok": False, "reason": f"저장 실패 — {txt}"}
        new = _is_new_number(before, await page.evaluate(js.FIND_NUMBERS_JS, number_prefix) or [])
        if new or seen_success:
            await settle_after_save(page)
            return {"ok": True, "number": new[-1] if new else None}
        for d in await page.evaluate(js.DIALOGS_JS) or []:
            if d.get("buttons") and len(d["buttons"]) <= 2 and "프로젝트" not in (d.get("title") or ""):
                seen.append(f"dialog:{(d.get('text') or '')[:120]}{d.get('buttons')}")
                await click_dialog_button(page, d["buttons"][0])
                if any(w in (d.get("text") or "") for w in ("실패", "오류", "없습니다", "확인해")):
                    return {"ok": False, "reason": f"저장 후 안내 — {d.get('text')!r}"}
        await verify.DEFAULT_SLEEP(POLL_MS / 1000)
        waited += POLL_MS
    return {
        "ok": False,
        "reason": (
            "저장 후 상한 내에 성공 신호(번호 발급/성공 문구)를 확인하지 못했습니다 — "
            f"번호 before={sorted(before)} now={sorted(await page.evaluate(js.FIND_NUMBERS_JS, number_prefix) or [])} "
            f"관측 {seen[:8]}"
        ),
    }


async def reset_header_for_new_request(page: Any, *, keyword: str, pjt_no: str) -> dict:
    """저장 직후 상단 '구매요청번호' 에 직전 PRQ 가 남아 화면이 **기존 문서 편집** 상태가 된다 —
    이 상태에서 저장 버튼은 '변경 없음' 으로 무시된다(다이얼로그조차 없음, 2026-08-28 ETRI-001
    실측 run5~7: 세션 첫 저장만 성공·두 번째는 무신호 실패). 신규(F3, `button.main-button.add`)로
    헤더를 초기화한 뒤 프로젝트가 비면 다시 적용하고 고정값을 재확인한다.
    반환 {"ok", "via": "none"|"add", "reason"?}.
    """
    from .steps import PROJECT_FIELD_LABEL, apply_project, ensure_fixed_header

    from app.agents.voucher_receivable import steps as voucher_steps

    # PRQ(구매요청) 뿐 아니라 **IRQ(이동요청번호)** 잔존도 같은 '기존 문서' 상태다 — 이동요청 저장 직후
    # 구매요청만 재조회가 163행(이동요청 뷰) 그대로 멈춘 실측(2026-08-28 ETRI-002, IRQ2026081446).
    stale = [
        p for p in (PUR_REQ_PREFIX, MOVE_REQ_PREFIX) if await page.evaluate(js.INPUT_NUMBERS_JS, p)
    ]
    if not stale:
        return {"ok": True, "via": "none"}
    left: list = []
    seen: list[str] = []
    # 결과검증형 재시도(상한 3): 클릭 → 다이얼로그 처리 → 번호가 비워질 때까지 폴링(최대 5s).
    # 저장 직후 로딩/후처리 중 클릭이 먹히지 않는 사례(2026-08-28 run8 #6) 대비.
    for attempt in range(3):
        await voucher_steps.wait_loading_overlay_gone(page)
        box = await page.evaluate(js.BOX_BY_SELECTOR_JS, selectors.BTN_ADD)
        if not box:
            return {"ok": False, "reason": "신규(추가) 버튼을 찾지 못해 구매요청번호를 초기화할 수 없습니다."}
        await page.mouse.click(box["x"], box["y"])
        dlg = await scan_dialog(page, cap_ms=1_500)
        if dlg and dlg.get("buttons"):
            seen.append(f"dialog:{(dlg.get('text') or '')[:80]}{dlg['buttons']}")
            await click_dialog_button(page, "예" if "예" in dlg["buttons"] else dlg["buttons"][0])
        waited = 0
        while waited < 6_000:
            # '초기화하시겠습니까?' [예][아니요] 가 클릭 2초 뒤에도 뜬다(2026-08-28 run8 스크린샷) —
            # 폴링 중에도 계속 감지해 [예] 를 누른다.
            for d in await page.evaluate(js.DIALOGS_JS) or []:
                btns = d.get("buttons") or []
                if btns and len(btns) <= 3 and "프로젝트" not in (d.get("title") or ""):
                    seen.append(f"dialog:{(d.get('text') or '')[:80]}{btns}")
                    await click_dialog_button(page, "예" if "예" in btns else btns[0])
            left = [n for p in (PUR_REQ_PREFIX, MOVE_REQ_PREFIX) for n in (await page.evaluate(js.INPUT_NUMBERS_JS, p) or [])]
            if not left:
                break
            await verify.DEFAULT_SLEEP(POLL_MS / 1000)
            waited += POLL_MS
        if not left:
            break
        await verify.DEFAULT_SLEEP(1.0)
    if left:
        return {
            "ok": False,
            "reason": f"신규 클릭(3회) 후에도 구매요청번호가 남아 있습니다 — {left} 관측 {seen}",
        }
    project = await page.evaluate(js_lib.FIELD_DISPLAY_JS, PROJECT_FIELD_LABEL)
    if not project:
        r = await apply_project(page, keyword, pjt_no)
        if not r.get("ok"):
            return {"ok": False, "reason": f"신규 후 프로젝트 재적용 실패 — {r.get('reason')}"}
    h = await ensure_fixed_header(page)
    if not h.get("ok"):
        return {"ok": False, "reason": f"신규 후 고정값 확인 실패 — {h.get('reason')}"}
    return {"ok": True, "via": "add", "project_reapplied": not project}


# ── 화면 ② 구매요청처리(PUOPRQ00300) ─────────────────────────────────────────────
REQ_PLANT_FIELD = "s_plant_cd"
REQ_NO_FIELD = "s_no_purreq"
# ❓ 결재 아이콘 2종 중 어느 쪽이 셀프결재인지 미확정(title/aria 공란) — 순서대로 시도.
REQ_APPROVAL_SELECTORS = ("button.main-button.approval", "button.main-button.etn-approval")
REQ_QUERY_CAP_MS = 30_000


async def ensure_req_plant(page: Any, name: str = "나인벨") -> dict:
    """공장(필수 코드피커)이 비었으면 name 으로 채운다. 이미 맞으면 무변경."""
    cur = await page.evaluate(js.INPUT_VALUE_JS, REQ_PLANT_FIELD)
    if cur and name in str(cur):
        return {"ok": True, "unchanged": True}
    return await pick_code_document(page, REQ_PLANT_FIELD, name)


async def query_request(page: Any, purreq_no: str) -> dict:
    """요청번호로 조회(F2) → 마스터 그리드에서 해당 행 찾기. 반환 {"ok", "row"?, "reason"?}."""
    r = await set_text_verified(page, REQ_NO_FIELD, purreq_no)
    if not r.get("ok"):
        return r
    await click_lookup(page)
    waited = 0
    cap = latency.budget_ms(REQ_QUERY_CAP_MS)
    last: dict = {}
    while waited < cap:
        last = await page.evaluate(js.REQ_MASTER_ROWS_JS) or {}
        for row in last.get("rows") or []:
            if str(row.get("PURREQ_NO") or "").strip() == purreq_no:
                return {"ok": True, "row": row}
        await verify.DEFAULT_SLEEP(POLL_MS / 1000)
        waited += POLL_MS
    return {
        "ok": False,
        "reason": f"구매요청처리 조회에서 {purreq_no} 행을 찾지 못했습니다(조회 {last.get('count')}행).",
    }


def submit_guard(row: dict) -> str | None:
    """상신 가드레일 — 결재상태=='저장' ∧ 결재상신코드=='' 인 행만. 위반 사유 또는 None."""
    st = str(row.get("ATHZ_ST_NM") or "").strip()
    gw = str(row.get("GWDOCU_NO") or "").strip()
    if st != "저장" or gw:
        return f"상신 대상 아님 — 결재상태 {st!r}, 결재상신코드 {gw!r}"
    return None


async def select_request_row(page: Any, idx: int) -> bool:
    return bool(await page.evaluate(js.REQ_SELECT_ROW_JS, idx))


async def open_request_approval(page: Any, *, attempts: int = 2) -> dict:
    """결재 아이콘 클릭 → 새 Page(EAP 결재창) 캡처. 후보 2종 순서로 시도, 열린 셀렉터를 반환."""
    from app.agents.voucher_receivable import steps as voucher_steps  # 공용 EAP 프리미티브

    context = page.context
    for sel in REQ_APPROVAL_SELECTORS:
        for attempt in range(attempts):
            await voucher_steps.wait_loading_overlay_gone(page)
            rect = await page.evaluate(js.BOX_BY_SELECTOR_JS, sel)
            if not rect:
                break
            try:
                async with context.expect_page(timeout=15_000) as info:
                    await page.mouse.click(rect["x"], rect["y"])
                    # ✅ 실측(2026-08-28 run10): 아이콘 클릭 → 인페이지 확인 '전자결재를 진행하시겠습니까?'
                    # [예][아니요] → [예] 뒤에 EAP 새 창이 뜬다. 새 창 대기 중에 확인을 처리한다.
                    waited = 0
                    while waited < 12_000:
                        dlg = next(
                            (d for d in (await page.evaluate(js.DIALOGS_JS) or []) if "예" in (d.get("buttons") or [])),
                            None,
                        )
                        if dlg:
                            await click_dialog_button(page, "예")  # 좌표→로케이터 폴백 내장
                            # 확인 뒤엔 새 창이 뜰 때까지 조용히 기다린다(재클릭 금지 — 이중 상신 방지).
                            break
                        await verify.DEFAULT_SLEEP(POLL_MS / 1000)
                        waited += POLL_MS
            except Exception:  # noqa: BLE001 — 새 창 미출현 → 재시도/다음 후보.
                dlg = await page.evaluate(js.DIALOGS_JS)
                if dlg:
                    return {
                        "ok": False,
                        "reason": f"결재 클릭 후 다이얼로그 — {dlg[0].get('text')!r}",
                        "selector": sel,
                    }
                if attempt + 1 < attempts:
                    await page.wait_for_timeout(500)
                continue
            return {"ok": True, "child": await info.value, "selector": sel}
    return {"ok": False, "reason": "결재 아이콘 클릭으로 결재창(새 창)이 열리지 않았습니다."}
