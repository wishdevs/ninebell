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


UNASSIGNED_CLASS = "미지정"  # planner 가 품목거래처 공란 부품에 붙이는 분류(assemble_planner_bom 미러)


def plan_vendor_changes(unit: dict, rows: list[dict]) -> dict[str, list[int]]:
    """팝업 행(PRINCIPALPARTN_NM) 중 의사 거래처(가공품/판금품)·공란(→'미지정') → 계획서 실거래처명별 행 인덱스 묶음.

    공란 행은 계획서 '미지정' 그룹에 **실거래처**(라벨 echo 가 아닌 실제 이름)가 지정된 경우에만
    변경거래처 적용 대상에 포함한다 — 매핑이 없으면 unorderable_positions 가 하단 적용에서 뺀다.
    """
    by_class = {g.get("vendorClass"): g.get("vendor") for g in unit.get("vendorGroups") or []}
    out: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        cls = str(r.get("PRINCIPALPARTN_NM") or "").strip()
        if cls in PSEUDO_VENDORS and by_class.get(cls):
            out.setdefault(str(by_class[cls]), []).append(i)
        elif not cls:
            v = str(by_class.get(UNASSIGNED_CLASS) or "").strip()
            if v and v != UNASSIGNED_CLASS:
                out.setdefault(v, []).append(i)
    return out


def unorderable_positions(unit: dict, rows: list[dict]) -> list[int]:
    """품목주거래처 공란 + 계획서 실거래처 매핑도 없는 행 위치 — 하단 적용 제외 대상.

    ERP 는 이런 행이 체크에 섞이면 '적용하시겠습니까?' [예] 를 받고도 **무반응**(에러·경고
    없음)으로 팝업을 유지해 공란 1행이 배치 전체를 20s 타임아웃으로 막는다
    (2026-09-01 empty_vendor 프로브 실측 — PROCESS.md D8).
    """
    by_class = {g.get("vendorClass"): g.get("vendor") for g in unit.get("vendorGroups") or []}
    v = str(by_class.get(UNASSIGNED_CLASS) or "").strip()
    if v and v != UNASSIGNED_CLASS:
        return []
    return [i for i, r in enumerate(rows) if not str(r.get("PRINCIPALPARTN_NM") or "").strip()]


async def ensure_po_type(page: Any) -> dict:
    """구매발주유형=원재료 — **반드시 코드피커 경로**.

    ⛔ 코드+표시(hidden/_text) 직접 세팅은 폼 값만 채우고 **위젯 내부 모델이 비어** `구매요청`
    버튼이 다이얼로그조차 없이 무반응이 된다(2026-08-31 po_potype_diag 프로브 실측: direct →
    팝업 미출현, picker → 정상). D3 의 '위젯 내부 모델 미검증' 경고가 이 화면에서 실증된 것 —
    속도 최적화로 되돌리지 말 것.
    """
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
        await verify.DEFAULT_SLEEP(0.3)
        waited += 300
    return int(last or -1)


def row_key(row: dict) -> str:
    """팝업 행 식별키 — 구매요청번호|순번|품목코드. 행 번호는 재조회·재정렬로 무효가 된다."""
    return "|".join(
        str(row.get(f) or "").strip() for f in ("PURREQ_NO", "PURREQ_SQ", "ITEM_CD")
    )


