"""법인카드 승인내역 정리(card-collect) — 카드팝업 이후 노드(진입 앞단은 expense_card 재사용).

체인: (login→user_type→menu_nav→set_gubun→add_row→open_evdn→select_evdn = expense_card 재사용)
→ select_all_cards → set_period(D2) → query(리스트 조회·표 보고) → collect_rows(그리드 HITL 로
행별 예산단위·프로젝트·적요 일괄 입력) → save(최종 HITL 확인 후에만 F7).

state 계약: page/browser/events/userid/password/params(러너 주입). 실패는 {"error"} 로 남긴다.
⚠ 저장(F7)은 collect 완료 후 사용자가 HITL 로 '저장'을 택했을 때만. 그 외 저장 절대 금지.

collect_rows 는 kind="grid" HITL 프레임을 방출한다 — 프론트가 행 그리드 + 예산단위/프로젝트
피커 UI 를 그리고, 사용자가 값을 채워 한 번에 제출(`rows`)하거나 프로젝트 검색(`query`)을 보낸다.
Gemini 대화 루프는 제거됐다(그리드 채널로 대체).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import date
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.db import get_sessionmaker
from app.live.events import emit_chat, emit_hitl, emit_log, emit_step, emit_transactions
from app.live.hitl import close_hitl_channel, open_hitl_channel, wait_hitl
from app.models import User, UserCodeFavorite
from app.services.code_sync import dept_matches_budget_name
from nbkit.patterns import emit_shot

from . import steps

logger = logging.getLogger("app.agents.card_collect.nodes")

# 그리드 프레임 크기 가드(프론트 페이로드 비대 방지).
_MAX_BUDGET_UNITS = 200
_MAX_PROJECT_RESULTS = 25
_MAX_FAVORITES = 100

# 코드피커 필드 스펙: 폼 id → (팝업 code 컬럼, name 컬럼). probe5~8 실측.
# ⚠ 순서 의존: 계정(acct_cd)은 예산단위 선택 후에야 목록이 채워진다(예산계정 연동). → 반드시
#   예산단위 → 계정 → 프로젝트 순서로 채운다(_apply_row_fields 의 튜플 순서 유지).
FIELD_SPEC: dict[str, dict[str, str]] = {
    "예산단위": {"id": "bg_cd", "code": "BG_CD", "name": "BG_NM"},
    "계정": {"id": "acct_cd", "code": "ACCT_CD", "name": "ACCT_NM"},
    "프로젝트": {"id": "pjt_cd", "code": "PJT_NO", "name": "PJT_NM"},
}


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _fmt_won(v: Any) -> str:
    if v is None or str(v).strip() == "":
        return "-"  # 그리드에 값이 없는 컬럼(예: 부가세 미제공 행)은 'None원' 대신 '-'.
    try:
        return f"{int(str(v).replace(',', '')):,}원"
    except (ValueError, TypeError):
        return f"{v}원"


def recommend_note(tran_nm: str, amount: str) -> str:
    """가맹점명 기반 적요 초안 추천(휴리스틱 v1, 추후 Gemini 로 고도화)."""
    nm = tran_nm or ""
    rules = [
        (("식", "푸드", "요기요", "배달", "김밥", "곱창", "고기"), "식대(법인카드)"),
        (("주차", "파킹"), "주차료(법인카드)"),
        (("택시", "카카오T", "코레일", "고속", "항공", "대한항공", "아시아나"), "교통비(법인카드)"),
        (("주유", "에너지", "오일", "GS칼텍스", "SK에너지"), "차량 주유비(법인카드)"),
        (("네이버", "쿠팡", "11번가", "G마켓", "다이소", "코스트코", "이마트"), "소모품 구입(법인카드)"),
    ]
    for keys, note in rules:
        if any(k in nm for k in keys):
            return note
    return f"{nm} 사용" if nm else "법인카드 사용"


# ── 카드 전체선택 ────────────────────────────────────────────────────────────────
def make_select_all_cards_node():
    async def select_all_cards(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, "select_all_cards", "running")
        t0 = time.monotonic()
        r = await steps.select_all_cards(page)
        if not r.get("ok"):
            await emit_step(events, "select_all_cards", "failed")
            return {"error": f"카드 전체선택 실패: {r.get('reason')}"}
        await emit_log(events, f"법인카드 {r.get('n')}장 전체선택·적용 완료.", "ok")
        await emit_shot(events.put, page)
        await emit_step(events, "select_all_cards", "done", _ms(t0))
        return {}

    return select_all_cards


# ── 승인일 기간(D2) ──────────────────────────────────────────────────────────────
def make_set_period_node():
    async def set_period(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, "set_period", "running")
        t0 = time.monotonic()
        params = state.get("params") or {}
        # 테스트/재현용 override 가능(params['today']=YYYY-MM-DD), 없거나 형식오류면 실제 오늘(리뷰 #12).
        today = date.today()
        raw_today = params.get("today")
        if raw_today:
            try:
                today = date.fromisoformat(str(raw_today))
            except (ValueError, TypeError):
                await emit_log(events, f"params.today 형식 오류({raw_today!r}) — 오늘 날짜로 진행.", "warn")
        start, end = steps.compute_period(today)
        r = await steps.set_period(page, start, end)
        if not r.get("ok"):
            await emit_step(events, "set_period", "failed")
            return {"error": f"승인일 기간 설정 실패({start}~{end}): {r}"}
        rule = "전월" if today.day < steps.DAY_CUTOFF else "당월"
        await emit_log(events, f"승인일 기간 = {start} ~ {end} ({rule} 규칙).", "info")
        await emit_step(events, "set_period", "done", _ms(t0))
        return {"period": [start, end]}

    return set_period


# ── 조회 + 리스트 표 보고 ─────────────────────────────────────────────────────────
def make_query_node():
    async def query(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, "query", "running")
        t0 = time.monotonic()
        rows = await steps.run_query(page)
        if not isinstance(rows, int) or rows < 0:
            await emit_step(events, "query", "failed")
            return {"error": "조회에 실패했습니다(그리드 로딩 실패)."}
        lst = await steps.read_rows(page, limit=500)
        # 리스트 표 보고(승인일/가맹점명/승인액/부가세구분).
        columns = [
            {"key": "d", "header": "승인일"},
            {"key": "m", "header": "가맹점명"},
            {"key": "a", "header": "승인액", "align": "right"},
            {"key": "v", "header": "부가세구분"},
        ]
        table_rows = [
            {
                "d": r.get("TRAN_DT") or "",
                "m": r.get("TRAN_NM") or "",
                "a": _fmt_won(r.get("TRAN_AMT")),
                "v": r.get("VAT_TP") or "-",
            }
            for r in lst
        ]
        await emit_transactions(events, title=f"법인카드 승인내역 {rows}건", columns=columns, rows=table_rows)
        await emit_log(events, f"조회 완료 — 승인내역 {rows}건.", "ok")
        await emit_shot(events.put, page)
        await emit_step(events, "query", "done", _ms(t0))
        return {"rows_list": lst}

    return query


# ── 리스트 표 / 항목 지정 파서 ─────────────────────────────────────────────────
def _md_cell(v: object) -> str:
    """마크다운 표 셀 안전화(파이프·개행 제거)."""
    return str(v or "").replace("|", "/").replace("\n", " ").strip()


_STATUS_MARK = {"done": "✅ 반영", "skipped": "⏭️ 건너뜀", "failed": "❌ 실패", "pending": "· 대기"}


def _status_table(rows: list[dict], status: dict[int, str], notes: dict[int, str]) -> str:
    """처리 현황 마크다운 표(# · 가맹점명 · 승인액 · 적요 · 상태)."""
    head = "| # | 가맹점명 | 승인액 | 적요 | 상태 |\n|---:|---|---:|---|---|"
    lines = [head]
    for r in rows:
        i = r.get("i", 0)
        lines.append(
            f"| {i + 1} | {_md_cell(r.get('TRAN_NM'))} | {_md_cell(_fmt_won(r.get('TRAN_AMT')))} "
            f"| {_md_cell(notes.get(i, ''))} | {_STATUS_MARK.get(status.get(i, 'pending'))} |"
        )
    return "\n".join(lines)


async def _load_user_favorites(owner: str | None) -> tuple[list[dict], list[dict], str | None]:
    """사용자 즐겨찾기(예산단위/프로젝트) + 소속부서를 DB 에서 로드. owner=None(스크립트) → 빈 값.

    반환 (budget_favs [{code,name}], project_favs [{code,name}], department) — sort_order 순.
    department 는 '내 부서' 예산단위 그룹(이름 정규화 매칭)에 쓴다.
    라우터 밖(세션 펌프)이므로 store.py 처럼 get_sessionmaker() 로 자체 세션을 연다.
    """
    if not owner:
        return [], [], None
    try:
        user_id = uuid.UUID(str(owner))
    except (ValueError, TypeError):
        return [], [], None
    async with get_sessionmaker()() as s:
        rows = (
            await s.execute(
                select(UserCodeFavorite)
                .where(UserCodeFavorite.user_id == user_id)
                .order_by(UserCodeFavorite.sort_order)
            )
        ).scalars().all()
        department = (
            await s.execute(select(User.department).where(User.id == user_id))
        ).scalar()
    budget_favs: list[dict] = []
    project_favs: list[dict] = []
    for f in rows:
        if f.kind == "budget_unit":
            budget_favs.append({"code": f.code, "name": f.name})
        elif f.kind == "project":
            project_favs.append({"code": f.code, "name": f.name})
    return budget_favs, project_favs, department


def _validate_grid_submit(rows_in: list[dict], n: int) -> tuple[bool, str]:
    """제출 rows 서버검증. 비스킵 행은 예산단위(code·name)·적요 필수, 행번호는 1..n.

    행 집합은 정확히 {1..n}(중복·누락 불허) — 부분 제출을 허용하면 빠진 행이 조용히 pending
    으로 남고, 중복 no 는 같은 ERP 행을 이중 반영한다(리뷰 MEDIUM #3). (ok, reason) 반환.
    """
    seen: set[int] = set()
    for row in rows_in:
        no = row.get("no")
        if not isinstance(no, int) or not (1 <= no <= n):
            return False, f"행 번호가 올바르지 않습니다: {no!r}"
        if no in seen:
            return False, f"행 번호가 중복됐습니다: {no}"
        seen.add(no)
        if row.get("skip"):
            continue
        bu = row.get("budgetUnit") or {}
        if not (bu.get("code") and bu.get("name")):
            return False, f"{no}행 예산단위를 선택해 주세요."
        if not (row.get("note") or "").strip():
            return False, f"{no}행 적요를 입력해 주세요."
    if len(seen) != n:
        missing = sorted(set(range(1, n + 1)) - seen)[:5]
        return False, f"모든 행이 포함돼야 합니다(누락: {missing} …)."
    return True, ""


# ── 항목 처리(그리드 HITL): 행 그리드 방출 → 일괄 제출(rows) 을 순차 반영 ──────────────
def make_collect_rows_node(timeout_s: int | None = None):
    async def collect_rows(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        rows_list: list[dict] = state.get("rows_list") or []
        await emit_step(events, "collect_rows", "running")
        if not rows_list:
            period = state.get("period") or []
            period_txt = f"{period[0]} ~ {period[1]}" if len(period) == 2 else "이번 조회 기간"
            # 조회는 정상 실행됐지만 결과가 0건인 경우 — 채팅에 명확히 알린다(조용히 끝나면
            # 사용자가 '먹통'으로 오해하기 쉽다). 로그 탭 warn 만으론 부족(리뷰).
            await emit_chat(
                events,
                chat_id="cc-empty",
                role="assistant",
                content=f"{period_txt} 기간에 해당하는 법인카드 승인내역이 0건입니다. 처리할 항목이 없어 이대로 종료합니다.",
                streaming=False,
            )
            await emit_log(events, "처리할 승인내역이 없습니다.", "warn")
            await emit_step(events, "collect_rows", "done")
            return {"filled": 0}

        settings = get_settings()
        wait_timeout = timeout_s if timeout_s is not None else settings.hitl_timeout_s
        n = len(rows_list)

        # 행별 추천 적요(prefill) + 처리 현황(status)·적요(notes) 트래킹. status/notes 는
        # r.get("i", idx)(=행 인덱스, 제출행 no-1 과 동일)를 키로 쓴다(_status_table 과 같은 규칙).
        recs = {r.get("i", idx): recommend_note(r.get("TRAN_NM") or "", r.get("TRAN_AMT") or "")
                for idx, r in enumerate(rows_list)}
        status: dict[int, str] = {r.get("i", idx): "pending" for idx, r in enumerate(rows_list)}
        notes = dict(recs)

        # 그리드 행(프론트 계약: no·card·merchant·amount·date·time·approved·vatType·note).
        grid_rows = [
            {
                "no": idx + 1,
                "card": r.get("FINPRODUCT_NM") or "",
                "merchant": r.get("TRAN_NM") or "",
                "amount": _fmt_won(r.get("TRAN_AMT")),
                "date": r.get("TRAN_DT") or "",
                "time": r.get("TRAN_TM") or "",
                "approved": r.get("APRVL_YN") or "",
                "vatType": r.get("VAT_TP") or "",
                "note": recs[r.get("i", idx)],
            }
            for idx, r in enumerate(rows_list)
        ]

        # 즐겨찾기·부서(DB) + 예산단위 라이브 덤프(ERP). 실패는 경고 후 빈 목록으로 진행(런 유지).
        budget_favs, project_favs, department = await _load_user_favorites(state.get("owner"))
        try:
            all_units = await steps.dump_budget_units(page)
        except Exception:  # noqa: BLE001 — 덤프 실패로 런을 죽이지 않는다.
            logger.exception("card-collect dump_budget_units failed")
            all_units = []
        if not all_units:
            await emit_log(events, "예산단위 목록을 불러오지 못했습니다(즐겨찾기·검색으로 진행).", "warn")

        # '내 부서' = 예산단위명 ↔ 소속부서 정규화 매칭('인사/기획팀' ↔ '인사기획팀').
        mine_units = [u for u in all_units if dept_matches_budget_name(department, u["name"])]
        budget_units = {
            "favorites": budget_favs[:_MAX_FAVORITES],
            "mine": mine_units[:_MAX_BUDGET_UNITS],
            "all": all_units[:_MAX_BUDGET_UNITS],
        }
        project_favs = project_favs[:_MAX_FAVORITES]

        # 지속 HITL 채널: decision_id 1개로 노드 수명 내내 큐를 유지한다(query 재검색·재제출을
        # 같은 채널로 받는다). 소유권·런바인딩은 오픈 시점에 등록해 /runs/hitl 레이스 창을 없앤다.
        decision_id = uuid.uuid4().hex
        q = open_hitl_channel(decision_id, owner=state.get("owner"), run_id=state.get("run_id"))

        async def _emit_frame(search_results: list | None, query: str | None) -> None:
            # 프론트는 run.hitl 을 통째로 교체하므로, 재방출 시 rows/budgetUnits/favorites 를 매번 싣는다.
            await emit_hitl(
                events,
                decision_id=decision_id,
                kind="grid",
                title="승인내역 정리",
                prompt="행별로 예산단위·프로젝트·적요를 입력한 뒤 적용을 누르세요.",
                rows=grid_rows,
                budgetUnits=budget_units,
                projects={"favorites": project_favs, "searchResults": search_results, "query": query},
            )

        last_results: list | None = None  # 마지막 프로젝트 검색 결과(무효 제출 시 프레임 유지용).
        last_query: str | None = None
        submitted: list[dict] | None = None
        await _emit_frame(None, None)
        try:
            while True:
                try:
                    resp = await asyncio.wait_for(q.get(), timeout=wait_timeout)
                except asyncio.TimeoutError:
                    await emit_step(events, "collect_rows", "failed")
                    return {"error": f"입력 대기 시간 초과({wait_timeout // 60}분). 저장 전 반영 0건."}

                query = resp.get("query")
                if isinstance(query, str) and query.strip():
                    kw = query.strip()[:50]
                    try:
                        found = await steps.dump_projects(page, kw)
                    except Exception:  # noqa: BLE001 — 검색 실패로 런을 죽이지 않는다.
                        logger.exception("card-collect dump_projects failed")
                        found = []
                    last_results = [
                        {"code": p.get("code"), "name": p.get("name")} for p in found
                    ][:_MAX_PROJECT_RESULTS]
                    last_query = kw
                    await _emit_frame(last_results, last_query)
                    continue

                rows_in = resp.get("rows")
                if isinstance(rows_in, list):
                    ok, reason = _validate_grid_submit(rows_in, n)
                    if not ok:
                        await emit_log(events, f"입력값을 확인해 주세요: {reason}", "warn")
                        await _emit_frame(last_results, last_query)  # 프레임 유지 — 재제출 유도.
                        continue
                    submitted = rows_in
                    break

                # done/기타 — 그리드에선 사용하지 않는다(무시하고 계속 대기).
                logger.debug("card-collect grid: 무시된 메시지 %r", resp)
                continue

            # ── 반영(apply) 단계 — 비스킵 행을 no 순으로 ERP 에 순차 반영 ─────────────
            apply_rows = sorted((r for r in submitted if not r.get("skip")), key=lambda r: r["no"])
            skipped = 0
            for r in submitted:
                if r.get("skip"):
                    status[r["no"] - 1] = "skipped"
                    skipped += 1

            filled = 0
            failures: list[str] = []
            total = len(apply_rows)
            for pos, row in enumerate(apply_rows):
                no = row["no"]
                idx = no - 1
                bu = row.get("budgetUnit") or {}
                proj = row.get("project") or None
                note = (row.get("note") or "").strip()
                notes[idx] = note
                await emit_log(events, f"{no}행 반영 중…", "info")
                collected = {
                    "예산단위": bu.get("name") or "",
                    "계정": "",  # 계정은 예산단위로 자동 결정(비워 두면 자동 처리).
                    "프로젝트": (proj.get("name") if proj else "") or "",
                    "적요": note,
                }
                ok, detail = await _apply_row_fields(page, events, idx, collected)
                if ok:
                    filled += 1
                    status[idx] = "done"
                else:
                    status[idx] = "failed"  # 실패는 배치를 중단하지 않는다.
                    failures.append(f"{no}행: {detail}")
                # 진행 현황 표를 매 행 갱신(같은 chat_id 로 대체) + 2행마다·마지막에 스냅샷.
                await emit_chat(
                    events,
                    chat_id="cc-status",
                    role="assistant",
                    content="처리 현황:\n\n" + _status_table(rows_list, status, notes),
                    streaming=False,
                )
                if (pos + 1) % 2 == 0 or pos == total - 1:
                    await emit_shot(events.put, page)
        finally:
            close_hitl_channel(decision_id)

        # ── 요약 ──────────────────────────────────────────────────────────
        summary = f"반영 {filled}건 · 건너뜀 {skipped}건 · 실패 {len(failures)}건"
        if failures:
            summary += "\n\n실패 상세:\n- " + "\n- ".join(failures)
        await emit_chat(
            events,
            chat_id="cc-summary",
            role="assistant",
            content=summary + "\n\n" + _status_table(rows_list, status, notes),
            streaming=False,
        )
        await emit_log(events, f"항목 처리 완료 — {filled}건 반영(저장 전).", "ok")
        await emit_step(events, "collect_rows", "done")
        return {"filled": filled}

    return collect_rows


async def _apply_row_fields(
    page: Any, events: Any, row: int, collected: dict[str, str]
) -> tuple[bool, str]:
    """한 행에 적요(인라인) + 예산단위/계정/프로젝트(코드피커) 채우고 apply_row(일괄적용).

    반환 (ok, detail). detail 은 성공 시 **실제 선택된 이름**(사용자 입력이 아님, 리뷰 #1), 실패 시 사유.
    적요 세팅 실패는 치명(리뷰 #11) — 적요 없이 반영하지 않는다. 필드 순서(예산단위→계정→프로젝트)
    는 계정의 예산단위 의존 때문에 고정. 계정만 자동축소 단일 허용(allow_default).
    """
    note_res = await steps.set_note(page, row, collected["적요"])
    if not note_res.get("ok"):
        return False, f"적요 세팅 실패: {note_res.get('err') or note_res.get('reason')}"
    applied: list[str] = []
    for field in ("예산단위", "계정", "프로젝트"):
        # 프로젝트는 그리드에서 선택하지 않을 수 있다(옵션) — 값이 없으면 건너뛴다.
        # (계정은 값 없이도 예산단위 연동 자동축소를 태워야 하므로 건너뛰지 않는다.)
        if field == "프로젝트" and not (collected.get("프로젝트") or "").strip():
            continue
        spec = FIELD_SPEC[field]
        r = await steps.fill_codepicker(
            page, spec["id"], collected[field], spec["code"], spec["name"],
            allow_default=(field == "계정"),
        )
        if not r.get("ok"):
            return False, f"{field} '{collected[field]}': {r.get('reason')}"
        await emit_log(events, f"{field} = {r.get('name')} (code {r.get('code')})", "info")
        applied.append(f"{field} {r.get('name')}")
    ap = await steps.apply_row(page, row)
    if not ap.get("ok"):
        return False, f"일괄적용 실패: {ap.get('reason')}"
    return True, " / ".join(applied) + f" / 적요 '{collected['적요']}'"


# ── 저장(최종 HITL 확인 후에만) ───────────────────────────────────────────────────
def make_save_node():
    async def save(state: dict) -> dict:
        if state.get("error"):
            return {"result": f"오류로 저장하지 않음: {state.get('error')}"}
        events = state["events"]
        page = state["page"]
        filled = state.get("filled", 0)
        await emit_step(events, "save", "running")
        if not filled:
            await emit_step(events, "save", "done")  # 스텝을 'pending' 에 멈추지 않는다(리뷰 #13).
            return {"result": "반영된 건이 없어 저장하지 않았습니다."}
        # 실 회계 반영이라 반드시 사용자 확인(choice) 후에만 F7.
        try:
            resp = await wait_hitl(
                events,
                kind="choice",
                title="결의서 저장 확인",
                prompt=f"{filled}건이 입력되었습니다. 결의서를 저장(F7)할까요? 저장 시 실제 전표가 생성됩니다.",
                options=[
                    {"value": "save", "label": "저장", "description": "실제 결의서 저장(F7)"},
                    {"value": "cancel", "label": "저장 안 함", "description": "입력만 유지, 저장 취소"},
                ],
                owner=state.get("owner"),
                run_id=state.get("run_id"),
            )
        except asyncio.TimeoutError:
            await emit_step(events, "save", "failed")
            return {"error": f"저장 확인 대기 시간 초과 — {filled}건 입력됨(저장 안 함)."}
        choice = (resp.get("value") or resp.get("message") or "").strip()
        if choice != "save":
            await emit_step(events, "save", "done")
            return {"result": f"{filled}건 입력 완료 — 사용자 선택으로 저장하지 않았습니다."}
        r = await steps.save_document(page, confirm=True)
        if not r.get("ok"):
            await emit_step(events, "save", "failed")
            return {"error": f"저장 실패: {r}"}
        await emit_log(events, f"결의서 저장 완료(F7, via {r.get('via')}).", "ok")
        await emit_shot(events.put, page)
        await emit_step(events, "save", "done")
        return {"result": f"{filled}건 입력·저장 완료."}

    return save
