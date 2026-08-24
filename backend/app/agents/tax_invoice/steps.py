"""세금계산서 결의서입력 — 브라우저 스텝(진입 후 본문·팝업 조작).

재사용 원칙: 공용 detail 채움(거래처·프로젝트·금액 타이핑·적요)은 `trip_domestic.steps` 를
그대로 import 하고(쓰기 프로브가 이 조합으로 완전 사이클 PASS — PROCESS.md 검증 로그),
관리항목(tb1) 패널 접근 JS 는 `card_collect.mgmt_items` 를 재사용하며, 세금계산서 고유(증빙
적용 후 다이얼로그·전자세금계산서 팝업·분할처리 팝업·자금과목 채움)만 여기 둔다.
in-page JS 는 :mod:`.js`(프로브 승격분) + `nbkit.omnisol.js_lib`.

반환 dict 컨벤션(형제 동일): {"ok": bool, "reason"?: 하드 실패 사유, "warn"?: 확인 불가 경고}.

⚠ 저장(F7)은 여기서 하지 않는다 — nodes/save.py 의 게이트(card save_document)만 실행한다.
⚠ 분할처리 '적용' 이후는 F7 과 동일한 비가역 지점 — confirm_split_apply 는 팝업 닫힘(개수
  감소)을 확인 못 하면 실패를 돌려준다(팬텀 저장 방지 — 쓰기 프로브 attempt 1 원인).
"""

from __future__ import annotations

from typing import Any

from nbkit.browser.actions import mouse_click
from nbkit.omnisol import js_lib, latency, verify
from nbkit.omnisol.codepicker import _norm, _picker_search

# 관리항목(tb1) 패널 접근 JS — 라벨 텍스트로 행을 찾는 3종(카드 실측 검증분 재사용).
from app.agents.card_collect.mgmt_items import (
    _ROW_BUTTON_JS,
    _ROW_SCROLL_JS,
    _ROW_VALUES_JS,
)

# 공용 재사용 스텝 — 쓰기 프로브 검증 조합(fill 노드가 `steps.<name>` 으로 참조).
from app.agents.trip_domestic.steps import (  # noqa: F401
    _cell_matches,
    _cell_unreadable,
    _fail_close,
    _fill_partner_cell,
    _open_detail_cell_picker,
    _popup_count,
    _read_detail_cell,
    _search_and_pick,
    fill_project,
    set_row_note,
    type_amount,
)

from . import js

# ── 상수(PROCESS.md 실측) ────────────────────────────────────────────────────
GATE_DIALOG_HINT = "전자발행된 증빙"  # "전자발행된 증빙으로 입력하시겠습니까?" 공통 문구.
SPLIT_POPUP_TITLE = "분할처리"
BUDGET_STATUS_TITLE = "예산현황"  # 분할 확정 후 남는 예산 배분 검증 창(스모크 실측).
BUDGET_MODAL_LABELS = ("확인", "예", "닫기")  # 라벨 변형 대비 우선순위(형제 관례).
INVOICE_POPUP_HINTS = ("전자세금계산서", "전자계산서")
# 팝업 내 재조회 버튼 — **정확일치**로 찾는다. 팝업 버튼은 ['품목정보','조회','일괄적용',
# '적용','닫기'](A/B 진단 실측)이고 본창에도 '조회 (F2)' 가 있어, 부분일치는 본창 버튼이나
# '일괄적용' 쪽으로 샐 여지를 남긴다.
INVOICE_QUERY_BTN_TEXTS = ("조회", "검색")
INVOICE_POPUP_CAP_MS = 10_000  # 증빙 적용 → 계산서 모달 출현·그리드 바인딩 대기 예산.
# 조회 클릭 후 로딩 안정 판정(2026-08-19 진단 실측: 클릭 후 t=400ms 부터 36행 안정).
INVOICE_QUERY_POLL_S = 0.4
INVOICE_ROWS_SETTLE_REPEATS = 2  # 직전 값과 동일한 관측 2회 연속 = 안정.
INVOICE_ROWS_MIN_MS = 800  # 행이 온 뒤 안정 판정 최소 관찰창.
# ⚠ 0행은 **길게** 확인한다 — 진단은 400ms 에 36행을 봤지만 그건 팝업이 충분히 정착한 뒤 누른
#   클릭이었다. 갓 열린 팝업에 누른 클릭은 무반응일 수 있어(실런 24b8fd76/67bfe659), 짧은 창의
#   '0 안정'은 '진짜 0건'이 아니라 '아직 아무 일도 안 일어남'이다.
INVOICE_EMPTY_CONFIRM_MS = 4_000  # 이 시간 내내 0행이어야 한 번의 조회가 빈 결과라고 본다.
INVOICE_QUERY_ATTEMPTS = 2  # 0행이면 조회를 1회 더 실행(삼켜진 클릭 회수).
INVOICE_POPUP_READY_REPEATS = 2  # 클릭 전 팝업 정착 — 연속 성공 읽기 횟수.
INVOICE_QUERY_CAP_MS = 12_000
DIST_LINE_INPUT = "#GLDDOC00300_DISTRIBUTION_grid_line"  # 분할 적요 인라인 에디터.
DIST_NUMBER_INPUT = "#GLDDOC00300_DISTRIBUTION_grid_number"  # 분할 금액 인라인 에디터.
DIST_NOTE_FIELD = "NOTE_DC"  # 분할처리 팝업 컬럼(17종 확정 — 검증 로그).
DIST_AMOUNT_FIELD = "SPPRC_AMT2"
DIST_CC_FIELD = "CC_NM"
DIST_PJT_FIELD = "PJT_NM"
BUDGET_FIELDS = ["BG_CD", "BG_NM", "BIZPLAN_NM", "BGACCT_NM"]
FUND_ITEM_LABEL = "자금과목"  # 관리항목 패널 행 라벨(위젯은 캔버스 셀이 아니라 tb1 DOM 패널).
DEFAULT_FUND_NAME = "일반경비"  # D8 기본값(FUND_CD 5310) — 계정 관리항목이 요구하면 필수.


# ══════════════════════════════════════════════════════════════════════════════
# 순수 헬퍼(브라우저 불필요 — 단위 테스트 대상)
# ══════════════════════════════════════════════════════════════════════════════
def evdn_dialog_answer(issue: str) -> str:
    """증빙 적용/조회 다이얼로그("전자발행된 증빙으로 입력하시겠습니까?") 응답.

    발행 전(22/23/24) = "아니요", 발행 후(03/04/05/06/07·11/13) = **분할 여부와 무관하게 "예"**
    (쓰기 프로브 실측: 11 은 "예"로 통과). 수동분할의 계산서 조회 스킵은 조회(F2)를 누르지
    않는 것으로 달성한다 — pick_invoices 스킵 분기가 그 역할이다.
    """
    return "아니요" if issue == "pre" else "예"