def row_keys(rows: list[dict]) -> list[str]:
    """그리드 전 행의 식별키(같은 키가 여러 행이면 등장 순서 #n 으로 구분)."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for r in rows:
        k = row_key(r)
        n = seen.get(k, 0)
        seen[k] = n + 1
        out.append(f"{k}#{n}")
    return out


async def popup_locate_rows(page: Any, keys: list[str]) -> dict:
    """식별키로 현재 그리드에서 행 번호를 다시 찾는다 — {ok, idxs, missing, rowCount}.

    2026-09-02 ETRI-026 실측: 타 요청 잔존 행이 섞인 채 조회가 끝난 것처럼 보인 뒤 필터 재조회
    결과가 늦게 도착해 그리드가 갈아끼워지면, 조회 시점의 행 번호가 무효가 되어 변경거래처
    적용 확인(전부 None)·재클릭(체크 0행)이 헛돌았다. 번호 대신 키로 매번 다시 찾는다.
    """
    read = await page.evaluate(j3.POPUP_GRID_ROWS_JS, [0, 2000])
    rows = (read or {}).get("rows") or []
    pos = {k: i for i, k in enumerate(row_keys(rows))}
    found = [(k, pos.get(k)) for k in keys]
    missing = [k for k, i in found if i is None]
    return {
        "ok": not missing,
        "idxs": [i for _, i in found if i is not None],
        "missing": missing,
        "rowCount": len(rows),
    }


async def popup_query_prq(
    page: Any,
    prq: str,
    *,
    tries: int = 4,
    allow_missing: bool = False,
    zero_cap_ms: int | None = None,
) -> dict:
    """구매요청번호 필드 + trusted Enter → 그 PRQ 라인만(프로브 ✅ 647→84, 팝업 소멸 없음).

    ⚠ 결과검증형 재시도(2026-08-31 ETRI-004 실측): Enter 직후 서버 재조회 중에는 그리드가 잠깐
      **0행**이 되는데, 0→0 을 '안정'으로 오판해 즉시 실패했다(행 0/조회 전 17). 0행은 실패 확정이
      아니라 재시도 사유다 — 행이 생기고 전부 해당 PRQ 일 때만 성공, 타 요청이 섞이면 즉시 실패.
    """
    before = await page.evaluate(j3.POPUP_GRID_COUNT_JS, 0)
    r = await set_text_verified(page, POPUP_PRQ_FIELD, prq)
    if not r.get("ok"):
        return r
    attempts: list[int] = []
    for attempt in range(1, tries + 1):
        await page.keyboard.press("Enter")
        await verify.DEFAULT_SLEEP(0.5)
        # 0행(재조회 중 공백)은 안정으로 치지 않고 행이 생길 때까지 기다린다(상한 내).
        waited = 0
        # zero_cap_ms: 0행이 이어질 때 행 출현을 기다리는 상한. 재개 대상은 '0행 = 이미 발주'가
        # 지배적이라(2026-08-31 ETRI-004~006 실측) 짧게 자르고 즉시 스킵 판정으로 넘어간다.
        cap = latency.budget_ms(zero_cap_ms or POPUP_CAP_MS)
        n = -1
        while waited < cap:
            n = await page.evaluate(j3.POPUP_GRID_COUNT_JS, 0)
            if isinstance(n, int) and n > 0:
                stable = await _wait_popup_rows_stable(page)
                n = stable if stable > 0 else n
                break
            await verify.DEFAULT_SLEEP(0.6)
            waited += 600
        attempts.append(int(n))
        if not isinstance(n, int) or n <= 0:
            continue  # 여전히 0행 — 재조회 지연으로 보고 Enter 재시도.
        read = await page.evaluate(j3.POPUP_GRID_ROWS_JS, [0, 2000])
        rows = read.get("rows") or []
        # ⚠ 필터가 간헐 미적용돼 타 요청 잔존 행이 섞일 수 있다(2026-08-31 ETRI-005 #4: 141 = 대상
        #   124 + 잔존 17). 순수성을 요구하지 말고 **일치 행만 골라**(실 인덱스 보존) 진행한다 —
        #   비일치 행은 체크하지 않으므로 하단 적용에서 자연 배제된다.
        matched = [(i, x) for i, x in enumerate(rows) if str(x.get("PURREQ_NO") or "").strip() == prq]
        if matched:
            foreign = len(rows) - len(matched)
            if foreign > 0:
                # 잔존 행이 섞였다 = 필터 재조회가 아직 안 끝났을 수 있다(2026-09-02 ETRI-026 실측:
                # 조회 직후 잡은 행 번호가 늦게 온 재조회로 무효화 → 변경거래처 미반영 23/23).
                # 잠깐 더 기다려 그리드가 바뀌었으면 바뀐 그리드로 다시 매칭한다.
                await verify.DEFAULT_SLEEP(1.0)
                again = await page.evaluate(j3.POPUP_GRID_ROWS_JS, [0, 2000])
                rows2 = (again or {}).get("rows") or []
                if rows2 and len(rows2) != len(rows):
                    rows = rows2
                    matched = [(i, x) for i, x in enumerate(rows) if str(x.get("PURREQ_NO") or "").strip() == prq]
                    foreign = len(rows) - len(matched)
                    n = len(rows)
            keys_all = row_keys(rows)
            return {
                "ok": True,
                "rows": [x for _, x in matched],
                "idxs": [i for i, _ in matched],
                "keys": [keys_all[i] for i, _ in matched],
                "count": n,
                "foreign": foreign,
            }
    if allow_missing:
        # 자동 재개 대상(이전 런 PRQ)은 0행 = 이미 발주 완료가 지배적 — 실패가 아니라 스킵 신호.
        return {"ok": True, "already": True, "rows": [], "idxs": []}
    return {
        "ok": False,
        "reason": (
            f"{prq} 조회가 {tries}회 시도에도 행을 반환하지 않았습니다"
            f"(시도별 행수 {attempts}, 조회 전 {before}) — 상신 반영 지연 또는 요청일 범위 문제."
        ),
    }


async def popup_apply_vendor(
    page: Any, row_idxs: list[int], vendor_name: str, *, keys: list[str] | None = None
) -> dict:
    """행 체크 → 변경거래처 코드피커(검색어) → #btn_apply → 대상 행의 CHG_PARTNER_NM 반영 확인.

    keys 가 있으면 행 번호를 믿지 않고 매 단계 식별키로 다시 찾는다(그리드 재조회·재정렬 방어).
    미반영이면 행 재체크 + 피커 재선택 + [적용] 재클릭 1회(종전 재클릭은 체크가 풀린 상태에서
    빈 적용을 눌러 헛돌았다 — 2026-09-02 ETRI-026 118/119).
    반환 {ok, display, codes, retried, idxs(최종 행 번호), relocated}.
    """
    original = list(row_idxs)

    async def _current() -> tuple[list[int] | None, str | None]:
        if not keys:
            return list(row_idxs), None
        loc = await popup_locate_rows(page, keys)
        if not loc.get("ok"):
            return None, f"팝업 행 재탐색 실패 — 누락 {len(loc.get('missing') or [])}/{len(keys)}(그리드 {loc.get('rowCount')}행)"
        return list(loc["idxs"]), None

    async def _check(idxs: list[int]) -> dict | None:
        await page.evaluate(j3.POPUP_CHECK_ALL_JS, [0, False])
        c = await page.evaluate(j3.POPUP_CHECK_ROWS_JS, [0, idxs])
        got = sorted(int(x) for x in (c.get("checked") or []))
        if not c.get("ok") or got != sorted(idxs):
            return {"ok": False, "reason": f"팝업 행 체크 불일치 — 기대 {len(idxs)} / 실제 {len(got)}"}
        return None

    cur, err = await _current()
    if err:
        return {"ok": False, "reason": err}
    bad_check = await _check(cur)
    if bad_check:
        return bad_check
    kw = vendor_keyword(vendor_name)
    p = await pick_code_document(page, POPUP_VENDOR_FIELD, kw)
    if not p.get("ok"):
        return {"ok": False, "reason": f"변경거래처 '{kw}' 선택 실패 — {p.get('reason')}"}
    a = await click_by_id(page, POPUP_APPLY_BTN)
    if not a.get("ok"):
        return a

    async def _poll_reflect() -> tuple[list[int], dict, list[int]]:
        # 반영을 고정 슬립 대신 결과 폴링으로 확인(0.3s 간격, 상한 6s) — 보통 1s 내 반영.
        # 매 회 식별키로 행을 다시 찾는다(그리드가 갈아끼워져도 같은 행을 본다).
        waited = 0
        vals: dict = {}
        idxs = list(cur)
        bad: list[int] = list(idxs)
        while waited < 6_000:
            found, _ = await _current()
            if found is not None:
                idxs = found
            vals = await page.evaluate(j3.POPUP_FIELDS_JS, [0, idxs, ["CHG_PARTNER_NM", "CHG_PARTNER_CD"]])
            bad = [i for i in idxs if norm(kw) not in norm((vals.get(str(i)) or vals.get(i) or {}).get("CHG_PARTNER_NM"))]
            if not bad:
                break
            await verify.DEFAULT_SLEEP(0.3)
            waited += 300
        return bad, vals, idxs

    bad, vals, final = await _poll_reflect()
    retried = False
    checked_n = -1
    if bad:
        # 미반영 — 체크 유지 여부를 진단으로 남기고, 행을 다시 찾아 재체크·피커 재선택 후 [적용]
        # 1회 재클릭. 성공 시 retried 를 반환해 호출부가 경고 로그로 표면화한다(조용한 재시도 금지).
        chk = await page.evaluate(j3.POPUP_CHECK_ROWS_JS, [0, []])  # 빈 목록 = 체크 변경 없이 현황만.
        checked_n = len(chk.get("checked") or []) if chk.get("ok") else -1
        cur2, err2 = await _current()
        if err2:
            return {"ok": False, "reason": err2 + " (변경거래처 적용 미반영 후 재탐색)"}
        cur = cur2
        bad_check = await _check(cur)
        if bad_check:
            return bad_check
        p2 = await pick_code_document(page, POPUP_VENDOR_FIELD, kw)
        if not p2.get("ok"):
            return {"ok": False, "reason": f"변경거래처 '{kw}' 재선택 실패 — {p2.get('reason')}"}
        a2 = await click_by_id(page, POPUP_APPLY_BTN)
        if a2.get("ok"):
            retried = True
            bad, vals, final = await _poll_reflect()
    if bad:
        sample = (vals.get(str(bad[0])) or vals.get(bad[0]) or {})
        return {
            "ok": False,
            "reason": (
                f"변경거래처 적용 미반영 행 {len(bad)}/{len(final)} — 예 {sample}"
                f" (재체크+재클릭 {'1회 포함' if retried else '실패'} · 1차 무반응 시 체크 유지 {checked_n}행)"
            ),
        }
    codes = {str((vals.get(str(i)) or vals.get(i) or {}).get("CHG_PARTNER_CD")) for i in final}
    return {
        "ok": True,
        "display": p.get("display"),
        "codes": sorted(codes),
        "retried": retried,
        "idxs": final,
        "relocated": final != original,
    }


async def popup_bottom_apply(page: Any, row_idxs: list[int], *, keys: list[str] | None = None) -> dict:
    """대상 행 체크 → 하단 적용 → '적용하시겠습니까?' [예] → 팝업 닫힘 → 마스터 행수.

    keys 가 있으면 체크 직전 식별키로 행 번호를 다시 찾는다(변경거래처 적용 뒤 그리드가 바뀐 경우).
    """
    if keys:
        loc = await popup_locate_rows(page, keys)
        if not loc.get("ok"):
            return {"ok": False, "reason": f"하단 적용 전 행 재탐색 실패 — 누락 {len(loc.get('missing') or [])}/{len(keys)}(그리드 {loc.get('rowCount')}행)"}
        row_idxs = list(loc["idxs"])
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
    # 마스터 행 출현을 결과 폴링으로(고정 1.0s 슬립 대체).
    waited = 0
    n = -1
    while waited < 8_000:
        n = await page.evaluate(j3.MAIN_GRID_COUNT_JS, 0)
        if isinstance(n, int) and n > 0:
            return {"ok": True, "master_rows": n}
        await verify.DEFAULT_SLEEP(0.3)
        waited += 300
    return {"ok": False, "reason": "하단 적용 후 본화면 마스터에 행이 생기지 않았습니다."}


async def master_rows(page: Any) -> list[dict]:
    r = await page.evaluate(j3.MAIN_GRID_ROWS_JS, [0, 200])
    return r.get("rows") or []


async def select_master_row(page: Any, idx: int, *, vendor: str | None = None) -> dict:
    """마스터 행 실 마우스 클릭 → `getCurrent()` 가 idx 인지 **독립 확인**(헤더 높이 후보 스캔) →
    디테일 재조회(행수>0) 확인. vendor 가 있으면 현재 행 PARTNER_NM 도 대조.

    2026-08-28 실측: 고정 헤더 30px 가정으로 1행 클릭이 5행을 선택 — 결과검증형 스캔으로 교체.
    """
    rect = await page.evaluate(j3.MAIN_GRID_RECT_JS, 0)
    if not rect:
        return {"ok": False, "reason": "마스터 그리드 rect 미발견"}
    # 현재 행이 이미 잡혀 있으면(직전 거래처 처리 후) **거기서부터** 방향키로 이동 — 매 행마다 첫 행
    # 클릭 후 0행부터 재보행하던 낭비 제거(거래처 10행 PRQ 에서 ~20s, 2026-08-31 속도 개선. 키 간격도
    # 0.5→0.2s — currentChanged 발화는 getCurrent 재확인으로 담보). 현재 행이 없을 때만 항상 보이는
    # **첫 행** 위치를 실클릭해 포커스를 잡는다(마스터는 ~5행만 보여 6행째 이상 좌표는 그리드 밖 —
    # 2026-08-28 ETRI-002 #3 실측. 좌표 클릭은 선택을 못 바꾸고 방향키가 디테일 재조회까지 일으킨다).
    tried: list[tuple[str, int]] = []
    cur = await page.evaluate(j3.MAIN_CURRENT_ROW_JS, 0)
    if cur < 0:
        x = rect["x"] + 200
        y = rect["y"] + MASTER_HEADER_PX + MASTER_ROW_PX // 2
        await page.mouse.click(x, y)
        await verify.DEFAULT_SLEEP(0.6)
        cur = await page.evaluate(j3.MAIN_CURRENT_ROW_JS, 0)
    tried.append(("start", cur))
    if cur == idx:
        # 이동이 없으면 currentChanged 가 안 나가 디테일 재조회가 발화되지 않을 수 있다 — 한 칸 왕복.
        first, second = ("ArrowDown", "ArrowUp") if idx == 0 else ("ArrowUp", "ArrowDown")
        await page.keyboard.press(first)
        await verify.DEFAULT_SLEEP(0.2)
        await page.keyboard.press(second)
        await verify.DEFAULT_SLEEP(0.2)
        cur = await page.evaluate(j3.MAIN_CURRENT_ROW_JS, 0)
        tried.append(("nudge", cur))
    stagnant = 0
    refocused = False
    for _ in range(60):
        if cur == idx or cur < 0:
            break
        prev = cur
        await page.keyboard.press("ArrowDown" if cur < idx else "ArrowUp")
        await verify.DEFAULT_SLEEP(0.2)
        cur = await page.evaluate(j3.MAIN_CURRENT_ROW_JS, 0)
        tried.append(("key", cur))
        if cur == prev:
            stagnant += 1
            # ⚠ 직전 행의 비고 에디터/납기 입력에 키보드 포커스가 남으면 방향키가 그리드에 안 닿아
            #   현재 행이 고정된다(2026-08-31 ETRI-005 0756 실측: idx 5 이동 실패, 4 고정) —
            #   정체 3회면 그리드를 한 번 클릭해 포커스를 되찾고 이어서 보행한다(1회 한정).
            if stagnant >= 3 and not refocused:
                refocused = True
                await page.mouse.click(rect["x"] + 200, rect["y"] + MASTER_HEADER_PX + MASTER_ROW_PX // 2)
                await verify.DEFAULT_SLEEP(0.5)
                cur = await page.evaluate(j3.MAIN_CURRENT_ROW_JS, 0)
                tried.append(("refocus", cur))
                stagnant = 0
        else:
            stagnant = 0
    for _ in range(1):
        if cur != idx:
            continue
        if vendor:
            vals = await page.evaluate(j3.MAIN_FIELDS_JS, [0, [idx], ["PARTNER_NM"]])
            got = str((vals.get(str(idx)) or vals.get(idx) or {}).get("PARTNER_NM") or "")
            if norm(got) != norm(vendor):
                return {"ok": False, "reason": f"마스터 {idx}행 거래처 불일치 — 기대 {vendor!r} / 실제 {got!r}"}
        waited = 0
        while waited < 8_000:
            n = await page.evaluate(j3.MAIN_GRID_COUNT_JS, 1)
            if isinstance(n, int) and n > 0:
                return {"ok": True, "detail_rows": n, "moves": tried}
            await verify.DEFAULT_SLEEP(0.4)
            waited += 400
        return {"ok": False, "reason": f"마스터 {idx}행 선택 후 디테일이 채워지지 않았습니다."}
    return {"ok": False, "reason": f"마스터 {idx}행을 클릭으로 선택하지 못했습니다(헤더 후보별 현재행 {tried})."}


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
    from .nodes.save_units import _digits  # KST 정규화 공유

    want = _digits(due)
    # 반영을 결과 폴링으로(고정 1.0s 슬립 대체, 0.3s 간격 상한 6s).
    waited = 0
    vals: dict = {}
    bad: list[int] = list(range(n))
    while waited < 6_000:
        vals = await page.evaluate(j3.MAIN_FIELDS_JS, [1, list(range(n)), [DUE_FIELD]])
        bad = [i for i in range(n) if _digits((vals.get(str(i)) or vals.get(i) or {}).get(DUE_FIELD)) != want]
        if not bad:
            break
        await verify.DEFAULT_SLEEP(0.3)
        waited += 300
    if bad:
        snacks = [s.get("text") for s in (await page.evaluate(js.SNACKBARS_JS) or []) if s.get("text")]
        cur = (vals.get(str(bad[0])) or vals.get(bad[0]) or {}).get(DUE_FIELD)
        return {"ok": False, "reason": f"납기 {due} 미반영 디테일 행 {len(bad)}/{n}(현재 {cur!r}, 스낵바 {snacks[:2]})"}
    return {"ok": True, "rows": n}


def due_before_today(due: str, today: str) -> bool:
    """계획 납기가 발주일(오늘) 이전이면 True — ERP 가 조용히 무시하므로(2026-08-28 실측 08-21) 적용을 건너뛴다."""
    d, t = re.sub(r"\D", "", due or "")[:8], re.sub(r"\D", "", today or "")[:8]
    return bool(d) and bool(t) and d < t


async def _read_note(page: Any, idx: int) -> str:
    vals = await page.evaluate(j3.MAIN_FIELDS_JS, [0, [idx], ["RMK_DC"]])
    return str((vals.get(str(idx)) or vals.get(idx) or {}).get("RMK_DC") or "").strip()


async def set_master_note(page: Any, idx: int, text: str) -> dict:
    """마스터 RMK_DC 인라인 편집 — 빠른 것부터 폴백 체인, 각 단계 `ds.getValue` 독립 확인.

    ⓪ 그리드 setValue + 즉시 확인(수 ms — 사용자 지시 2026-09-01: 싸고 빠른 걸 먼저, 실패 시에만
      느리고 확실한 UI 경로)  ① 에디터 오픈 → 오버레이 input 로케이터 fill + Enter
    ② 오픈 → 트리플클릭 전체선택 → 타이핑 + Enter.
    ⚠ getValue 확인은 그리드 모델 반영까지 보장 — 저장 시 서버 반영은 실발주 런에서 최종 검증
      (setValue 파생 미동기 전례: 발주유형 직접 세팅 시 버튼 무반응, po_potype_diag).
    """
    tried: list[str] = []

    # ⓪ setValue 선시도 — 실패/미반영 시에만 UI 편집으로 폴백.
    r = await page.evaluate(
        """([i, f, v]) => { try {
             const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[0]).data('dewsControl')._grid;
             g.setValue(i, f, v); return { ok: true };
           } catch (e) { return { ok: false, err: String(e).slice(0, 100) }; } }""",
        [idx, "RMK_DC", text],
    )
    if r.get("ok") and await _read_note(page, idx) == text.strip():
        return {"ok": True, "via": "setValue"}
    tried.append(f"setValue {r} → {await _read_note(page, idx)!r}")

    async def _open() -> dict | None:
        o = await page.evaluate(j3.MAIN_OPEN_EDITOR_JS, [idx, "RMK_DC"])
        if not o.get("ok"):
            return None
        await verify.DEFAULT_SLEEP(0.6)
        return await page.evaluate(j3.MAIN_EDITOR_INPUT_JS)

    # ① 로케이터 fill
    inp = await _open()
    if inp:
        try:
            await page.locator(f"#{inp['id']}").fill(text, timeout=3_000)
            await page.keyboard.press("Enter")
            await verify.DEFAULT_SLEEP(0.6)
            if await _read_note(page, idx) == text.strip():
                # 에디터가 열린 채 남으면(2026-08-28 스크린샷) 저장 클릭을 방해할 수 있어 Tab 으로 닫고 재확인.
                await page.keyboard.press("Tab")
                await verify.DEFAULT_SLEEP(0.4)
                if await _read_note(page, idx) == text.strip():
                    return {"ok": True, "via": "fill"}
            tried.append(f"fill→{await _read_note(page, idx)!r}")
        except Exception as exc:  # noqa: BLE001
            tried.append(f"fill EXC {str(exc)[:60]}")
        await page.keyboard.press("Escape")
    else:
        tried.append("editor-open-failed")

    # ② 트리플클릭 + 타이핑
    inp = await _open()
    if inp:
        await page.mouse.click(inp["x"], inp["y"], click_count=3)
        await page.keyboard.type(text, delay=10)
        await page.keyboard.press("Enter")
        await verify.DEFAULT_SLEEP(0.6)
        if await _read_note(page, idx) == text.strip():
            return {"ok": True, "via": "type"}
        tried.append(f"type→{await _read_note(page, idx)!r}")
        await page.keyboard.press("Escape")

    return {"ok": False, "reason": f"비고 커밋 실패 — 기대 {text!r}, 시도 {tried}"}


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
