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

import httpx
from sqlalchemy import select

from app.agents.common.nodes import (
    make_add_row_node,
    make_open_evdn_node,
    make_select_evdn_node,
)
from app.config import get_settings
from app.db import get_sessionmaker
from app.live.events import emit_chat, emit_hitl, emit_log, emit_step, emit_transactions
from app.live.hitl import close_hitl_channel, open_hitl_channel, wait_hitl
from app.models import ErpCodeCatalog, User, UserCodeFavorite
from app.services.code_sync import dept_matches_budget_name
from nbkit.patterns import emit_shot

from . import steps
from .recommend import RECOMMEND_CONFIDENCE_THRESHOLD, recommend_selections

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


# ── 회계일(마스터 그리드 ACTG_DT = 수집 기간 월의 말일) ────────────────────────────
def _params_today(state: dict) -> date:
    """params['today'] 재정의(테스트/재현용) 지원 — set_period 와 동일 규약."""
    params = state.get("params") or {}
    raw = params.get("today")
    if raw:
        try:
            return date.fromisoformat(str(raw))
        except (ValueError, TypeError):
            pass
    return date.today()


def make_set_acct_date_node():
    """회계일 규칙(사용자 확정 2026-07-04): 전월 수집=전월 말일, 당월 수집=당월 말일.

    F3 직후 생성된 마스터(결의서) 행의 ACTG_DT 를 수집 기간 월의 말일로 설정한다.
    카드 팝업이 뜨기 전(메인 화면)이라 안전하게 datasource 로 쓴다(프로브 실측).
    """

    async def set_acct_date(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        await emit_step(events, "set_acct_date", "running")
        t0 = time.monotonic()
        start, _end = steps.compute_period(_params_today(state))
        compact, dashed = steps.period_month_end(start)
        r = await steps.set_acct_date(page, compact, dashed)
        if not r.get("ok"):
            await emit_step(events, "set_acct_date", "failed")
            return {"error": f"회계일 설정 실패({dashed}): {r.get('reason')}"}
        await emit_log(events, f"회계일 = {dashed} (수집 기간 월의 말일).", "info")
        await emit_step(events, "set_acct_date", "done", _ms(t0))
        return {}

    return set_acct_date


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


_STATUS_MARK = {
    "done": "✅ 반영",
    "skipped": "⏭️ 건너뜀",
    "failed": "❌ 실패",
    "pending": "· 대기",
    "wait2": "🕓 2차(불공) 대기",
}


def _row_key(r: dict) -> str:
    """거래 행 식별키 — 승인/취소 쌍이 같은 APRVL_NO 라(프로브 실측) 일자·금액까지 복합."""
    return f"{r.get('APRVL_NO') or ''}|{r.get('TRAN_DT') or ''}|{r.get('TRAN_AMT') or ''}"


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


async def _load_budget_catalog() -> list[dict]:
    """erp_code_catalog(kind='budget_unit') 캐시 → dump_budget_units 와 동일 형태 목록.

    라이브 피커 전량 덤프(~3.4s + 대형 DOM 리드)를 매 런 반복하지 않기 위한 속도 최적화
    (2026-07-04). code_sync 가 같은 dump 로 채우므로 형태가 1:1(code=BG|BIZPLAN|BGACCT,
    name=BG_NM, extra=bizplan/bgacct). 비어 있으면 [] — 호출부가 라이브 덤프로 폴백한다.
    """
    async with get_sessionmaker()() as s:
        rows = (
            await s.execute(select(ErpCodeCatalog).where(ErpCodeCatalog.kind == "budget_unit"))
        ).scalars().all()
    out: list[dict] = []
    for r in rows:
        extra = r.extra or {}
        out.append(
            {
                "code": r.code,
                "name": r.name,
                "bizplanCd": extra.get("bizplanCd", ""),
                "bizplanNm": extra.get("bizplanNm", ""),
                "bgacctCd": extra.get("bgacctCd", ""),
                "bgacctNm": extra.get("bgacctNm", ""),
            }
        )
    return out


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
        extra = f.extra or {}
        if f.kind == "budget_unit":
            budget_favs.append(
                {
                    "code": f.code,
                    "name": f.name,
                    "bizplanNm": extra.get("bizplanNm", ""),
                    "bgacctNm": extra.get("bgacctNm", ""),
                    "isDefault": f.is_default,
                }
            )
        elif f.kind == "project":
            project_favs.append(
                {
                    "code": f.code,
                    "name": f.name,
                    "wbsNo": extra.get("wbsNo", ""),
                    "wbsNm": extra.get("wbsNm", ""),
                    "isDefault": f.is_default,
                }
            )
    return budget_favs, project_favs, department


def _pick_budget(o: dict) -> dict:
    return {
        "code": o["code"],
        "name": o["name"],
        "bizplanNm": o.get("bizplanNm", ""),
        "bgacctNm": o.get("bgacctNm", ""),
    }


def _pick_project(o: dict) -> dict:
    return {
        "code": o["code"],
        "name": o["name"],
        "wbsNo": o.get("wbsNo", ""),
        "wbsNm": o.get("wbsNm", ""),
    }


# 비용구분 → 예산계정 접두사. 팀의 비용구분이 이 접두사 계정을 우선하게 한다.
_COST_PREFIX = {"판관비": "(판)", "제조원가": "(제)"}


async def _prefill_selections(
    events: Any,
    settings: Any,
    rows_list: list[dict],
    recs: dict[int, str],
    budget_favs: list[dict],
    mine_units: list[dict],
    project_favs: list[dict],
    cost_prefix: str | None = None,
) -> dict[int, dict]:
    """행별 예산단위·프로젝트 프리셀렉트 — AI 추천이 확신하면 그 항목, 아니면 기본지정 폴백.

    반환 {no: {budgetUnit, project, budgetSource, projectSource}} — 각 값은 없으면 None.
    예산단위·프로젝트는 서로 독립적으로 결정한다(예: 예산단위는 AI, 프로젝트는 기본).
    """
    # AI 후보 — 예산단위(자주쓰는 + 내 부서, code 중복 제거) / 프로젝트(자주쓰는).
    budget_candidates: list[dict] = []
    seen: set[str] = set()
    for c in [*budget_favs, *mine_units]:
        code = c.get("code")
        if code and code not in seen:
            seen.add(code)
            budget_candidates.append(c)
    project_candidates = list(project_favs)

    recommendations: dict[int, dict] = {}
    if settings.gemini_api_key and (budget_candidates or project_candidates):
        rec_rows = [
            {
                "no": idx + 1,
                "merchant": r.get("TRAN_NM") or "",
                "amount": _fmt_won(r.get("TRAN_AMT")),
                "vatType": r.get("VAT_TP") or "",
                "note": recs[r.get("i", idx)],
            }
            for idx, r in enumerate(rows_list)
        ]
        await emit_log(events, "AI 추천을 계산하는 중입니다…", "info")
        http = httpx.AsyncClient(timeout=60.0)
        try:
            recommendations = await recommend_selections(
                rec_rows, budget_candidates, project_candidates, http=http, settings=settings
            )
        finally:
            await http.aclose()
        if not recommendations:
            await emit_log(events, "AI 추천을 받지 못해 기본지정으로 프리필합니다.", "warn")

    budget_by_code = {c["code"]: c for c in budget_candidates}
    project_by_code = {c["code"]: c for c in project_candidates}

    # 기본 예산단위 폴백: 기본지정(isDefault) 우선, 단 비용구분 접두사가 있으면 접두사 일치를
    # 더 우선한다(기본지정 없음 + 접두사 일치 후보가 있으면 그것으로 폴백).
    def _prefix_ok(c: dict) -> bool:
        return bool(cost_prefix) and (c.get("bgacctNm") or "").startswith(cost_prefix)

    default_budget = (
        next((c for c in budget_favs if c.get("isDefault") and _prefix_ok(c)), None)
        or next((c for c in budget_favs if c.get("isDefault")), None)
        or (next((c for c in budget_candidates if _prefix_ok(c)), None) if cost_prefix else None)
    )
    default_project = next((c for c in project_favs if c.get("isDefault")), None)

    out: dict[int, dict] = {}
    for idx in range(len(rows_list)):
        no = idx + 1
        rec = recommendations.get(no) or {}
        hi = rec.get("confidence", 0.0) >= RECOMMEND_CONFIDENCE_THRESHOLD

        ai_budget = budget_by_code.get(rec.get("budgetUnitCode", "")) if hi else None
        if ai_budget:
            budget, budget_source = _pick_budget(ai_budget), "ai"
        elif default_budget:
            budget, budget_source = _pick_budget(default_budget), "default"
        else:
            budget, budget_source = None, None

        ai_project = project_by_code.get(rec.get("projectCode", "")) if hi else None
        if ai_project:
            project, project_source = _pick_project(ai_project), "ai"
        elif default_project:
            project, project_source = _pick_project(default_project), "default"
        else:
            project, project_source = None, None

        out[no] = {
            "budgetUnit": budget,
            "project": project,
            "budgetSource": budget_source,
            "projectSource": project_source,
        }
    return out


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
        t0 = time.monotonic()
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
            await emit_step(events, "collect_rows", "done", _ms(t0))
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

        # 즐겨찾기·부서(DB) + 예산단위 목록. 카탈로그 캐시(erp_code_catalog) 우선 — 라이브
        # 피커 전량 덤프(~3.4s)는 캐시가 빌 때만 폴백(속도 최적화 2026-07-04).
        budget_favs, project_favs, department = await _load_user_favorites(state.get("owner"))
        try:
            all_units = await _load_budget_catalog()
        except Exception:  # noqa: BLE001 — 캐시 조회 실패로 런을 죽이지 않는다.
            logger.exception("card-collect budget catalog load failed")
            all_units = []
        if all_units:
            await emit_log(events, f"예산단위 {len(all_units)}건 — 카탈로그 캐시 사용(덤프 생략).", "info")
        else:
            try:
                all_units = await steps.dump_budget_units(page)
            except Exception:  # noqa: BLE001 — 덤프 실패로 런을 죽이지 않는다.
                logger.exception("card-collect dump_budget_units failed")
                all_units = []
        if not all_units:
            await emit_log(events, "예산단위 목록을 불러오지 못했습니다(즐겨찾기·검색으로 진행).", "warn")

        # '내 부서' = 예산단위명 ↔ 소속부서 정규화 매칭('인사/기획팀' ↔ '인사기획팀').
        mine_units = [u for u in all_units if dept_matches_budget_name(department, u["name"])]
        # 소속 팀 비용구분(판관비→'(판)' / 제조원가→'(제)') 이 있으면 그 접두사 계정을 우선한다
        # (내 부서 목록·AI 후보·기본 폴백 순서에 반영). 없으면 기존 순서 유지.
        cost_type = (state.get("params") or {}).get("cost_type")
        cost_prefix = _COST_PREFIX.get(cost_type or "")
        if cost_prefix:
            await emit_log(
                events, f"소속 팀 비용구분 '{cost_type}' → 예산계정 '{cost_prefix}' 우선 선택.", "info"
            )
            mine_units = sorted(
                mine_units,
                key=lambda u: 0 if (u.get("bgacctNm") or "").startswith(cost_prefix) else 1,
            )
        # 그리드 선택지는 자주쓰는 + 내 부서만(사용자 확정 — 전사 전체는 과다·캡 잘림으로 무의미).
        # 전량 덤프(all_units)는 내 부서 매칭·AI 추천 후보용으로만 쓴다.
        budget_units = {
            "favorites": budget_favs[:_MAX_FAVORITES],
            "mine": mine_units[:_MAX_BUDGET_UNITS],
        }
        project_favs = project_favs[:_MAX_FAVORITES]

        # AI 추천 + 기본지정 폴백으로 행별 예산단위·프로젝트를 프리셀렉트한다(사용자는 수정 가능).
        # 기본지정 부재는 폴백이 조용히 비는 원인이므로 명시적으로 알려 진단을 돕는다.
        missing_defaults = [
            label
            for label, favs in (("예산단위", budget_favs), ("프로젝트", project_favs))
            if favs and not any(f.get("isDefault") for f in favs)
        ]
        if missing_defaults:
            await emit_log(
                events,
                f"{'/'.join(missing_defaults)} 기본지정이 없어 AI 추천 실패 시 빈 선택으로 둡니다"
                " (관리 페이지에서 '기본'을 지정하세요).",
                "info",
            )
        preselect = await _prefill_selections(
            events, settings, rows_list, recs, budget_favs, mine_units, project_favs,
            cost_prefix=cost_prefix,
        )

        # 그리드 행(프론트 계약: no·card·merchant·amount·date·time·approved·vatType·note
        #  + 프리셀렉트 budgetUnit/project·출처 budgetSource/projectSource).
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
                **preselect[idx + 1],
            }
            for idx, r in enumerate(rows_list)
        ]

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
                prompt=(
                    "행별로 예산단위·프로젝트·적요를 입력한 뒤 '입력 완료'를 누르세요. "
                    "과세 행은 법인카드(01), 나머지는 법인카드(불공)(02)으로 자동 전환해 "
                    "반영하고, 마지막에 저장(F7)까지 자동 진행합니다."
                ),
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
                        {
                            "code": p.get("code"),
                            "name": p.get("name"),
                            "wbsNo": p.get("wbsNo", ""),
                            "wbsNm": p.get("wbsNm", ""),
                        }
                        for p in found
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

            # ── 부가세구분 분할: 과세 → 1차(법인카드) 즉시 반영, 그 외 → 2차(불공) 대기 ──
            # 사용자 입력은 이 그리드 1회가 전부 — 2차는 여기 보존한 입력을 재조회 행에
            # (APRVL_NO+일자+금액) 키로 매칭해 자동 적용한다(재입력 없음).
            apply_rows = sorted((r for r in submitted if not r.get("skip")), key=lambda r: r["no"])
            skipped = 0
            for r in submitted:
                if r.get("skip"):
                    status[r["no"] - 1] = "skipped"
                    skipped += 1

            taxable_work: list[dict] = []
            pending_nontax: list[dict] = []
            for row in apply_rows:
                idx = row["no"] - 1
                src = rows_list[idx]
                entry = {
                    "idx": idx,
                    "label": row["no"],
                    "budgetUnit": row.get("budgetUnit") or {},
                    "project": row.get("project") or None,
                    "note": (row.get("note") or "").strip(),
                }
                if (src.get("VAT_TP") or "").strip() == "과세":
                    taxable_work.append(entry)
                else:
                    pending_nontax.append(
                        {**entry, "key": _row_key(src), "merchant": src.get("TRAN_NM") or ""}
                    )
                    status[idx] = "wait2"
                    notes[idx] = entry["note"]

            # 행 분류 전문 로깅 — 승인취소(음수) 행이 어느 패스로 갔는지 사후 진단용.
            def _row_desc(e: dict, tag: str) -> str:
                src2 = rows_list[e["idx"]]
                return (
                    f"{e['label']}행 {(src2.get('TRAN_NM') or '?')[:10]} {src2.get('TRAN_AMT', '?')}"
                    f"(승인 {src2.get('APRVL_NO', '?')}·'{src2.get('VAT_TP', '')}'→{tag})"
                )

            split_desc = ", ".join(
                [_row_desc(e, "과세") for e in taxable_work]
                + [_row_desc(e, "불공") for e in pending_nontax]
            )
            await emit_log(events, f"부가세구분 분류: {split_desc}", "info")

            filled, failures, applied_idx = await _apply_batch(
                page, events, rows_list, taxable_work, status, notes, chat_id="cc-status"
            )
        finally:
            close_hitl_channel(decision_id)

        # ── 요약(1차) ─────────────────────────────────────────────────────
        summary = (
            f"1차(법인카드·과세) 반영 {filled}건 · 2차(불공) 대기 {len(pending_nontax)}건 · "
            f"건너뜀 {skipped}건 · 실패 {len(failures)}건"
        )
        if failures:
            summary += "\n\n실패 상세:\n- " + "\n- ".join(failures)
        await emit_chat(
            events,
            chat_id="cc-summary",
            role="assistant",
            content=summary + "\n\n" + _status_table(rows_list, status, notes),
            streaming=False,
        )
        await emit_log(events, f"1차(과세) 처리 완료 — {filled}건 반영(저장 전).", "ok")
        await emit_step(events, "collect_rows", "done", _ms(t0))
        return {
            "filled": filled,
            "pending_nontax": pending_nontax,
            "pass1_applied_idx": applied_idx,
            "pass1_failed": len(failures),
        }

    return collect_rows