def classify_post_apply_modals(modals: list[dict] | None) -> tuple[str, list[str]]:
    """증빙 '적용' 직후 보이는 k-window 들을 분류한다.

    - "dialog": 게이트 다이얼로그(`전자발행된 증빙…`) 또는 정체불명 창 → 텍스트 목록 반환
    - "popup": 계산서 리스트 팝업(`전자세금계산서/전자계산서`)만 열림 — 03/04 등 무다이얼로그
      코드의 정상 경로다(PROCESS.md D5: 적용이 리스트 모달을 연다). 다이얼로그로 오인하지 않는다
    - "none": 아무 창도 없음
    """
    texts = [str(m.get("text") or m.get("title") or "") for m in (modals or [])]
    others = [
        t for m, t in zip(modals or [], texts)
        if not any(h in str(m.get("title") or "") for h in INVOICE_POPUP_HINTS)
    ]
    if others:
        return "dialog", others
    if texts:
        return "popup", []
    return "none", []


def pick_row_by_text(rows: list[dict], text: str) -> tuple[int | None, dict | None]:
    """팝업 그리드 행에서 필드명과 무관하게 문자열 값 중 text 를 포함하는 첫 행(쓰기 프로브 이식).

    사유구분·계정과목 팝업은 필드명이 화면마다 달라 code/name 컬럼을 가정할 수 없다.
    """
    for i, r in enumerate(rows):
        for v in r.values():
            if isinstance(v, str) and text and text in v:
                return i, r
    return None, None


def pick_budget_by_name(options: list[dict], name: str) -> tuple[dict | None, str | None]:
    """예산단위 후보에서 BG_NM 정규화 완전일치 단건 선택 — 무/다중(BG_CD 상이)은 한국어 오류."""
    want = _norm(name)
    matches = [o for o in options if _norm(o.get("BG_NM")) == want]
    if not matches:
        cands = ", ".join(str(o.get("BG_NM") or "") for o in options[:6]) or "없음"
        return None, f"예산단위 '{name}' 일치 없음(후보: {cands})"
    codes = {str(o.get("BG_CD")) for o in matches}
    if len(codes) > 1:
        cands = ", ".join(f"{o.get('BG_NM')}({o.get('BG_CD')})" for o in matches[:6])
        return None, f"예산단위 '{name}' 후보 여러 건({cands}) — 이름으로 특정 불가"
    return matches[0], None


def balance_row_index(rows: list[dict]) -> int | None:
    """차액반영이 만든 잔액행 — 적요는 비고 금액은 찬 행(쓰기 프로브 판정식 이식)."""
    for i, r in enumerate(rows):
        note_empty = not str(r.get(DIST_NOTE_FIELD) or "").strip()
        if note_empty and r.get(DIST_AMOUNT_FIELD) not in (None, ""):
            return i
    return None


def orphan_row_indexes(rows: list[dict]) -> list[int]:
    """금액이 비어 있는 고아 행(미리 만든 빈 행 — 차액반영이 채우지 않는 사양) 전부."""
    return [i for i, r in enumerate(rows) if r.get(DIST_AMOUNT_FIELD) in (None, "")]


def map_split_plan_to_grid(plan_rows: list[dict], grid_rows: list[dict]) -> list[int] | None:
    """분할 계획 행 → 분할 그리드 행 인덱스 매핑(적요 정규화 일치, 중복 적요는 순서 배정).

    행 수가 다르거나 매핑 불가면 None(호출측이 한국어 오류로 승격).
    """
    if len(plan_rows) != len(grid_rows):
        return None
    used: set[int] = set()
    out: list[int] = []
    for p in plan_rows:
        want = _norm(p.get("note"))
        gi = next(
            (i for i, g in enumerate(grid_rows) if i not in used and _norm(g.get(DIST_NOTE_FIELD)) == want),
            None,
        )
        if gi is None:  # 적요 무매칭 — 남은 행 중 첫 행(순서 배정 폴백).
            gi = next((i for i in range(len(grid_rows)) if i not in used), None)
        if gi is None:
            return None
        used.add(gi)
        out.append(gi)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 공용 소형 브라우저 헬퍼
# ══════════════════════════════════════════════════════════════════════════════
async def _wait_popup_titled(page: Any, hints: tuple[str, ...], *, cap_ms: int = 6_000) -> bool:
    """제목에 hints 중 하나를 포함하는 k-window 출현 폴링(실측 300ms 간격)."""
    waited = 0
    budget = latency.budget_ms(cap_ms)
    while waited < budget:
        await verify.DEFAULT_SLEEP(0.3)
        waited += 300
        titles = await page.evaluate(js.VISIBLE_POPUP_TITLES_JS)
        if any(h in t for t in (titles or []) for h in hints):
            return True
    return False


async def _dump_popup_grid(page: Any, limit: int = 50, *, cap_ms: int = 8_000) -> dict:
    """최상단 팝업 그리드 준비 폴링 후 덤프 — '도움창 확인 중' 로딩 함정 대응(프로브 실측)."""
    waited = 0
    budget = latency.budget_ms(cap_ms)
    dump: dict = {"ok": False}
    while True:
        dump = await page.evaluate(js.INVOICE_POPUP_DUMP_JS, limit)
        if dump.get("grid") and not dump["grid"].get("err"):
            return dump
        if waited >= budget:
            return dump
        await verify.DEFAULT_SLEEP(0.3)
        waited += 300


async def _click_modal(page: Any, label: str) -> bool:
    btn = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, label)
    if btn:
        await mouse_click(page, btn["x"], btn["y"])
        return True
    return False


async def _answer_modals(page: Any, labels: tuple[str, ...]) -> list[str]:
    """뜨는 모달을 labels 우선순위로 눌러 닫는다(최대 3라운드). 클릭한 라벨 목록 반환."""
    clicked: list[str] = []
    for _ in range(3):
        await page.wait_for_timeout(600)
        modals = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
        if not modals:
            break
        hit = False
        for label in labels:
            if await _click_modal(page, label):
                clicked.append(label)
                hit = True
                break
        if not hit:
            break
    return clicked


