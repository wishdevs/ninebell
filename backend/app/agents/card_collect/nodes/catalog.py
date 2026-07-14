"""코드 카탈로그·즐겨찾기 로딩 — 예산단위/프로젝트 후보와 seed 계정 해석."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import ErpCodeCatalog, User, UserCodeFavorite
from app.services import cost_project as _cost_project


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
        # bgacctCd 는 계정 인지 적요 리졸버(suggest_note)의 매칭 키 — 프리셀렉트 예산단위가
        # 그 계정으로 초기 적요를 태우려면 코드가 실려야 한다(제출 write 경로와도 대칭).
        "bgacctCd": o.get("bgacctCd", ""),
        "bgacctNm": o.get("bgacctNm", ""),
    }


def _pick_project(o: dict) -> dict:
    return {
        "code": o["code"],
        "name": o["name"],
        "wbsNo": o.get("wbsNo", ""),
        "wbsNm": o.get("wbsNm", ""),
    }


def _acct_norm(s: str | None) -> str:
    """예산계정명 매칭 키 — (판)/(제)/(공통) 접두사·공백·하이픈·괄호를 흡수해
    seed 계정과목('복리후생비-석식')과 예산단위 bgacctNm('(판)복리후생비-석식')을 묶는다."""
    t = str(s or "")
    for pre in ("(판)", "(제)", "(공통)", "（판）", "（제）"):
        t = t.replace(pre, "")
    return re.sub(r"[\s()\[\]{}·・,./\-_]+", "", t).lower()


def _resolve_seed_budget(acct_name: str | None, candidates: list[dict]) -> dict | None:
    """seed 계정과목명을 예산단위 후보의 bgacctNm 과 매칭해 예산단위(_pick_budget 형태) 반환.

    사용자 결정 '1.a'(2026-07-04): 계정 → 예산단위 연결. 별도 표가 아니라 예산단위 카탈로그의
    bgacctNm(계정명)으로 런타임 매칭한다. 정확 매칭 1건이면 그것, 아니면 None(모호/무매칭 →
    AI/기본에 맡김)."""
    if not acct_name:
        return None
    key = _acct_norm(acct_name)
    if not key:
        return None
    hits = [c for c in candidates if _acct_norm(c.get("bgacctNm")) == key]
    return _pick_budget(hits[0]) if len(hits) == 1 else None


# 비용구분 → 예산계정 접두사. 팀의 비용구분이 이 접두사 계정을 우선하게 한다.
_COST_PREFIX = {"판관비": "(판)", "제조원가": "(제)"}
# 비용구분 → 기본 프로젝트 해석은 공용 서비스로 승격(card·trip 단일 소스). 하위호환 이름 유지.
_COST_PROJECT_NO = _cost_project.COST_PROJECT_NO


async def _load_cost_project(cost_type: str | None) -> dict | None:
    """비용구분 기본 프로젝트 — app.services.cost_project.resolve_cost_project 위임(단일 소스)."""
    return await _cost_project.resolve_cost_project(cost_type)