async def _apply_batch(
    page: Any,
    events: Any,
    rows_view: list[dict],
    work: list[dict],
    status: dict[int, str],
    notes: dict[int, str],
    *,
    chat_id: str,
) -> tuple[int, list[str], list[int]]:
    """행 배치를 순차 반영. work 항목 = {idx(현재 그리드 행 인덱스), label(표시 행번호),
    budgetUnit, project, note}. 실패는 배치를 중단하지 않는다.
    반환 (filled, failures, applied_idx — 성공 행 인덱스, 카드팝업 '적용' 체크 대상)."""
    filled = 0
    failures: list[str] = []
    applied_idx: list[int] = []
    total = len(work)
    for pos, row in enumerate(work):
        idx = row["idx"]
        label = row["label"]
        bu = row.get("budgetUnit") or {}
        proj = row.get("project") or None
        note = row["note"]
        notes[idx] = note
        await emit_log(events, f"{label}행 반영 중…", "info")
        collected = {
            "예산단위": bu.get("name") or "",
            # 조합 선택(BG×사업계획×예산계정) — 값이 있으면 그 행을 정확히 고른다.
            "예산단위_사업계획": bu.get("bizplanNm") or "",
            "예산단위_예산계정": bu.get("bgacctNm") or "",
            "계정": "",  # 계정은 예산단위로 자동 결정(비워 두면 자동 처리).
            "프로젝트": (proj.get("name") if proj else "") or "",
            # WBS 행 단위 선택 — 값이 있으면 그 WBS 요소를 정확히 고른다.
            "프로젝트_wbsNo": (proj.get("wbsNo") if proj else "") or "",
            "적요": note,
        }
        ok, detail = await _apply_row_fields(page, events, idx, collected)
        if ok:
            filled += 1
            status[idx] = "done"
            applied_idx.append(idx)
        else:
            status[idx] = "failed"
            failures.append(f"{label}행: {detail}")
            # 실패 사유를 실행 로그에도 남긴다 — 현황표(chat)만으론 종료 후 진단 불가(실전 런 교훈).
            await emit_log(events, f"{label}행 반영 실패: {detail}", "warn")
        # 진행 현황 표를 매 행 갱신(같은 chat_id 로 대체) + 2행마다·마지막에 스냅샷.
        await emit_chat(
            events,
            chat_id=chat_id,
            role="assistant",
            content="처리 현황:\n\n" + _status_table(rows_view, status, notes),
            streaming=False,
        )
        if (pos + 1) % 2 == 0 or pos == total - 1:
            await emit_shot(events.put, page)
    return filled, failures, applied_idx


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
        if field == "예산단위":
            # 선택 단위 = (BG × 사업계획 × 예산계정) 조합 행 — 그 행을 정확히 고른다.
            r = await steps.fill_budget_codepicker(
                page,
                {
                    "name": collected["예산단위"],
                    "bizplanNm": collected.get("예산단위_사업계획", ""),
                    "bgacctNm": collected.get("예산단위_예산계정", ""),
                },
            )
        elif field == "프로젝트":
            # 선택 단위 = WBS 행 — PJT_NM 검색 후 WBS_NO 정확 일치(없으면 PJT_NM 폴백).
            r = await steps.fill_project_codepicker(
                page,
                {"name": collected["프로젝트"], "wbsNo": collected.get("프로젝트_wbsNo", "")},
            )
        else:
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