# ══════════════════════════════════════════════════════════════════════════════
# 증빙유형 적용 + 다이얼로그(쓰기 프로브 _select_evdn 승격)
# ══════════════════════════════════════════════════════════════════════════════
async def select_evidence(page: Any, code: str, answer: str) -> dict:
    """증빙유형 code 선택·적용 + 뒤따르는 "전자발행된 증빙…" 다이얼로그를 answer 로 응답.

    다이얼로그는 코드별로 안 뜨기도 한다(03/04 는 조회 시점 발화 — PROCESS.md) — 최대 4.5s
    관찰 후 없으면 그대로 진행. 반환 {ok, dialog_texts, answered, cell, picked_name}|
    {ok:False, reason}. cell 은 적용 후 재독한 증빙 셀 표시명이고 picked_name 은 팝업에서 고른
    항목명 — 호출측(select_evdn 노드)이 둘의 일치로 적용을 판정한다.
    """
    opened = False
    for _attempt in range(3):
        shown = await page.evaluate(js_lib.OPEN_EVDN_EDITOR_JS)
        if not shown:
            continue
        # 돋보기 rect 출현 관찰창 — 실시간(시간축 규율: 명목 카운터는 delay_scale 로 붕괴).
        rect = None
        waited = 0
        rect_cap_ms = latency.budget_ms(1_500)
        while waited < rect_cap_ms:
            await verify.DEFAULT_SLEEP(0.15)
            waited += 150
            rect = await page.evaluate(js_lib.EVDN_EDITOR_MAGNIFIER_RECT_JS)
            if rect:
                break
        if not rect:
            continue
        await mouse_click(page, rect["x"], rect["y"])
        for _ in range(20):
            await page.wait_for_timeout(300)
            if await page.evaluate(js_lib.EVDN_POPUP_OPEN_JS):
                opened = True
                break
        if opened:
            break
    if not opened:
        return {"ok": False, "reason": "증빙유형 팝업이 열리지 않았습니다(돋보기 3회 실패)."}
    # 팝업 오픈 직후 로딩 중이면 select 가 code-not-found — 성공까지 조건 폴링(프로브 실측).
    sel = {"ok": False}
    for _ in range(20):
        sel = await page.evaluate(js_lib.EVDN_SELECT_BY_CODE_JS, code)
        if sel.get("ok"):
            break
        await page.wait_for_timeout(300)
    if not sel.get("ok"):
        await page.evaluate(js_lib.PICKER_CLOSE_JS)
        return {"ok": False, "reason": f"증빙유형 코드 {code} 선택 실패: {sel}"}
    box = await page.evaluate(js_lib.EVDN_APPLY_BOX_JS)
    if not box:
        await page.evaluate(js_lib.PICKER_CLOSE_JS)
        return {"ok": False, "reason": "증빙유형 '적용' 버튼을 찾지 못했습니다."}
    await mouse_click(page, box["x"], box["y"])
    # 적용 직후 다이얼로그 — 헤드리스 렌더 지연으로 고정 1회 스냅샷은 놓친다(프로브 실측) →
    # 최대 4.5s **실시간** 관찰창(시간축 규율). 없으면 무다이얼로그 코드(03/04 등)로 보고 진행.
    # ⚠ 03 등은 적용이 곧바로 계산서 리스트 팝업(k-window)을 연다 — 그 창은 다이얼로그가 아니라
    # 무다이얼로그 경로의 정상 결과이므로 분류해서 통과시킨다(실런 f2270bb3 오인 중단 재발 방지).
    kind = "none"
    dialog_texts: list[str] = []
    waited = 0
    modal_cap_ms = latency.budget_ms(4_500)
    while waited < modal_cap_ms:
        await verify.DEFAULT_SLEEP(0.3)
        waited += 300
        kind, dialog_texts = classify_post_apply_modals(
            await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
        )
        if kind != "none":
            break
    answered: str | None = None
    if kind == "dialog":
        # ⚠ 모르는 다이얼로그에는 임의로 응답하지 않는다 — 비가역 조작일 수 있다.
        if not any(GATE_DIALOG_HINT in str(t) for t in dialog_texts):
            return {
                "ok": False,
                "reason": (
                    f"증빙 적용 후 모르는 다이얼로그가 떴습니다: '{str(dialog_texts[0])[:160]}' — "
                    "임의로 응답하지 않고 중단합니다."
                ),
            }
        if not await _click_modal(page, answer):
            return {
                "ok": False,
                "reason": f"증빙 다이얼로그에서 '{answer}' 버튼을 찾지 못했습니다.",
            }
        answered = answer
        await page.wait_for_timeout(800)
    # 세팅→독립확인: 증빙 셀(EVDN_TP_NM)이 고른 항목명으로 바뀔 때까지 실시간 관찰(상한 8s —
    # doc_steps.select_evdn_code 와 동일 판정). 상한을 넘겨도 마지막 셀값을 그대로 돌려주고
    # 일치 판정은 호출측이 한다(여기서 성공을 단정하지 않는다).
    picked_name = str(sel.get("name") or "")
    cell = ""
    waited = 0
    cell_cap_ms = latency.budget_ms(8_000)
    while True:
        cell = str(await page.evaluate(js_lib.DETAIL_EVDN_CELL_JS) or "")
        if picked_name and picked_name in cell:
            break
        if waited >= cell_cap_ms:
            break
        await verify.DEFAULT_SLEEP(0.3)
        waited += 300
    return {
        "ok": True,
        "dialog_texts": dialog_texts,
        "answered": answered,
        "cell": cell,
        "picked_name": picked_name,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 예산단위(BG_NM 정확명) · 사유구분(비과세)
# ══════════════════════════════════════════════════════════════════════════════
async def fill_budget_by_name(page: Any, budget_unit_name: str) -> dict:
    """예산단위 셀 피커 — 사용자 지정 예산단위명(BG_NM) 검색→완전일치 선택→적용→확인→셀 재독.

    ⚠ 픽커는 BG_CD 가 아니라 표시필드 **BG_NM** 으로 연다(PROCESS.md 실측 — 프로브 3회 헛돎).
    적용 시 사업계획/예산계정/계정/비용센터 자동연동(실측). ⚠ trip `_select_and_apply` 를 쓰지
    않는 이유: 세금계산서는 적용 직후 "확인" 안내 모달이 뜰 수 있어(PROCESS.md 셀렉터 표)
    팝업 개수 감소 판정이 모달에 가려 오탐한다 — 모달을 먼저 닫고 셀 반영·닫힘을 확인한다.
    """
    op = await _open_detail_cell_picker(page, "BG_NM", "예산단위")
    if not op.get("ok"):
        return op
    row, err = await _search_and_pick(
        page, budget_unit_name, BUDGET_FIELDS, lambda opts: pick_budget_by_name(opts, budget_unit_name)
    )
    if err or not row:
        return await _fail_close(page, err or "예산단위 후보를 읽지 못했습니다")
    sel = await page.evaluate(js_lib.PICKER_SELECT_JS, row["i"])
    if not sel.get("ok"):
        return await _fail_close(page, f"예산단위 행 선택 실패: {sel}")
    await page.wait_for_timeout(400)
    apply_box = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
    if not apply_box:
        return await _fail_close(page, "예산단위 '적용' 버튼을 찾지 못했습니다.")
    before = await _popup_count(page)
    await mouse_click(page, apply_box["x"], apply_box["y"])
    # 적용 직후 예산 안내 모달("확인") — 닫아야 팝업 개수 판정·다음 조작이 산다(프로브 관례).
    await _answer_modals(page, ("확인",))
    want = row.get("BG_NM")
    chk = await verify.confirm(
        _read_detail_cell(page, "BG_NM"),
        lambda v: not _cell_unreadable(v) and _cell_matches(_norm(want), (v.get("raw") or {}).get("BG_NM")),
        timing=verify.ASYNC,
        what="예산단위 셀(BG_NM) 반영",
        expected=want,
        unknown_when=_cell_unreadable,
    )
    if chk.mismatch:
        return await _fail_close(page, f"예산단위 적용 후 셀 미반영 — {chk.reason}")
    closed = await verify.confirm_popup_count(page, less_than=before, timing=verify.ASYNC)
    if not closed:
        return await _fail_close(page, f"예산단위 적용 후 피커가 닫히지 않았습니다 — {closed.reason}")
    out: dict = {"ok": True, "code": row.get("BG_CD"), "name": row.get("BG_NM")}
    if not chk:  # 확인 불가 — 반영을 단정하지 않고 경고만 남긴다.
        out["warn"] = chk.reason
    return out


async def fill_exempt_reason(page: Any, reason: str) -> dict:
    """비과세 사유구분(REASON_NM) — 셀 피커(팝업 label '사유구분') → 텍스트 매칭 행 → 적용 → 확인.

    04 는 미입력 시 저장 반려(녹화 실측) — 검증 체인의 일부. 팝업 필드명이 미상이라
    텍스트 매칭(pick_row_by_text)으로 고른다.
    """
    op = await _open_detail_cell_picker(page, "REASON_NM", "사유구분")
    if not op.get("ok"):
        return op
    await _picker_search(page, reason)
    dump = await _dump_popup_grid(page, 30)
    rows = (dump.get("grid") or {}).get("rows") or []
    idx, _row = pick_row_by_text(rows, reason)
    if idx is None:
        if len(rows) == 1:  # 검색이 단건으로 좁혀진 경우 폴백.
            idx = 0
        else:
            return await _fail_close(page, f"사유구분 '{reason}' 매칭 행 없음(후보 {len(rows)}건)")
    sel = await page.evaluate(js_lib.PICKER_SELECT_JS, idx)
    if not sel.get("ok"):
        return await _fail_close(page, f"사유구분 행 선택 실패: {sel}")
    await page.wait_for_timeout(400)
    apply_box = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
    if not apply_box:
        return await _fail_close(page, "사유구분 '적용' 버튼을 찾지 못했습니다.")
    before = await _popup_count(page)
    await mouse_click(page, apply_box["x"], apply_box["y"])
    await _answer_modals(page, ("확인",))  # 적용 후 "확인" 안내(녹화 exempt L55-59) — 닫힘 판정 전에 처리.
    closed = await verify.confirm_popup_count(page, less_than=before, timing=verify.ASYNC)
    if not closed:
        return {"ok": False, "reason": f"사유구분 적용 후 팝업이 닫히지 않았습니다 — {closed.reason}"}
    return {"ok": True, "reason_name": reason}


# ══════════════════════════════════════════════════════════════════════════════
# 발행 후 — 전자세금계산서 팝업(D5)
# ══════════════════════════════════════════════════════════════════════════════
async def invoice_popup_state(page: Any, limit: int = 50) -> dict:
    """전자세금계산서 팝업을 **제목으로 지정**해 상태(입력·버튼·그리드)를 읽는다.

    ⚠ '마지막 보이는 k-window' 로 잡지 않는다 — 실런(2026-08-19 b4eb0ea3)에서 팝업은 열려
    있었는데 다른 창이 뒤에 있어 조회 버튼 탐색이 0건이 됐다(PROCESS.md D5 실패 기록).
    """
    return await page.evaluate(
        js.POPUP_BY_TITLE_STATE_JS, {"hints": list(INVOICE_POPUP_HINTS), "limit": limit}
    ) or {"ok": False, "reason": "no-result"}


def best_invoice_grid(state: dict) -> dict | None:
    """팝업의 그리드 중 **결과 그리드**를 고른다 — 읽기 성공한 것들 중 행수 최대(동률은 앞선 것).

    팝업에 그리드가 여러 개면 첫 번째가 조건영역의 빈 그리드일 수 있다(진단 스크립트가
    '엉뚱한 빈 그리드' 가설을 세운 이유). 행이 하나도 없으면 첫 정상 그리드를 돌려준다 —
    0행 판정의 대상도 실제 그리드여야 한다. 전부 읽기 실패면 None.
    """
    ok_grids = [g for g in (state.get("grids") or []) if isinstance(g, dict) and not g.get("err")]
    if not ok_grids:
        return None
    return max(ok_grids, key=lambda g: (g.get("n") or 0, -(g.get("gridIndex") or 0)))


async def wait_invoice_popup_ready(page: Any, *, limit: int = 50, cap_ms: int = 8_000) -> dict:
    """팝업 출현 + 그리드 부착 + **정착**까지 실시간 폴링.

    ⚠ 부착 즉시 진행하지 않고 **연속 성공 읽기 2회**를 요구한다 — 갓 열린 팝업('도움창 확인
    중' 로딩 상태)에 누른 조회 클릭은 버튼이 이미 DOM 에 있어도 무반응이라, 그대로 0행을
    읽고 '계산서 없음'으로 끝난다(실런 24b8fd76·67bfe659 의 3.2초 실패).
    """
    waited = 0
    budget = latency.budget_ms(cap_ms)
    state: dict = {"ok": False}
    hits = 0
    while True:
        state = await invoice_popup_state(page, limit)
        hits = hits + 1 if (state.get("ok") and best_invoice_grid(state) is not None) else 0
        if hits >= INVOICE_POPUP_READY_REPEATS:
            return state
        if waited >= budget:
            return state
        await verify.DEFAULT_SLEEP(0.4)
        waited += 400


async def wait_invoice_rows_settled(
    page: Any, *, limit: int = 100, cap_ms: int = INVOICE_QUERY_CAP_MS
) -> dict:
    """조회 실행 후 결과 도착까지 대기하고 행을 읽는다.

    ⚠ 이 팝업은 열릴 때 자동 조회하지 않는다 — 열린 직후 0행이고 팝업 내 '조회'를 눌러야
    결과가 온다(2026-08-19 진단: 정착된 팝업에 클릭 → t=400ms 에 36행, 4s 까지 불변).

    판정 비대칭이 핵심이다: **행이 오면** 같은 값 2회 연속(최소 0.8s)으로 빠르게 확정하고,
    **0행이면** 최소 4s 를 꽉 채운 뒤에야 빈 결과로 본다. 0 은 '결과가 없다'와 '아직 아무
    일도 안 일어났다'가 구분되지 않는 값이라, 짧은 창의 '0 안정'을 결과로 확정하면 실런
    24b8fd76·67bfe659 처럼 실데이터 36건을 '계산서 없음'으로 끝낸다.
    반환 {ok, n, rows, settled, title} | {ok:False, reason}.
    """
    waited = 0
    cap = latency.budget_ms(cap_ms)
    rows_min_ms = latency.budget_ms(INVOICE_ROWS_MIN_MS)
    empty_ms = latency.budget_ms(INVOICE_EMPTY_CONFIRM_MS)
    poll_ms = int(INVOICE_QUERY_POLL_S * 1_000)
    prev: int | None = None
    repeats = 0
    settled = False
    while True:
        state = await invoice_popup_state(page, 0)  # 행수만 — 폴링은 가볍게.
        grid = best_invoice_grid(state) or {}
        n = grid.get("n") if state.get("ok") and grid else None
        repeats = repeats + 1 if (n is not None and n == prev) else 0
        prev = n
        stable = n is not None and repeats >= INVOICE_ROWS_SETTLE_REPEATS
        if stable and n and waited >= rows_min_ms:
            settled = True
            break
        if stable and not n and waited >= empty_ms:  # 0행은 긴 창을 다 채워야 확정.
            settled = True
            break
        if waited >= cap:
            break
        await verify.DEFAULT_SLEEP(INVOICE_QUERY_POLL_S)
        waited += poll_ms
    final = await invoice_popup_state(page, limit)
    grid = best_invoice_grid(final)
    if not final.get("ok") or grid is None:
        return {"ok": False, "reason": f"계산서 목록을 읽지 못했습니다: {_popup_diag(final)}"}
    return {
        "ok": True,
        "n": grid.get("n") or 0,
        "rows": grid.get("rows") or [],
        "settled": settled,
        "title": final.get("title"),
    }


async def run_invoice_query(page: Any) -> dict:
    """팝업 창 DOM **안에서** '조회' 정확일치 버튼을 찾아 요소 클릭한다.

    ⚠ 좌표 클릭 금지 — 본창(결의서입력)에도 조회(F2) 버튼이 있어 창이 겹치면 전역 좌표
    클릭이 **본창 조회**를 누른다(사용자 헤디드 관찰 2026-08-19 + A/B 진단). 본창 조회는
    팝업 목록을 채우지 않으므로 결과는 언제나 0행이 된다.
    반환 {ok, label}|{ok:False, reason}.
    """
    buttons: list | None = None
    for label in INVOICE_QUERY_BTN_TEXTS:
        r = await page.evaluate(
            js.CLICK_WINDOW_BUTTON_JS,
            {"titleHints": list(INVOICE_POPUP_HINTS), "textHint": None, "label": label},
        )
        if r.get("ok"):
            return {"ok": True, "label": label}
        if r.get("reason") == "no-window":
            return {
                "ok": False,
                "reason": f"전자세금계산서 팝업을 찾지 못했습니다(열린 창: {r.get('titles')}).",
            }
        buttons = r.get("buttons")
    return {
        "ok": False,
        "reason": f"전자세금계산서 팝업의 '조회' 버튼을 찾지 못했습니다(팝업 버튼: {buttons}).",
    }


def _popup_diag(state: dict) -> str:
    """실패 사유에 붙일 진단 꼬리표 — 보이는 창 제목 + 팝업 버튼 라벨 + 그리드별 행수."""
    titles = state.get("titles") or []
    buttons = [str(b.get("text") or "") for b in (state.get("buttons") or [])]
    grids = [g.get("err") or g.get("n") for g in (state.get("grids") or []) if isinstance(g, dict)]
    tail = f"열린 창: {titles}"
    if buttons:
        tail += f" · 팝업 '{state.get('title')}' 버튼: {buttons}"
    if grids:
        tail += f" · 그리드 {len(grids)}개 행수: {grids}"
    return tail


async def open_invoice_list(page: Any, period_from: str, period_to: str) -> dict:
    """조회(F2) → 게이트 다이얼로그 "예" → 전자세금계산서 팝업 → 기간 세팅 → 재조회 → 행 덤프.

    반환 {ok, title, rows}|{ok:False, reason}. ⚠ 발행 후 실데이터 검증 미완(테스트 환경 0건 —
    PROCESS.md D5 리스크): 팝업 도달·구조까지는 프로브 검증, 행 적용은 사용자 감독 검증 대기.
    """
    # ⚠ 화면 전체의 조회(F2)는 **누르지 않는다**(사용자 교정 2026-08-20) — 계산서 리스트
    # 모달은 **증빙유형 적용 시점에** 열리고, 눌러야 할 조회는 그 **모달 안의 버튼**이다.
    # F2 를 누르면 '저장하지 않은 데이터…' 확인창 등 엉뚱한 다이얼로그 체인이 시작된다.
    state = await wait_invoice_popup_ready(page, limit=10, cap_ms=INVOICE_POPUP_CAP_MS)
    if not state.get("ok"):
        return {
            "ok": False,
            "reason": f"증빙 적용 후 계산서 모달이 열리지 않았습니다({_popup_diag(state)}).",
        }
    if best_invoice_grid(state) is None:
        return {
            "ok": False,
            "reason": (
                "계산서 모달 그리드가 초기화되지 않았습니다"
                f"(dewsControl 미바인딩, {_popup_diag(state)})."
            ),
        }
    set_r = await page.evaluate(js.SET_INVOICE_PERIOD_JS, {"from": period_from, "to": period_to})
    if not (set_r.get("start") and set_r.get("end")):
        return {"ok": False, "reason": f"조회기간 입력을 찾지 못했습니다(period_startinput/endinput): {set_r}"}
    # 조회 실행 → 결과 도착까지 대기. 0행이면 **한 번 더 조회**한다 — 정착 대기를 넣어도 첫
    # 클릭이 삼켜질 여지가 남아 있고(실런 실패의 유력 원인), 재조회는 읽기 전용이라 안전하다.
    result: dict = {}
    attempts = 0
    for _ in range(INVOICE_QUERY_ATTEMPTS):
        attempts += 1
        clicked = await run_invoice_query(page)
        if not clicked.get("ok"):
            return clicked
        result = await wait_invoice_rows_settled(page, limit=100)
        if not result.get("ok"):
            return result
        if result.get("n"):
            break
    return {
        "ok": True,
        "title": result.get("title"),
        "rows": result.get("rows") or [],
        "settled": result.get("settled"),
        "attempts": attempts,
    }


async def apply_invoice_rows(page: Any, indexes: list[int]) -> dict:
    """전자세금계산서 팝업에서 indexes 행을 선택하고 '적용' → 팝업 닫힘 확인.

    ⚠ 복수 선택은 실물 미검증(❓ PROCESS.md D5) — 순차 선택으로 시도하고, 닫힘 실패는 하드
    실패로 끊는다(잔존 팝업은 F7 을 삼켜 팬텀 저장을 유발).
    """
    for i in indexes:
        sel = await page.evaluate(js_lib.PICKER_SELECT_JS, i)
        if not sel.get("ok"):
            return await _fail_close(page, f"계산서 {i + 1}행 선택 실패: {sel}")
        await page.wait_for_timeout(300)
    apply_box = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
    if not apply_box:
        return await _fail_close(page, "계산서 팝업 '적용' 버튼을 찾지 못했습니다.")
    before = await _popup_count(page)
    await mouse_click(page, apply_box["x"], apply_box["y"])
    await _answer_modals(page, ("예", "확인"))
    closed = await verify.confirm_popup_count(page, less_than=before, timing=verify.HEAVY)
    if not closed:
        return {"ok": False, "reason": f"계산서 적용 후 팝업이 닫히지 않았습니다 — {closed.reason}"}
    return {"ok": True, "applied": len(indexes)}


# ══════════════════════════════════════════════════════════════════════════════
# 비용분할(분할처리 팝업 — PROCESS.md 확정 레시피)
# ══════════════════════════════════════════════════════════════════════════════
async def open_split_popup(page: Any) -> dict:
    """'비용분할' 클릭 → 분할처리 팝업 출현 확인. 무반응이면 검증 토스트를 사유에 싣는다.

    전제조건(실측): 거래처·예산단위·공급가액·프로젝트가 채워져 있어야 열린다.
    """
    btns = await page.evaluate(js.BUTTON_BY_TEXT_JS, "비용분할")
    if not btns or btns[0].get("disabled"):
        return {"ok": False, "reason": f"'비용분할' 버튼 없음/비활성: {btns}"}
    await mouse_click(page, btns[0]["x"], btns[0]["y"])
    if await _wait_popup_titled(page, (SPLIT_POPUP_TITLE,), cap_ms=6_000):
        return {"ok": True}
    toasts = await page.evaluate(js_lib.VALIDATION_TOAST_JS)
    detail = f" — ERP 검증: {' / '.join(toasts)}" if toasts else ""
    return {"ok": False, "reason": f"분할처리 팝업이 열리지 않았습니다{detail}", "toasts": toasts or []}


async def dump_split_rows(page: Any) -> list[dict]:
    dump = await _dump_popup_grid(page, 30)
    return (dump.get("grid") or {}).get("rows") or []


async def add_split_row(page: Any) -> dict:
    """분할처리 팝업 '추가' — 확인 모달 처리 + **행수 증가**로 성공 판정(3회 재시도, 프로브 실측)."""
    for _retry in range(3):
        add_btn = await page.evaluate(js.BUTTON_BY_TEXT_JS, "추가")
        if not add_btn:
            return {"ok": False, "reason": "분할처리 팝업 '추가' 버튼을 찾지 못했습니다."}
        before = await page.evaluate(js.DIST_ROWCOUNT_JS)
        await mouse_click(page, add_btn[-1]["x"], add_btn[-1]["y"])
        await page.wait_for_timeout(800)
        await _answer_modals(page, ("확인",))
        after = await page.evaluate(js.DIST_ROWCOUNT_JS)
        if isinstance(after, int) and isinstance(before, int) and after > before:
            return {"ok": True, "rows": after}
        await page.wait_for_timeout(500)
    return {"ok": False, "reason": "분할 행 추가 실패(행수 불변 — 3회 소진)."}


async def set_split_note(page: Any, row_index: int, text: str) -> dict:
    """분할 행 적요 — 셀 에디터(_grid_line) 인라인 입력 + Enter 커밋(Escape 는 미커밋 — 실측)."""
    op = await page.evaluate(js.OPEN_DIST_CELL_EDITOR_JS, {"rowIndex": row_index, "fieldName": DIST_NOTE_FIELD})
    if not op.get("ok"):
        return {"ok": False, "reason": f"분할 적요 셀 에디터 오픈 실패: {op.get('reason')}"}
    loc = page.locator(DIST_LINE_INPUT)
    try:
        await loc.wait_for(state="visible", timeout=5_000)
        await loc.click()
        await loc.fill(text)
        await page.keyboard.press("Enter")
    except Exception as exc:  # noqa: BLE001 — locator 실패는 스텝 실패로 승격.
        return {"ok": False, "reason": f"분할 적요 입력 실패: {str(exc)[:200]}"}
    return {"ok": True}


async def set_split_amount(page: Any, row_index: int, amount: int) -> dict:
    """분할 행 금액(SPPRC_AMT2) — 셀 에디터(_grid_number) 실타이핑 + Tab 커밋(프로브 검증)."""
    op = await page.evaluate(js.OPEN_DIST_CELL_EDITOR_JS, {"rowIndex": row_index, "fieldName": DIST_AMOUNT_FIELD})
    if not op.get("ok"):
        return {"ok": False, "reason": f"분할 금액 셀 에디터 오픈 실패: {op.get('reason')}"}
    loc = page.locator(DIST_NUMBER_INPUT)
    try:
        await loc.wait_for(state="visible", timeout=5_000)
        await loc.click()
        await loc.select_text()
        await loc.press_sequentially(str(amount), delay=60)
        await page.keyboard.press("Tab")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"분할 금액 입력 실패: {str(exc)[:200]}"}
    return {"ok": True}


