"""테스트 문서 정리(cleanup) 워크플로우 — 결의서입력(GLDDOC00300) 문서 일괄 삭제(F6).

디버그 편의 기능(사용자 요청 2026-08-10): 에이전트를 디버깅하며 만든 결의서를 지워 반복
테스트를 원활하게 한다. e2e 스모크의 실측 삭제 경로(`e2e/product_cycle.py::erp_verify_and_delete`,
10회 사이클 그린)를 프로덕션 그래프로 이식했다 — 조회(F2) → **3중 가드 전 행 검증** →
전체 선택 → F6+확인 모달 → 재조회 잔존 0 확인.

⚠⚠ 절대 안전(스모크 가드레일 + HITL 선택, 2026-08-10 사용자 확정) ⚠⚠
  - 3중 가드를 **모든 행**이 통과할 때만 진행한다: 결의자(WRT_EMP_NM) = 로그인 계정
    ∧ 결의구분 코드(ABDOCU_FG_CD) 일치 ∧ 미결(DOCU_NO 공백 — 상신/확정 문서 보호).
    한 행이라도 어긋나면 **아무것도 지우지 않고** 중단한다.
  - 가드는 "본인의 미결 문서"까지만 식별한다 — **에이전트가 만든 문서인지는 ERP 로 구분
    불가**(사용자 지적 2026-08-10: 수작업 미결 문서가 섞일 수 있다). 그래서 자동 전량 삭제
    대신 **HITL(multiselect) 개입으로 대상 목록을 제시하고, 사용자가 체크한 문서만** 지운다.
    선택 0건이면 아무것도 지우지 않는다.
  - 삭제(F6)는 비가역 — hidden 워크플로우라 실행 경로는 관리자 + 프론트 디버그 모드
    버튼뿐이다(`agent_visibility.HIDDEN_AGENT_IDS`).
  - 날짜 조건은 쓰지 않는다(그리드 UTC/회계일 편차로 신뢰 불가 — 2026-07-04 실측) —
    신원(결의자·결의구분·미결)으로만 판정한다.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, StateGraph

from app.agents.card_collect import js as cc_js  # MODALS_SNAPSHOT_JS / MODAL_BTN_BOX_JS
from app.agents.common.nodes import (
    make_login_node,
    make_menu_nav_node,
    make_set_gubun_node,
    make_user_type_node,
)
from app.agents.common.state import BaseAgentState
from app.agents.voucher_receivable.steps import (  # F2 확정 규율 + 전체해제 재사용
    run_query,
    uncheck_all_rows,
)
from app.live.events import emit_log, emit_step
from app.live.hitl import wait_hitl
from nbkit.omnisol import selectors, verify
from nbkit.patterns import emit_shot

logger = logging.getLogger(__name__)

RECURSION_LIMIT = 10

# 마스터 그리드 전 행에서 가드 판정에 필요한 필드만 덤프(e2e MASTER_DUMP_JS 축약 이식).
MASTER_DUMP_JS = """(index) => {
  try {
    const g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[index || 0])
      .data('dewsControl')._grid;
    const ds = g.getDataSource();
    const n = ds.getRowCount();
    const rows = n > 0 ? ds.getJsonRows(0, n - 1) : [];
    const s = v => (v == null ? '' : String(v));
    return { ok: true, n, rows: rows.map(r => ({
      ABDOCU_NO: s(r.ABDOCU_NO), ABDOCU_FG_CD: s(r.ABDOCU_FG_CD),
      WRT_EMP_NM: s(r.WRT_EMP_NM), DOCU_NO: s(r.DOCU_NO),
      DETAIL_SUM_AMT: s(r.DETAIL_SUM_AMT) })) };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 160) }; }
}"""

# 행 체크 + 반영 독립확인(결의서입력 실측 2026-08-10). voucher CHECK_ROW_JS 는 setCurrent 에
# 컬럼 fieldName(getColumns()[1])을 함께 넘기는데, 이 화면에선 그 호출이 실패했다(라이브 회귀:
# "1행 선택(checkRow) 실패"). 이 화면에서 실측 확정된 형태는 **itemIndex 단독 setCurrent**
# (e2e SELECT_MASTER_JS)다. checkRow→checkItem 순으로 시도하고, getCheckedRows 재독으로
# **실제 반영을 확인**해서만 ok 를 돌려준다(세팅→독립확인 규율). 실패 시 원인 목록(err) 동봉.
CHECK_ROW_VERIFIED_JS = """(idx) => {
  const short = e => String(e).slice(0, 100);
  const out = { ok: false, via: [], err: [], checked: null };
  let g;
  try {
    g = window.jQuery(document.querySelectorAll('.dews-ui-grid')[0]).data('dewsControl')._grid;
  } catch (e) { out.err.push('grid:' + short(e)); return out; }
  try { g.setCurrent({ itemIndex: idx }); out.via.push('setCurrent'); }
  catch (e) { out.err.push('setCurrent:' + short(e)); }
  let done = false;
  try {
    if (typeof g.checkRow === 'function') { g.checkRow(idx, true); done = true; out.via.push('checkRow'); }
  } catch (e) { out.err.push('checkRow:' + short(e)); }
  if (!done) {
    try {
      if (typeof g.checkItem === 'function') { g.checkItem(idx, true); done = true; out.via.push('checkItem'); }
    } catch (e) { out.err.push('checkItem:' + short(e)); }
  }
  try {
    const raw = g.getCheckedRows ? (g.getCheckedRows() || []) : [];
    const idxs = raw.map(r => (typeof r === 'number' ? r : ((r && (r.itemIndex ?? r.dataRow)) ?? -1)));
    out.checked = idxs;
    out.ok = idxs.indexOf(idx) >= 0;
  } catch (e) { out.err.push('verify:' + short(e)); out.ok = done; }
  return out;
}"""


async def _check_row(page: Any, idx: int) -> dict:
    """idx 행 체크 + 반영 확인. 미반영이면 1회 재시도(체크 직후 빈 배열 과도상태 실측 대비)."""
    for attempt in range(2):
        try:
            r = await page.evaluate(CHECK_ROW_VERIFIED_JS, idx)
        except Exception as exc:  # noqa: BLE001 — 평가 실패도 진단 가능한 형태로.
            r = {"ok": False, "err": [str(exc)[:120]]}
        if isinstance(r, dict) and r.get("ok"):
            return r
        if attempt == 0:
            await verify.DEFAULT_SLEEP(0.5)  # 지연 재렌더 정착 대기(실시간).
    return r if isinstance(r, dict) else {"ok": False, "err": ["non-dict"]}


# 버튼 중심좌표(e2e BTN_BOX_JS 이식) — 미발견이면 null(호출부가 F6 키로 폴백).
BTN_BOX_JS = """(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (!r.width || !r.height) return null;
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
}"""


def row_is_ours(row: dict, fg_code: str, userid: str) -> bool:
    """3중 가드(스모크 `row_is_ours` 이식) — 결의자=로그인 계정 ∧ 결의구분 일치 ∧ 미결."""
    writer = str(row.get("WRT_EMP_NM") or "").strip()
    fg = str(row.get("ABDOCU_FG_CD") or "").strip()
    docu_no = str(row.get("DOCU_NO") or "").strip()
    return writer == userid.strip() and fg == str(fg_code) and not docu_no


async def _delete_selected(page: Any) -> None:
    """F6(삭제) 실클릭 + 확인 모달 처리(e2e delete_selected 이식, 실시간 대기 규율)."""
    box = await page.evaluate(BTN_BOX_JS, selectors.BTN_DELETE)
    if box:
        await page.mouse.click(box["x"], box["y"])
    else:
        await page.keyboard.press("F6")
    for _ in range(8):
        await verify.DEFAULT_SLEEP(1.2)  # 시간축 규율 — 모달 관찰은 실시간.
        modals = await page.evaluate(cc_js.MODALS_SNAPSHOT_JS)
        if not modals:
            break
        clicked = False
        for label in ("예", "확인", "삭제"):
            btn = await page.evaluate(cc_js.MODAL_BTN_BOX_JS, label)
            if btn:
                await page.mouse.click(btn["x"], btn["y"])
                clicked = True
                break
        if not clicked:
            break


class DocCleanupState(BaseAgentState, total=False):
    """러너 주입 공통 키 상속 + cleanup 산출 키 선언(LangGraph 미선언 키 silent drop)."""

    deleted: int  # cleanup_docs — 삭제한 문서 수


def make_cleanup_docs_node(fg_code: str, doc_label: str):
    """조회(F2) → 전 행 3중 가드 → 전체 선택 → F6 삭제 → 재조회 잔존 0 확인."""

    async def cleanup_docs(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, "cleanup_docs", "running")

        userid = str(state.get("userid") or "").strip()
        if not userid:
            await emit_step(events, "cleanup_docs", "failed")
            return {"error": "로그인 계정을 확인할 수 없어 정리를 중단합니다(가드레일 판정 불가)."}

        rq = await run_query(page)
        if not (isinstance(rq, dict) and rq.get("ok")):
            await emit_step(events, "cleanup_docs", "failed")
            return {"error": f"조회(F2) 실패 — 정리를 진행할 수 없습니다: {rq}"}
        n = int(rq.get("rowcount") or 0)
        if n <= 0:
            await emit_log(events, f"{doc_label} 문서가 없습니다(조회 0건) — 정리할 것이 없습니다.", "info")
            await emit_step(events, "cleanup_docs", "done")
            return {"deleted": 0, "result": f"정리 완료 — {doc_label} 문서가 없습니다(조회 0건)."}

        dump = await page.evaluate(MASTER_DUMP_JS, 0)
        if not (isinstance(dump, dict) and dump.get("ok")):
            await emit_step(events, "cleanup_docs", "failed")
            return {"error": f"조회 결과를 읽지 못했습니다 — 정리 중단: {dump}"}
        rows = dump.get("rows") or []

        bad = [r for r in rows if not row_is_ours(r, fg_code, userid)]
        if bad:
            sample = ", ".join(
                f"{r.get('ABDOCU_NO') or '(번호미상)'}({r.get('WRT_EMP_NM') or '?'}"
                f"{'·상신됨' if str(r.get('DOCU_NO') or '').strip() else ''})"
                for r in bad[:3]
            )
            more = "…" if len(bad) > 3 else ""
            await emit_step(events, "cleanup_docs", "failed")
            return {
                "error": (
                    f"가드레일 불일치 — 본인 작성·{doc_label}·미결이 아닌 행 {len(bad)}건"
                    f"({sample}{more}). 아무것도 삭제하지 않았습니다."
                )
            }

        abdocu_nos = [r.get("ABDOCU_NO") or "(번호미상)" for r in rows]
        await emit_log(
            events,
            f"후보 {n}건 — 전 행 가드 통과(본인 작성·{doc_label}·미결). "
            "삭제할 문서를 선택하는 개입을 띄웁니다.",
            "action",
        )

        # ── HITL(multiselect): 사용자가 체크한 문서만 삭제(사용자 확정 2026-08-10) ──
        # 가드는 '본인 미결'까지만 식별한다 — 수작업 문서가 섞일 수 있어 최종 필터는 사람이다.
        options = [
            {
                "value": str(i),
                "label": abdocu_nos[i],
                "description": f"금액 {r.get('DETAIL_SUM_AMT') or '?'} · 작성자 {r.get('WRT_EMP_NM')}",
            }
            for i, r in enumerate(rows)
        ]
        try:
            resp = await wait_hitl(
                events,
                kind="multiselect",
                title=f"{doc_label} 테스트 문서 정리",
                prompt=(
                    f"본인 작성·미결 {doc_label} 문서 {n}건입니다. 삭제(F6)할 문서만 체크하세요 — "
                    "직접 작성한 실문서가 섞여 있을 수 있습니다. 체크하지 않은 문서는 남습니다."
                ),
                options=options,
                owner=state.get("owner"),
                run_id=state.get("run_id"),
            )
        except TimeoutError:
            await emit_step(events, "cleanup_docs", "failed")
            return {"error": "삭제 선택 응답 시간 초과 — 아무것도 삭제하지 않았습니다."}

        values = resp.get("values") if isinstance(resp, dict) else None
        picked = sorted(
            {int(v) for v in (values or []) if str(v).isdigit() and 0 <= int(v) < n}
        )
        if not picked:
            await emit_log(events, "선택 없음 — 아무것도 삭제하지 않고 종료합니다.", "info")
            await emit_step(events, "cleanup_docs", "done")
            return {"deleted": 0, "result": "정리 완료 — 선택한 문서가 없어 아무것도 삭제하지 않았습니다."}

        picked_nos = [abdocu_nos[i] for i in picked]
        head = ", ".join(picked_nos[:5]) + ("…" if len(picked_nos) > 5 else "")
        await emit_log(events, f"선택 {len(picked)}건 삭제 진행 — 전표: {head}", "action")

        # 선택 행만 체크(D4: checkRow 없이는 F6 이 대상을 못 잡는다) — 전체 해제 후 재체크.
        if not await uncheck_all_rows(page):
            await uncheck_all_rows(page)
        for i in picked:
            chk = await _check_row(page, i)
            if not chk.get("ok"):
                await emit_step(events, "cleanup_docs", "failed")
                detail = "; ".join(chk.get("err") or []) or str(chk)[:120]
                return {
                    "error": (
                        f"{i + 1}행 선택(checkRow) 실패({detail}) — 아무것도 삭제하지 않았습니다."
                    )
                }

        await _delete_selected(page)

        expected_left = n - len(picked)
        rq2 = await run_query(page, expected=expected_left)
        # ⚠ `or -1` 금지 — 잔존 0건(falsy)이 미상(-1)으로 둔갑한다.
        raw_after = rq2.get("rowcount") if (isinstance(rq2, dict) and rq2.get("ok")) else None
        after = raw_after if isinstance(raw_after, int) else -1
        await emit_shot(events.put, page)
        if after != expected_left:
            await emit_step(events, "cleanup_docs", "failed")
            return {
                "error": (
                    f"삭제 후 잔존 {after if after >= 0 else '미상'}건(기대 {expected_left}건) — "
                    f"수동 확인이 필요합니다(선택했던 전표: {head})."
                )
            }

        await emit_log(events, f"정리 완료 — 선택 {len(picked)}건 삭제, 잔존 {after}건(기대 일치) ✅", "ok")
        await emit_step(events, "cleanup_docs", "done")
        return {
            "deleted": len(picked),
            "result": (
                f"정리 완료 — {doc_label} 문서 {len(picked)}건 삭제"
                f"(후보 {n}건 중 선택분만, 잔존 {after}건 확인). 전표: {head}"
            ),
        }

    return cleanup_docs


def build_doc_cleanup_graph(gubun_label: str, fg_code: str):
    """결의서입력 진입 공유 체인 + cleanup_docs 를 조립해 컴파일(문서종류별 인스턴스화).

    체인: login → user_type(회계) → menu_nav(결의서입력) → set_gubun(gubun_label)
          → cleanup_docs → END. add_row(F3)는 **넣지 않는다**(새 문서 생성 금지).
    """
    g = StateGraph(DocCleanupState)
    g.add_node("login", make_login_node())
    g.add_node("user_type", make_user_type_node("회계"))
    g.add_node("menu_nav", make_menu_nav_node())  # 결의서입력(EXPENSE_CARD)
    g.add_node("set_gubun", make_set_gubun_node(gubun_label))
    g.add_node("cleanup_docs", make_cleanup_docs_node(fg_code, gubun_label))

    g.set_entry_point("login")
    for a, b in (
        ("login", "user_type"),
        ("user_type", "menu_nav"),
        ("menu_nav", "set_gubun"),
        ("set_gubun", "cleanup_docs"),
        ("cleanup_docs", END),
    ):
        g.add_edge(a, b)
    return g.compile().with_config({"recursion_limit": RECURSION_LIMIT})