# ── 문서 반영(적용) / 최종 저장(F7 은 마지막 1회, HITL 확인 후) ─────────────────────
# 업무 규칙(사용자 확정 2026-07-02): 과세 적용 → (저장 없이) F3 새 행 → 불공 진행·적용 →
# **마지막에만 저장(F7) 1회**. 적용은 draft(문서 반영, 전표 미생성)라 확인 없이 자동 진행.
async def _apply_doc(state: dict, *, label: str, step_key: str, applied_idx: list[int]) -> dict:
    """처리 행 체크 → 카드팝업 '적용' → '선택'(부가세0 포함? 예) → '예산현황' 확인 →
    팝업 닫힘·문서 반영(steps.apply_rows_to_document). 실패 시 화면 모달 텍스트 노출.
    반환 {"applied": True} | {"error": ...}."""
    events = state["events"]
    page = state["page"]
    ap = await steps.apply_rows_to_document(page, applied_idx)
    if not ap.get("ok"):
        modal_txt = "; ".join(
            f"[{m.get('title')}] {m.get('text', '')[:80]}" for m in (ap.get("modals") or [])[:2]
        )
        await emit_shot(events.put, page)
        await emit_step(events, step_key, "failed")
        return {
            "error": (
                f"{label} 적용 실패: {ap.get('reason')}"
                + (f" — 화면 메시지: {modal_txt}" if modal_txt else "")
            )
        }
    await emit_log(events, f"{label} {len(applied_idx)}건 결의서 반영(적용) 완료(저장 전).", "ok")
    await emit_shot(events.put, page)
    return {"applied": True}