async def select_split_row(page: Any, row_index: int) -> dict:
    """분할 행 실클릭 선택(차액반영 대상 지정 — trusted 클릭만 인식, 프로브 실측)."""
    rect = await page.evaluate(js.DIST_ROW_RECT_JS, row_index)
    if not rect:
        return {"ok": False, "reason": f"분할 {row_index + 1}행 좌표를 찾지 못했습니다."}
    await mouse_click(page, rect["x"], rect["y"])
    await page.wait_for_timeout(400)
    return {"ok": True}


async def apply_balance(page: Any) -> dict:
    """'차액반영' — 잔액을 **새 행**으로 생성(사양). 확인 모달 처리 후 행 덤프 반환."""
    diff_btn = await page.evaluate(js.BUTTON_BY_TEXT_JS, "차액반영")
    if not diff_btn:
        return {"ok": False, "reason": "'차액반영' 버튼을 찾지 못했습니다."}
    await mouse_click(page, diff_btn[-1]["x"], diff_btn[-1]["y"])
    await page.wait_for_timeout(800)
    await _answer_modals(page, ("확인",))
    return {"ok": True, "rows": await dump_split_rows(page)}


async def delete_split_row(page: Any, row_index: int) -> dict:
    """분할 행 삭제 — 체크박스(x+15) 클릭 → '삭제' → 예/확인 → 행수 감소 확인."""
    cb = await page.evaluate(js.DIST_ROW_CHECKBOX_RECT_JS, row_index)
    if not cb:
        return {"ok": False, "reason": f"분할 {row_index + 1}행 체크박스 좌표를 찾지 못했습니다."}
    await mouse_click(page, cb["x"], cb["y"])
    await page.wait_for_timeout(400)
    del_btn = await page.evaluate(js.BUTTON_BY_TEXT_JS, "삭제")
    if not del_btn:
        return {"ok": False, "reason": "분할처리 팝업 '삭제' 버튼을 찾지 못했습니다."}
    before = await page.evaluate(js.DIST_ROWCOUNT_JS)
    await mouse_click(page, del_btn[-1]["x"], del_btn[-1]["y"])
    await page.wait_for_timeout(800)
    await _answer_modals(page, ("예", "확인"))
    after = await page.evaluate(js.DIST_ROWCOUNT_JS)
    if isinstance(after, int) and isinstance(before, int) and after < before:
        return {"ok": True, "rows": after}
    return {"ok": False, "reason": f"분할 행 삭제 미반영(행수 {before}→{after})."}


async def fill_split_picker(page: Any, row_index: int, field: str, label: str, keyword: str, *, wbs_exact: bool = False) -> dict:
    """분할 행 코드피커 필드(CC_NM/PJT_NM) — 에디터+돋보기(재오픈 3회)→검색→선택→적용.

    적용 전 **전 행**에 비용센터·프로젝트를 채워야 '적용'이 닫힌다(실측 — 미채움 6회 전부 무반응).
    프로젝트는 WBS_NO 정확매칭 우선(wbs_exact), 그 외는 텍스트 매칭 → 0행 폴백.
    """
    opened = False
    for _attempt in range(3):
        op = await page.evaluate(js.OPEN_DIST_CELL_EDITOR_JS, {"rowIndex": row_index, "fieldName": field})
        if not op.get("ok"):
            await page.wait_for_timeout(400)
            continue
        mag = None
        for _ in range(10):
            mag = await page.evaluate(js.DIST_EDITOR_MAGNIFIER_JS)
            if mag:
                break
            await page.wait_for_timeout(200)
        if not mag:
            await page.wait_for_timeout(400)
            continue
        before = await _popup_count(page)
        await mouse_click(page, mag["x"], mag["y"])
        opened = bool(await verify.confirm_popup_count(page, more_than=before, timing=verify.ASYNC))
        if opened:
            break
        await page.wait_for_timeout(400)
    if not opened:
        return {"ok": False, "reason": f"{label} 피커 팝업이 열리지 않았습니다(3회 재시도 소진)."}
    await _picker_search(page, keyword)
    dump = await _dump_popup_grid(page, 30)
    rows = (dump.get("grid") or {}).get("rows") or []
    if not rows:
        await page.evaluate(js_lib.PICKER_CLOSE_JS)
        return {"ok": False, "reason": f"{label} 검색결과 0건(keyword={keyword!r})"}
    pick_i: int | None = None
    if wbs_exact:
        pick_i = next((i for i, r in enumerate(rows) if str(r.get("WBS_NO") or "") == keyword), None)
    if pick_i is None:
        pick_i, _row = pick_row_by_text(rows, keyword)
    if pick_i is None:
        if len(rows) == 1:
            pick_i = 0
        else:
            await page.evaluate(js_lib.PICKER_CLOSE_JS)
            return {"ok": False, "reason": f"{label} '{keyword}' 매칭 행 없음(후보 {len(rows)}건)"}
    sel = await page.evaluate(js_lib.PICKER_SELECT_JS, pick_i)
    if not sel.get("ok"):
        return await _fail_close(page, f"{label} 행 선택 실패: {sel}")
    await page.wait_for_timeout(400)
    apply_box = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
    if not apply_box:
        return await _fail_close(page, f"{label} '적용' 버튼을 찾지 못했습니다.")
    before2 = await _popup_count(page)
    await mouse_click(page, apply_box["x"], apply_box["y"])
    closed = await verify.confirm_popup_count(page, less_than=before2, timing=verify.ASYNC)
    if not closed:
        return {"ok": False, "reason": f"{label} 적용 후 피커가 닫히지 않았습니다."}
    return {"ok": True, "picked": rows[pick_i]}