def make_apply_doc_node():
    """1차(과세) 문서 반영(적용) — HITL 없음(draft). 0건이면 스킵하고 2차로."""

    async def apply_doc(state: dict) -> dict:
        if state.get("error"):
            return {"result": f"오류로 반영하지 않음: {state.get('error')}"}
        events = state["events"]
        filled = state.get("filled", 0)
        await emit_step(events, "apply_doc", "running")
        t0 = time.monotonic()
        if not filled:
            await emit_step(events, "apply_doc", "done", _ms(t0))
            await emit_log(events, "1차(과세) 반영 건이 없어 적용 없이 2차로 진행합니다.", "info")
            return {}
        out = await _apply_doc(
            state,
            label="법인카드(과세분)",
            step_key="apply_doc",
            applied_idx=state.get("pass1_applied_idx") or [],
        )
        if out.get("error"):
            return {"error": out["error"]}
        await emit_step(events, "apply_doc", "done", _ms(t0))
        # 적용으로 팝업이 닫힘 — 2차는 새 상세행 추가(F3)부터 다시 플로우를 탄다(사용자 업무 규칙).
        return {"pass1_doc_applied": True}

    return apply_doc

    return save


# ── 2차: 증빙유형 전환(법인카드(불공)) → 재조회·매칭 ───────────────────────────────
def make_switch_evdn_node():
    """카드 팝업 닫기 → 증빙유형 02 재선택 → 카드/기간/조회 재실행 → 1차 입력값 행 매칭.

    프로브 실측(2026-07-02): 팝업 '닫기' 후 같은 행에서 open_evdn→select_evdn("02") 이
    F3 없이 동작. 매칭 키 = (APRVL_NO, TRAN_DT, TRAN_AMT) — 승인/취소 쌍 구분.
    """

    async def switch_evdn(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        pending: list[dict] = state.get("pending_nontax") or []
        await emit_step(events, "switch_evdn", "running")
        t0 = time.monotonic()
        if not pending:
            await emit_log(events, "불공(비과세) 대상이 없어 2차를 생략합니다.", "info")
            await emit_step(events, "switch_evdn", "done", _ms(t0))
            return {"pass2_work": []}

        # 잔여 확인 모달('예산현황' 등)이 남아 있으면 F3/코드피커가 막힌다 — 방어적 정리.
        # (실측: 적용 후 지연 모달이 화면을 덮은 채 02 선택 시도 → TypeError 실패)
        cleared = await steps.dismiss_blocking_modals(page, rounds=3)
        if cleared:
            await emit_log(events, f"잔여 확인 모달 {len(cleared)}건을 닫고 진행합니다.", "info")

        r = await steps.close_card_popup(page)
        if not r.get("ok"):
            await emit_step(events, "switch_evdn", "failed")
            return {"error": f"카드 팝업 닫기 실패: {r.get('reason')}"}
        # 증빙유형 재선택 — 진입 공용 노드 재사용(state error 규약 공유, 스텝은 자체 방출).
        # 업무 규칙(사용자 확정): 1차 적용('적용' 클릭·문서 반영)을 했다면 **새 상세행 추가(F3)
        # 후** 다시 증빙유형부터 플로우를 탄다. 적용을 생략한 경우(과세 0건)는 기존 행에서
        # 재선택(프로브 실측: F3 불필요). 재선택 실패 시 F3 1회 폴백은 안전망으로 유지.
        if state.get("pass1_doc_applied"):
            await emit_log(events, "1차 적용 완료 — 새 상세행(F3) 추가 후 불공 플로우를 진행합니다.", "info")
            out = await make_add_row_node()(state)
            state.update(out or {})
            if state.get("error"):
                await emit_step(events, "switch_evdn", "failed")
                return {"error": state["error"]}
        out = await make_open_evdn_node()(state)
        state.update(out or {})
        if state.get("error") and not state.get("pass1_doc_applied"):
            await emit_log(events, "증빙 에디터 재오픈 실패 — 새 행(F3) 추가 후 재시도합니다.", "warn")
            state.pop("error", None)
            out = await make_add_row_node()(state)
            state.update(out or {})
            if not state.get("error"):
                out = await make_open_evdn_node()(state)
                state.update(out or {})
        if state.get("error"):
            await emit_step(events, "switch_evdn", "failed")
            return {"error": state["error"]}
        out = await make_select_evdn_node("02")(state)
        state.update(out or {})
        if state.get("error"):
            await emit_step(events, "switch_evdn", "failed")
            return {"error": state["error"]}

        r = await steps.select_all_cards(page)
        if not r.get("ok"):
            await emit_step(events, "switch_evdn", "failed")
            return {"error": f"2차 카드 전체선택 실패: {r.get('reason')}"}
        period = state.get("period") or list(steps.compute_period(date.today()))
        pr = await steps.set_period(page, period[0], period[1])
        if not pr.get("ok"):
            await emit_step(events, "switch_evdn", "failed")
            return {"error": f"2차 승인일 기간 설정 실패: {pr}"}
        rows2 = await steps.run_query(page)
        if not isinstance(rows2, int) or rows2 < 0:
            await emit_step(events, "switch_evdn", "failed")
            return {"error": "2차 조회에 실패했습니다(그리드 로딩 실패)."}
        lst2 = await steps.read_rows(page, limit=500)
        # 2차 조회 리스트 전문 로깅 — 1차에서 적용된 행이 '처리여부' 전환 실패로 재출현하는
        # 이상 징후(실전 관찰: 불공 리스트 2건) 진단용. 승인번호·금액·부가세구분을 남긴다.
        summary2 = ", ".join(
            f"{(r.get('TRAN_NM') or '?')[:10]} {r.get('TRAN_AMT', '?')}"
            f"(승인 {r.get('APRVL_NO', '?')}·부가세구분 '{r.get('VAT_TP', '')}')"
            for r in lst2[:8]
        )
        await emit_log(events, f"2차(불공) 조회 {len(lst2)}건: {summary2}", "info")
        expected2 = len(pending)
        if len(lst2) > expected2:
            await emit_log(
                events,
                f"⚠ 2차 조회가 예상({expected2}건)보다 많음 — 1차 적용 행 중 처리 전환 안 된 행이 "
                "재출현했을 수 있음(승인취소 행 여부 확인 필요).",
                "warn",
            )

        # 키당 후보 큐 — 동일 복합키(같은 승인번호·일자·금액) 행이 여러 건이어도 각 pending 이
        # 서로 다른 실제 행을 1:1 소비한다. setdefault(단일 보관)면 두 입력이 같은 행에 이중
        # 반영되고 다른 행은 조용히 누락된다(리뷰 HIGH #1).
        by_key: dict[str, list[dict]] = {}
        for r2 in lst2:
            by_key.setdefault(_row_key(r2), []).append(r2)
        work: list[dict] = []
        unmatched: list[str] = []
        for p in pending:
            queue = by_key.get(p["key"]) or []
            # 재조회에서 사라졌거나(큐 소진) 과세로 재분류된 행은 배제(안전) — 실패로 기록.
            hit = queue.pop(0) if queue else None
            if hit is None or (hit.get("VAT_TP") or "").strip() == "과세":
                unmatched.append(f"{p['label']}행({p.get('merchant', '')})")
                continue
            work.append(
                {
                    "idx": hit.get("i"),
                    "label": p["label"],
                    "budgetUnit": p["budgetUnit"],
                    "project": p["project"],
                    "note": p["note"],
                }
            )
        if unmatched:
            await emit_log(
                events,
                f"2차 재조회 매칭 실패 {len(unmatched)}건(반영 제외): {', '.join(unmatched[:5])}",
                "warn",
            )
        await emit_log(
            events, f"증빙유형 '법인카드(불공)' 전환 완료 — 2차 대상 {len(work)}건.", "ok"
        )
        await emit_shot(events.put, page)
        await emit_step(events, "switch_evdn", "done", _ms(t0))
        return {
            "rows2_list": lst2,
            "pass2_work": work,
            "pass2_unmatched": len(unmatched),
            "pass2_unmatched_desc": ", ".join(unmatched[:5]),
        }

    return switch_evdn


def make_apply_pass2_node():
    """2차(불공) 반영 — 1차 그리드에서 보존한 입력값을 매칭 행에 순차 적용(재입력 없음)."""

    async def apply_pass2(state: dict) -> dict:
        if state.get("error"):
            return {}
        events = state["events"]
        page = state["page"]
        work: list[dict] = state.get("pass2_work") or []
        await emit_step(events, "apply_pass2", "running")
        t0 = time.monotonic()
        if not work:
            await emit_step(events, "apply_pass2", "done", _ms(t0))
            return {"pass2_filled": 0}
        rows2: list[dict] = state.get("rows2_list") or []
        target_idx = {w["idx"] for w in work}
        rows_view = [r for r in rows2 if r.get("i") in target_idx]
        status2: dict[int, str] = {r.get("i"): "pending" for r in rows_view}
        notes2: dict[int, str] = {w["idx"]: w["note"] for w in work}
        filled2, failures2, applied2_idx = await _apply_batch(
            page, events, rows_view, work, status2, notes2, chat_id="cc-status2"
        )
        unmatched_n = state.get("pass2_unmatched", 0)
        summary = (
            f"2차(법인카드·불공) 반영 {filled2}건 · 매칭 실패 {unmatched_n}건 · "
            f"실패 {len(failures2)}건"
        )
        if unmatched_n:
            # 재조회에서 못 찾은 거래는 반영이 누락된 것 — 요약에 반드시 노출(리뷰 HIGH #2).
            summary += f"\n\n⚠ 매칭 실패(수동 확인 필요): {state.get('pass2_unmatched_desc', '')}"
        if failures2:
            summary += "\n\n실패 상세:\n- " + "\n- ".join(failures2)
        await emit_chat(
            events,
            chat_id="cc-summary2",
            role="assistant",
            content=summary + "\n\n" + _status_table(rows_view, status2, notes2),
            streaming=False,
        )
        await emit_log(events, f"2차(불공) 처리 완료 — {filled2}건 반영(저장 전).", "ok")
        # 불공분도 문서에 반영(적용) — 저장(F7)은 마지막 save_final 에서 1회만.
        if applied2_idx:
            out = await _apply_doc(
                state, label="법인카드(불공분)", step_key="apply_pass2", applied_idx=applied2_idx
            )
            if out.get("error"):
                return {"error": out["error"]}
        await emit_step(events, "apply_pass2", "done", _ms(t0))
        return {"pass2_filled": filled2, "pass2_applied_idx": applied2_idx, "pass2_failed": len(failures2)}

    return apply_pass2


def make_save_final_node():
    """최종 저장(F7) 1회 — 별도 확인 없음(사용자 업무 규칙: 그리드 '입력 완료' 제출이 곧
    저장까지의 승인이다). 반영 0건이면 저장하지 않는다."""

    async def save_final(state: dict) -> dict:
        if state.get("error"):
            return {"result": f"오류로 저장하지 않음: {state.get('error')}"}
        events = state["events"]
        page = state["page"]
        filled1 = state.get("filled", 0)
        filled2 = state.get("pass2_filled", 0)
        failed_n = state.get("pass1_failed", 0) + state.get("pass2_failed", 0)
        unmatched_n = state.get("pass2_unmatched", 0)
        # 매칭 실패(반영 누락)는 최종 결과에 반드시 노출한다(리뷰 HIGH #2).
        tail = f" · ⚠ 매칭 실패 {unmatched_n}건(수동 확인 필요)" if unmatched_n else ""
        if failed_n:
            tail += f" · ⚠ 행 반영 실패 {failed_n}건"
        total = filled1 + filled2
        await emit_step(events, "save_final", "running")
        t0 = time.monotonic()
        if not total:
            # 반영 0건: 조회 자체가 0건이면 정상 완료지만, 행 반영 **실패** 때문이라면
            # '처리 완료'로 위장하지 않고 실패로 보고한다(실전 2026-07-04: 40/40 실패가
            # '처리 완료 — 반영 0건'으로 성공 표시되던 문제).
            if failed_n:
                await emit_step(events, "save_final", "failed")
                return {"error": f"모든 행 반영 실패({failed_n}건) — 저장하지 않았습니다. 로그의 행별 실패 사유를 확인하세요."}
            await emit_step(events, "save_final", "done", _ms(t0))
            return {"result": f"처리 완료 — 반영 0건(저장할 내용 없음){tail}."}
        # 과세/불공 어느 한쪽이 0건이면 그 패스는 생략된 것 — 나머지 반영분만으로 저장한다.
        await emit_log(events, f"과세 {filled1}건 · 불공 {filled2}건 반영 완료 — 저장(F7)을 진행합니다.", "info")
        r = await steps.save_document(page, confirm=True)
        if not r.get("ok"):
            await emit_step(events, "save_final", "failed")
            return {"error": f"저장 실패: {r.get('reason') or r}"}
        seen = r.get("modals_seen") or []
        if seen:
            await emit_log(
                events,
                "저장 중 확인창: "
                + " / ".join(f"[{m.get('title')}] {m.get('text', '')[:160]}" for m in seen[:3]),
                "info",
            )
        await emit_log(events, "결의서 저장 시퀀스 완료(F7).", "ok")
        await emit_shot(events.put, page)
        await emit_step(events, "save_final", "done", _ms(t0))
        return {"result": f"처리 완료 — 과세 {filled1}건 · 불공 {filled2}건 입력·저장{tail}."}

    return save_final