async def confirm_split_apply(page: Any) -> dict:
    """분할 확정 '적용'→예→확인 — **팝업 닫힘(개수 감소) 미확인이면 실패**(비가역 게이트).

    닫힘 후 '진행 상황' 비동기 커밋이 끝날 때까지 대기하고 중립 영역 클릭으로 포커스를
    리셋한다(커밋 미완 F7 = 팬텀 저장 — 쓰기 프로브 최종라운드 실측).
    """
    before = await _popup_count(page)
    apply_btn = await page.evaluate(js.BUTTON_BY_TEXT_JS, "적용")
    if not apply_btn:
        return {"ok": False, "reason": "분할처리 팝업 '적용' 버튼을 찾지 못했습니다."}
    await mouse_click(page, apply_btn[-1]["x"], apply_btn[-1]["y"])
    await page.wait_for_timeout(800)
    await _answer_modals(page, ("예", "확인"))
    closed = await verify.confirm_popup_count(page, less_than=before, timing=verify.HEAVY)
    if not closed:
        return {
            "ok": False,
            "reason": (
                "분할처리 팝업이 '적용' 이후에도 닫히지 않았습니다 — 진행을 중단합니다"
                f"(잔존 팝업은 F7 을 삼켜 팬텀 저장을 유발). {closed.reason}"
            ),
        }
    # 비동기 커밋('진행 상황') 소멸 대기 + 그리드 재계산 여유 + 포커스 리셋.
    for _ in range(20):
        if not await page.evaluate(js.PROGRESS_VISIBLE_JS):
            break
        await page.wait_for_timeout(300)
    await page.wait_for_timeout(1_000)
    neutral = await page.evaluate(js.NEUTRAL_HEADER_BOX_JS)
    if neutral:
        await mouse_click(page, neutral["x"], neutral["y"])
        await page.wait_for_timeout(400)
    return {"ok": True}


async def close_budget_status_popup(page: Any, *, max_rounds: int = 3) -> dict:
    """분할 확정이 추가로 띄우는 '예산현황' 창을 닫는다 — 없으면 no-op.

    분할 '적용'(→예→확인) 이후 예산 배분 검증 창이 남아 F7 사전 게이트(열린 팝업 0)에 걸린다
    (2026-08-19 SPLIT11 스모크 3회 동일 재현, 잔존 타이틀 실측 ['예산현황']). 비분할 경로는
    이 창이 뜨지 않아 첫 스냅샷에서 그대로 통과한다.

    여러 장이 쌓일 수 있어 라운드마다 스냅샷 재독→클릭→닫힘 대기를 반복하고(상한 max_rounds),
    끝까지 남으면 하드 실패 — 잔존 창을 안고 F7 로 가면 팬텀 저장이 된다.
    반환 {ok:True, closed:int} | {ok:False, reason}.
    """

    async def _titles() -> list[str]:
        modals = await page.evaluate(js_lib.MODALS_SNAPSHOT_JS)
        return [str((m or {}).get("title") or "").strip() for m in (modals or [])]

    def _has_budget(titles: list[str]) -> bool:
        return any(BUDGET_STATUS_TITLE in t for t in titles)

    closed = 0
    for _round in range(max_rounds):
        titles = await _titles()
        if not _has_budget(titles):
            return {"ok": True, "closed": closed}
        btn = None
        for label in BUDGET_MODAL_LABELS:
            box = await page.evaluate(js_lib.MODAL_BTN_BOX_JS, label)
            # MODAL_BTN_BOX_JS 는 최상단 모달부터 찾으므로 눌린 창이 예산현황인지 확인한다.
            if box and BUDGET_STATUS_TITLE in str(box.get("title") or ""):
                btn = box
                break
        if not btn:
            return {
                "ok": False,
                "reason": f"'{BUDGET_STATUS_TITLE}' 창의 확인/닫기 버튼을 찾지 못했습니다(잔존: {titles}).",
            }
        await mouse_click(page, btn["x"], btn["y"])
        closed += 1
        # 닫힘까지 실시간 대기(시간축 규율 — wait_for_timeout 은 delay_scale 로 붕괴한다).
        # 최종 판정은 다음 라운드 스냅샷이 한다(창이 여러 장일 수 있다).
        await verify.confirm(
            _titles,
            lambda ts: not _has_budget(ts or []),
            timing=verify.ASYNC,
            what=f"'{BUDGET_STATUS_TITLE}' 창 닫힘",
            expected="닫힘",
        )
    titles = await _titles()
    if _has_budget(titles):
        return {
            "ok": False,
            "reason": (
                f"'{BUDGET_STATUS_TITLE}' 창이 {max_rounds}회 시도 후에도 남아 있습니다"
                f"(잔존: {titles}) — 잔존 창은 F7 을 삼켜 팬텀 저장을 유발합니다."
            ),
        }
    return {"ok": True, "closed": closed}


# ══════════════════════════════════════════════════════════════════════════════
# 자금과목(FUND_CD) — 관리항목 패널(PROCESS.md 검증 체인 4)
# ══════════════════════════════════════════════════════════════════════════════
async def fill_fund_item(page: Any, fund_name: str = DEFAULT_FUND_NAME) -> dict:
    """관리항목 '자금과목' 행 돋보기 → 자금과목(기표) 팝업 → 텍스트 매칭 행 → 적용 → 패널 재독.

    계정의 관리항목 구성에 따라 **필수**다("계정의 관리항목[자금과목] 항목이 입력되지
    않았습니다" 반려 — 2026-08-19 headed 세션). 구성별 편차를 판별할 방법이 없으므로 항상
    채우는 것이 기본. 위젯은 캔버스 셀이 아니라 tb1 DOM 패널이고(FUND_CD 는 대응 NM 컬럼이
    없는 hidden 백킹필드), 팝업 필드명이 미상이라 행은 텍스트 매칭으로 고른다.
    """
    if not await page.evaluate(_ROW_SCROLL_JS, FUND_ITEM_LABEL):
        return {
            "ok": False,
            "reason": "관리항목 패널에 '자금과목' 행이 없습니다(예산계정 미선택 또는 항목 구성 상이).",
        }
    await page.wait_for_timeout(200)
    box = await page.evaluate(_ROW_BUTTON_JS, FUND_ITEM_LABEL)
    if not box:
        return {"ok": False, "reason": "자금과목 행의 코드피커 버튼을 찾지 못했습니다."}
    before = await _popup_count(page)
    await mouse_click(page, box["x"], box["y"])
    opened = await verify.confirm_popup_count(page, more_than=before, timing=verify.ASYNC)
    if not opened:
        return {"ok": False, "reason": f"자금과목(기표) 팝업이 열리지 않았습니다 — {opened.reason}"}
    await _picker_search(page, fund_name)
    dump = await _dump_popup_grid(page, 30)
    rows = (dump.get("grid") or {}).get("rows") or []
    pick_i, _row = pick_row_by_text(rows, fund_name)
    if pick_i is None:
        if len(rows) == 1:  # 검색이 단건으로 좁혀진 경우 폴백.
            pick_i = 0
        else:
            return await _fail_close(page, f"자금과목 '{fund_name}' 매칭 행 없음(후보 {len(rows)}건)")
    sel = await page.evaluate(js_lib.PICKER_SELECT_JS, pick_i)
    if not sel.get("ok"):
        return await _fail_close(page, f"자금과목 행 선택 실패: {sel}")
    await page.wait_for_timeout(400)
    apply_box = await page.evaluate(js_lib.PICKER_APPLY_BTN_JS)
    if not apply_box:
        return await _fail_close(page, "자금과목 '적용' 버튼을 찾지 못했습니다.")
    before2 = await _popup_count(page)
    await mouse_click(page, apply_box["x"], apply_box["y"])
    await _answer_modals(page, ("확인",))  # 적용 후 안내 모달 — 닫힘 판정 전에 처리(프로브 관례).
    closed = await verify.confirm_popup_count(page, less_than=before2, timing=verify.ASYNC)
    if not closed:
        return {"ok": False, "reason": f"자금과목 적용 후 팝업이 닫히지 않았습니다 — {closed.reason}"}
    # 세팅→독립확인: 패널 행을 재독해 값이 실제로 붙었는지 본다(빈 값이면 저장 반려로 이어진다).
    await page.evaluate(_ROW_SCROLL_JS, FUND_ITEM_LABEL)
    await page.wait_for_timeout(200)
    readback = await page.evaluate(_ROW_VALUES_JS, FUND_ITEM_LABEL) or {}
    if not (readback.get("found") and (readback.get("code") or readback.get("name"))):
        return {"ok": False, "reason": f"자금과목 적용 후 패널 값이 비어 있습니다 — {readback}"}
    return {"ok": True, "code": readback.get("code"), "name": readback.get("name")}
