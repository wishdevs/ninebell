"""내 즐겨찾기 ERP 코드 + 공용 코드 카탈로그 + 헤드리스 동기화 라우터.

- /me/favorites        : 사용자별 즐겨찾는 예산단위/프로젝트 코드 CRUD + 순서변경(소유자 스코프).
- /me/catalog          : 공용 코드 카탈로그 조회(예산단위는 부서 스코프, 프로젝트는 전사).
- /me/catalog/sync     : 카탈로그 헤드리스 동기화 트리거(1슬롯 세마포어, 백그라운드 태스크).
모든 엔드포인트 인증(get_current_user) 필요. 응답은 프론트 규약대로 camelCase.
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

import app.db as appdb

# 옴니솔 비밀번호 조회의 단일 소스는 core.creds — 모듈 전역 별칭(_omnisol_password)은 테스트
# 주입 앵커(test_me_codes.py 가 monkeypatch). trigger_sync 가 호출 시점에 이 전역을 읽는다.
from app.core.creds import omnisol_password as _omnisol_password
from app.core.deps import CurrentUser, DbSession, RequireAdmin
from app.core.listing import PageQuery, page_slice, paginate
from app.core.permissions import ROLE_ADMIN, role_rank
from app.models import (
    CardLearnedSelection,
    CardSeedNote,
    CardSeedSelection,
    ErpCodeCatalog,
    MerchantDictRule,
    UserCodeFavorite,
)
from app.services import card_learning, erp_sync
from app.services.code_sync import dept_matches_budget_name
from app.services.cost_project import resolve_cost_project
from app.services.ordering import reorder_by_client_order
from app.services.org_lookup import user_cost_type
from app.services.owner_scope import get_owned_or_none

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/me", tags=["me-codes"])

# 카탈로그/동기화 kind — ERP 코드만(에이전트는 카탈로그·동기화 대상이 아님).
_VALID_KINDS = ("budget_unit", "project", "partner", "org_unit")
# 즐겨찾기 kind — 스키마 레벨에서 강제(무효 kind 행 축적 방지, 리뷰 MEDIUM #4).
# 'agent' = 홈 '자주쓰는 에이전트'(code=에이전트 id, name=에이전트명) — 즐겨찾기 전용.
# 'project_purchase' = 구매팀 자주쓰는 프로젝트 — 카탈로그(kind='project')는 그대로 공유하고
# 즐겨찾기 네임스페이스만 용도별로 가른다(2026-08-21). (user,kind,code) 유니크 + kind별
# is_default 부분 유니크(0034)가 kind 단위라 마이그레이션 없이 독립 목록·독립 기본지정이 된다.
CodeKind = Literal["budget_unit", "project", "project_purchase", "partner", "agent"]

# ── 스키마 ────────────────────────────────────────────────────────────────────
class FavoriteCreate(BaseModel):
    kind: CodeKind
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    extra: dict | None = None


class ReorderIn(BaseModel):
    kind: CodeKind
    orderedIds: list[str]


class SyncIn(BaseModel):
    kind: str = Field(min_length=1, max_length=16)


def _fav_dict(f: UserCodeFavorite) -> dict:
    return {
        "id": str(f.id),
        "kind": f.kind,
        "code": f.code,
        "name": f.name,
        "extra": f.extra,
        "sortOrder": f.sort_order,
        "isDefault": f.is_default,
    }


# ── 즐겨찾기 CRUD ─────────────────────────────────────────────────────────────
@router.get("/favorites")
async def list_favorites(user: CurrentUser, db: DbSession, kind: str | None = None) -> dict:
    """현재 유저의 즐겨찾기(순서대로). kind 로 필터."""
    stmt = select(UserCodeFavorite).where(UserCodeFavorite.user_id == user.id)
    if kind:
        stmt = stmt.where(UserCodeFavorite.kind == kind)
    stmt = stmt.order_by(UserCodeFavorite.sort_order.asc(), UserCodeFavorite.created_at.asc())
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [_fav_dict(f) for f in rows]}


@router.post("/favorites", status_code=status.HTTP_201_CREATED)
async def create_favorite(body: FavoriteCreate, user: CurrentUser, db: DbSession):
    """즐겨찾기 추가. 이미 있는 (user,kind,code)면 기존 행을 200 으로 반환(멱등)."""
    existing = (
        await db.execute(
            select(UserCodeFavorite).where(
                UserCodeFavorite.user_id == user.id,
                UserCodeFavorite.kind == body.kind,
                UserCodeFavorite.code == body.code,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return JSONResponse(_fav_dict(existing), status_code=status.HTTP_200_OK)
    max_order = (
        await db.execute(
            select(func.max(UserCodeFavorite.sort_order)).where(
                UserCodeFavorite.user_id == user.id, UserCodeFavorite.kind == body.kind
            )
        )
    ).scalar()
    fav = UserCodeFavorite(
        user_id=user.id,
        kind=body.kind,
        code=body.code,
        name=body.name,
        extra=body.extra,
        sort_order=(max_order or 0) + 1,
    )
    db.add(fav)
    await db.commit()
    return _fav_dict(fav)


@router.delete("/favorites/{fav_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_favorite(fav_id: str, user: CurrentUser, db: DbSession):
    """소유자 스코프 삭제. 대상이 없거나 소유자 불일치면 404."""
    fav = await get_owned_or_none(db, UserCodeFavorite, fav_id, user.id)
    if fav is None:
        return JSONResponse({"error": "즐겨찾기를 찾을 수 없습니다."}, status_code=404)
    await db.delete(fav)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/favorites/reorder")
async def reorder_favorites(body: ReorderIn, user: CurrentUser, db: DbSession) -> dict:
    """즐겨찾기 순서변경(현재 유저 + kind 스코프). 부분/stale 목록이어도 전체 순열 재구성(간극 없음)."""
    rows = (
        (
            await db.execute(
                select(UserCodeFavorite)
                .where(UserCodeFavorite.user_id == user.id, UserCodeFavorite.kind == body.kind)
                .order_by(UserCodeFavorite.sort_order.asc(), UserCodeFavorite.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    reorder_by_client_order(rows, body.orderedIds)
    await db.commit()
    return await list_favorites(user, db, kind=body.kind)


@router.post("/favorites/{fav_id}/default")
async def set_default_favorite(fav_id: str, user: CurrentUser, db: DbSession):
    """대상 즐겨찾기의 '기본'을 **토글** — 지정 시 같은 kind 의 기존 default 해제(단일성),
    이미 기본이면 해제(사용자 요청 2026-07-04: 다시 클릭하면 해제).

    소유자 스코프. 대상이 없거나 소유자 불일치면 404. 갱신된 항목을 반환.
    """
    target = await get_owned_or_none(db, UserCodeFavorite, fav_id, user.id)
    if target is None:
        return JSONResponse({"error": "즐겨찾기를 찾을 수 없습니다."}, status_code=404)
    if target.is_default:
        # 토글 해제 — 그 kind 의 기본 없음 상태가 된다(에이전트는 비용구분 기본 등 폴백 사용).
        target.is_default = False
        await db.commit()
        return _fav_dict(target)
    # 같은 (user,kind) 의 기존 default 를 모두 해제한 뒤 대상만 true — 한 kind 당 1개만 유지.
    siblings = (
        (
            await db.execute(
                select(UserCodeFavorite).where(
                    UserCodeFavorite.user_id == user.id,
                    UserCodeFavorite.kind == target.kind,
                    UserCodeFavorite.is_default.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    for s in siblings:
        s.is_default = False
    # 해제 UPDATE 를 대상 지정보다 **먼저 방출**한다 — 한 플러시에 섞이면 SQLAlchemy UOW 가
    # UPDATE 를 uuid PK 정렬로 내보내 대상 지정이 먼저 나갈 수 있고, 그 순간 부분 유니크
    # 인덱스(uq_user_code_favorites_default, 0034) 위반으로 IntegrityError 가 난다.
    await db.flush()
    target.is_default = True
    await db.commit()
    return _fav_dict(target)


# ── 개입 학습(디버그 조회) ───────────────────────────────────────────────────────
def _merchant_rule_dict(r: MerchantDictRule) -> dict:
    return {
        "id": str(r.id),
        "keywords": [k.strip() for k in (r.keywords or "").split(",") if k.strip()],
        "category": r.category,
        "acct": r.acct,
        "strong": r.strong,
        "source": r.source,
        "sortOrder": r.sort_order,
        "enabled": r.enabled,
    }


class MerchantRuleIn(BaseModel):
    keywords: list[str] = Field(min_length=1)
    category: str = Field(min_length=1, max_length=120)
    acct: str | None = Field(default=None, max_length=120)
    strong: bool = False
    source: str = Field(default="큐레이션", max_length=40)
    sort_order: int = Field(default=0, alias="sortOrder")
    enabled: bool = True

    model_config = {"populate_by_name": True}


def _clean_keywords(kws: list[str]) -> str:
    cleaned = [k.strip().lower() for k in kws if k and k.strip()]
    if not cleaned:
        raise HTTPException(status_code=422, detail="키워드를 하나 이상 입력하세요.")
    if any("," in k for k in cleaned):
        raise HTTPException(status_code=422, detail="키워드에 콤마(,)는 쓸 수 없습니다.")
    return ",".join(cleaned)


@router.get("/merchant-dict")
async def list_merchant_dict(_user: CurrentUser, db: DbSession) -> dict:
    """가맹점 분류 사전(하이브리드) 규칙 목록 — 미등록 가맹점을 카드 표기명 키워드로 인식.

    개발 디버그·관리용. sort_order 오름차순(매칭 우선순위)으로 반환한다.
    """
    rows = (
        (
            await db.execute(
                select(MerchantDictRule).order_by(
                    MerchantDictRule.sort_order, MerchantDictRule.category
                )
            )
        )
        .scalars()
        .all()
    )
    return {"items": [_merchant_rule_dict(r) for r in rows], "total": len(rows)}


@router.post("/merchant-dict", status_code=status.HTTP_201_CREATED)
async def create_merchant_rule(body: MerchantRuleIn, _admin: RequireAdmin, db: DbSession) -> dict:
    """가맹점 사전 규칙 추가(관리자). 저장 후 매칭 캐시를 무효화한다."""
    rule = MerchantDictRule(
        keywords=_clean_keywords(body.keywords),
        category=body.category.strip(),
        acct=(body.acct or "").strip() or None,
        strong=body.strong,
        source=body.source.strip() or "큐레이션",
        sort_order=body.sort_order,
        enabled=body.enabled,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    _invalidate_merchant_cache()
    return _merchant_rule_dict(rule)


@router.patch("/merchant-dict/{rule_id}")
async def update_merchant_rule(
    rule_id: str, body: MerchantRuleIn, _admin: RequireAdmin, db: DbSession
) -> dict:
    """가맹점 사전 규칙 수정(관리자). 저장 후 매칭 캐시를 무효화한다."""
    rule = await _get_merchant_rule_or_404(db, rule_id)
    rule.keywords = _clean_keywords(body.keywords)
    rule.category = body.category.strip()
    rule.acct = (body.acct or "").strip() or None
    rule.strong = body.strong
    rule.source = body.source.strip() or "큐레이션"
    rule.sort_order = body.sort_order
    rule.enabled = body.enabled
    await db.commit()
    await db.refresh(rule)
    _invalidate_merchant_cache()
    return _merchant_rule_dict(rule)


@router.delete("/merchant-dict/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_merchant_rule(rule_id: str, _admin: RequireAdmin, db: DbSession) -> Response:
    """가맹점 사전 규칙 삭제(관리자). 삭제 후 매칭 캐시를 무효화한다."""
    rule = await _get_merchant_rule_or_404(db, rule_id)
    await db.delete(rule)
    await db.commit()
    _invalidate_merchant_cache()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _get_merchant_rule_or_404(db: object, rule_id: str) -> MerchantDictRule:
    try:
        rid = uuid.UUID(rule_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="규칙을 찾을 수 없습니다.")
    rule = (
        await db.execute(select(MerchantDictRule).where(MerchantDictRule.id == rid))
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="규칙을 찾을 수 없습니다.")
    return rule


def _invalidate_merchant_cache() -> None:
    from app.agents.card_collect.merchant_dict import invalidate_cache

    invalidate_cache()


@router.get("/card-learning")
async def list_card_learning(user: CurrentUser, db: DbSession) -> dict:
    """현재 사용자의 카드 개입 학습(가맹점→확정 선택) 목록 — 개발 디버그용(빈도·최근순).

    제작 중 'AI 가 무엇을 근거로 추천하는지' 확인용. 본인 데이터만 조회한다.
    """
    rows = (
        (
            await db.execute(
                select(CardLearnedSelection)
                .where(CardLearnedSelection.user_id == user.id)
                .order_by(
                    CardLearnedSelection.count.desc(),
                    CardLearnedSelection.last_used_at.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": str(r.id),
                "merchant": r.merchant,
                "normMerchant": r.norm_merchant,
                "budget": r.budget,
                "project": r.project,
                "note": r.note,
                "count": r.count,
                "lastUsedAt": r.last_used_at.isoformat() if r.last_used_at else None,
            }
            for r in rows
        ]
    }


@router.delete("/card-learning", status_code=status.HTTP_200_OK)
async def clear_card_learning(user: CurrentUser, db: DbSession) -> dict:
    """현재 사용자의 개입 학습 전체 삭제 — 개발 디버그용. 본인 데이터만. 반환 {deleted:n}."""
    res = await db.execute(
        delete(CardLearnedSelection).where(CardLearnedSelection.user_id == user.id)
    )
    await db.commit()
    return {"deleted": int(res.rowcount or 0)}


@router.delete("/card-learning/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_card_learning(item_id: str, user: CurrentUser, db: DbSession):
    """개입 학습 1건 삭제(소유자 스코프) — 대상 없거나 소유자 불일치면 404."""
    row = await get_owned_or_none(db, CardLearnedSelection, item_id, user.id)
    if row is None:
        return JSONResponse({"error": "학습 항목을 찾을 수 없습니다."}, status_code=404)
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/card-learning/seed")
async def list_card_seed(
    user: CurrentUser, db: DbSession, page: PageQuery, q: str | None = None
) -> dict:
    """전사 기초자료(seed, 가맹점→계정·적요) 목록 — 개발 디버그용. 공용 데이터(user 무관).

    개인 학습이 없을 때 AI 힌트·폴백으로 쓰는 전사 관례. q 로 가맹점 검색, 빈도순 페이지네이션
    (limit/offset — 수동 clamp 대신 PageQuery, 범위 밖=422). total 은 **필터 적용 후** 전체
    건수라 프론트가 페이지 수를 계산한다. 동빈도 타이는 norm_merchant 로 안정 정렬(페이지 간
    순서 흔들림 방지).
    """
    stmt = select(CardSeedSelection).order_by(
        CardSeedSelection.count.desc(), CardSeedSelection.norm_merchant
    )
    if q and q.strip():
        stmt = stmt.where(CardSeedSelection.merchant.ilike(f"%{q.strip()}%"))
    # count 는 rows 쿼리에서 파생(paginate) — 기존 count/rows 이중 필터 조립 대체.
    result = await paginate(db, stmt, page)
    rows = result.items
    # 가맹점별 계정 수(card_seed_notes) — 요약 행에 '계정 N개'로 표시해 다중 계정(구분 있는) 가맹점을
    # 바로 알아보고 펼칠 수 있게 한다. 현재 페이지 가맹점만 1회 grouped 조회.
    norms = [r.norm_merchant for r in rows]
    note_counts: dict[str, int] = {}
    if norms:
        nc = await db.execute(
            select(CardSeedNote.norm_merchant, func.count())
            .where(CardSeedNote.norm_merchant.in_(norms))
            .group_by(CardSeedNote.norm_merchant)
        )
        note_counts = {n: int(c) for n, c in nc.all()}

    def _item(r) -> dict:
        raw = r.note
        excluded = card_learning.is_person_name_note(raw)
        if excluded or not raw:
            note_disp, divided = None, False
        else:
            note_disp, divided = card_learning.strip_division(raw)
            note_disp = note_disp or None
        return {
            "id": str(r.id),
            "merchant": r.merchant,
            "normMerchant": r.norm_merchant,
            "acctCode": r.acct_code,
            "acctName": r.acct_name,
            "note": note_disp,
            "costDivided": divided,
            "excluded": excluded,
            "count": r.count,
            "dominance": r.dominance,
            "lastYear": r.last_year,
            "noteCount": note_counts.get(r.norm_merchant, 0),
        }

    return {
        "total": result.total,
        "limit": result.limit,
        "offset": result.offset,
        "items": [_item(r) for r in rows],
    }


@router.get("/card-learning/seed-notes")
async def list_card_seed_notes(user: CurrentUser, db: DbSession, norm: str) -> dict:
    """한 가맹점(norm_merchant)의 **계정별 순위 적요**(card_seed_notes) — 개발 디버그용.

    '공통' 시드는 가맹점당 최상위 1건(card_seed_selections)만 보여주지만, 실제 추천은 계정을
    바꾸면 그 계정에 맞는 적요(note-suggest → card_seed_notes)를 채운다. 이 엔드포인트는 그
    계정별 순위(빈도순=1·2·3순위)를 그대로 반환해 디버그 화면에서 펼쳐 볼 수 있게 한다.
    """
    rows = (
        await db.execute(
            select(CardSeedNote)
            .where(CardSeedNote.norm_merchant == norm)
            .order_by(CardSeedNote.count.desc(), CardSeedNote.acct_name)
        )
    ).scalars().all()
    return {"items": [_display_seed_note(r) for r in rows]}


def _display_seed_note(r) -> dict:
    """시드 적요 1행을 **추천과 동일하게 정규화**해 표시용으로 반환한다: 사람이름 적요는 제외
    (excluded=True, 적요 숨김), 판/제 구분은 떼어 base 로 보이고(costDivided=True면 접속자
    비용구분에 따라 판매/제조가 붙는다는 표시), 그 외는 원문 base."""
    raw = r.note
    excluded = card_learning.is_person_name_note(raw)
    if excluded or not raw:
        note_disp, divided = None, False
    else:
        note_disp, divided = card_learning.strip_division(raw)
        note_disp = note_disp or None
    return {
        "id": str(r.id),
        "acctCode": r.acct_code,
        "acctName": r.acct_name,
        "note": note_disp,
        "costDivided": divided,
        "excluded": excluded,
        "count": r.count,
        "dominance": r.dominance,
        "lastYear": r.last_year,
    }


# ── 계정 인지 적요 추천(카드 개입: 예산단위 변경 시 그 계정 맞춤 적요) ────────────────
@router.get("/note-suggest")
async def note_suggest(
    user: CurrentUser,
    db: DbSession,
    merchant: str,
    acct: str | None = None,
    acctName: str | None = None,  # noqa: N803 — 프론트 camelCase 쿼리 파라미터와 맞춤.
) -> dict:
    """가맹점(+계정)으로 적요를 추천 — learned>seed>AI>category>heuristic 사다리.

    카드 개입 그리드에서 사람이 예산단위(=계정)를 바꾸면 그 계정에 맞는 적요를 즉시 재추천한다.
    사람이 트리거하는 경로라 allow_ai=True — learned/seed 에 (가맹점×계정) 실이력이 없는 미학습
    조합(예: 네이버파이낸셜 + 회의비)은 계정 이름(acctName)으로 AI 가 계정 맞춤 적요를 생성한다.
    merchant 필수, acct/acctName 선택(계정 없으면 키워드 휴리스틱만, acctName 없으면 AI 스킵).
    반환 {note, source} — source(learned·seed·ai·category·heuristic·null).

    반환 적요는 정규화된다: 사람이름 든 적요는 건너뛰고, 원본의 판/제 구분(-판매/-제품 등)은 떼어
    **접속자 소속 비용구분(판관비→판매 / 제조원가→제조)**으로 재부착한다(구분이 원래 있던 적요만).
    """
    cost_type = await user_cost_type(db, user)
    return await card_learning.suggest_note(
        db,
        user_id=user.id,
        merchant=merchant,
        acct_code=acct,
        acct_name=acctName,
        allow_ai=True,
        cost_type=cost_type,
    )


# ── 코드 카탈로그 조회 ──────────────────────────────────────────────────────────
@router.get("/trip-defaults")
async def get_trip_defaults(user: CurrentUser, db: DbSession) -> dict:
    """출장 실행 전 폼 기본값 — 소속 팀 비용구분(판/제)에 맞춘 기본 프로젝트 + 부서.

    조직 설정(팀 cost_type)과 프로젝트 기본값을 일치시킨다: 제조원가→PJT_NO 500 / 판관비→800.
    카드 자동화(collect 노드)와 동일 규칙(app.services.cost_project). 팀 미지정·구분 없음·
    카탈로그 미존재면 defaultProject=null(프론트가 기본지정 즐겨찾기로 폴백).
    """
    cost_type = await user_cost_type(db, user)
    project = await resolve_cost_project(cost_type)
    return {"costType": cost_type, "department": user.department, "defaultProject": project}


@router.get("/catalog")
async def get_catalog(
    user: CurrentUser,
    db: DbSession,
    page: PageQuery,
    kind: str,
    q: str | None = None,
    dept: str | None = None,
) -> dict:
    """공용 코드 카탈로그 조회. kind 필수. q=name/code 검색, 페이지네이션.

    limit/offset 은 수동 clamp 대신 PageQuery(범위 밖=422), envelope 는 page_slice 로 통일
    ({items,total,limit,offset} + syncedAt). 예산단위의 '내 부서' 필터는 dept 컬럼이 아니라
    **예산단위명 ↔ 부서명 정규화 매칭**(dept_matches_budget_name: '인사/기획팀' ↔ '인사기획팀')
    이다 — ERP 예산단위 목록은 전사 공통이고 이름이 곧 부서라서다. dept 파라미터: 없음=내 부서
    매칭(부서 없으면 전체), 'all'=전체, 그 외 값=그 부서명으로 매칭.
    """
    if kind not in _VALID_KINDS:
        return JSONResponse({"error": f"알 수 없는 kind: {kind}"}, status_code=422)

    # 두 kind 모두 조합/부가 필드 검색이 필요해 파이썬 필터(행 수천 건 이내라 충분).
    # 예산단위=사업계획·예산계정, 프로젝트=WBS요소명·위치·프로젝트번호까지 커버한다.
    rows = (
        (
            await db.execute(
                select(ErpCodeCatalog)
                .where(ErpCodeCatalog.kind == kind)
                .order_by(ErpCodeCatalog.name.asc(), ErpCodeCatalog.code.asc())
            )
        )
        .scalars()
        .all()
    )
    # 인메모리 필터는 'kind 당 수천 건 이내' 전제 — 임계 초과를 조기 감지해 DB 필터 전환
    # 시점을 놓치지 않게 한다(동작 불변, 경고만).
    if len(rows) > 10_000:
        logger.warning(
            "코드 카탈로그 kind=%s 행수 %d — 인메모리 필터 전제(수천 건)를 초과했습니다.",
            kind,
            len(rows),
        )

    if kind == "budget_unit":
        # '내 부서' 필터 — 예산단위명 정규화 매칭.
        if dept != "all":
            match_dept = dept or user.department
            if match_dept:
                rows = [r for r in rows if dept_matches_budget_name(match_dept, r.name)]
        # q — 예산단위명·사업계획명·예산계정명·코드 전체에서 부분 매칭.
        if q:
            ql = q.strip().lower()
            rows = [
                r
                for r in rows
                if ql in r.name.lower()
                or ql in r.code.lower()
                or ql in str((r.extra or {}).get("bizplanNm", "")).lower()
                or ql in str((r.extra or {}).get("bgacctNm", "")).lower()
            ]
    elif kind == "project" and q:
        # 프로젝트 — 프로젝트명(name)·코드 + WBS요소명·위치·프로젝트번호(extra)까지 부분 매칭.
        # 공백으로 나눈 단어는 AND — 'etr 2' 로 'ETRIBE ERP TEST 002' 를 찾는다(2026-08-28).
        terms = q.lower().split()
        rows = [
            r
            for r in rows
            if all(
                t in r.name.lower()
                or t in r.code.lower()
                or t in str((r.extra or {}).get("wbsNm", "")).lower()
                or t in str((r.extra or {}).get("loc", "")).lower()
                or t in str((r.extra or {}).get("pjtNo", "")).lower()
                for t in terms
            )
        ]
    elif kind == "partner" and q:
        # 거래처 — 거래처명(name)·코드 + 사업자번호(extra)까지 부분 매칭. 정렬은 기본 이름순.
        ql = q.strip().lower()
        rows = [
            r
            for r in rows
            if ql in r.name.lower()
            or ql in r.code.lower()
            or ql in str((r.extra or {}).get("bizNo", "")).lower()
        ]

    if kind == "project":
        # 프로젝트는 프로젝트번호(→WBS요소 번호) 순으로 정렬(이름순 아님 — 사용자 지정).
        rows = sorted(
            rows,
            key=lambda r: (
                str((r.extra or {}).get("pjtNo", "")),
                str((r.extra or {}).get("wbsNo", "")),
            ),
        )

    # 파이썬 인메모리 필터 경로 — page_slice 로 envelope 통일(limit/offset 키 additive 추가).
    result = page_slice(rows, page)

    # syncedAt 은 q/필터 무관하게 kind 전체의 최신 동기화 시각.
    synced_at = (
        await db.execute(
            select(func.max(ErpCodeCatalog.synced_at)).where(ErpCodeCatalog.kind == kind)
        )
    ).scalar()
    items = [{"code": r.code, "name": r.name, "extra": r.extra} for r in result.items]
    return {
        "items": items,
        "total": result.total,
        "limit": result.limit,
        "offset": result.offset,
        "syncedAt": synced_at.isoformat() if synced_at else None,
    }


# ── 헤드리스 동기화 트리거/상태 ─────────────────────────────────────────────────
# 실행 본체(세마포어·RAM 상태·erp_sync_runs 이력·run_semaphore 점유)는 services.erp_sync 공용
# 러너 — 관리자 /admin/erp-sync 및 일일 스케줄러와 같은 경로를 탄다(2026-09-02 통합).
@router.post("/catalog/sync", status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync(body: SyncIn, request: Request, user: CurrentUser):
    """카탈로그 동기화 트리거. 1슬롯 세마포어(진행 중이면 409). 백그라운드 실행 → 202."""
    if body.kind not in _VALID_KINDS:
        return JSONResponse({"error": f"알 수 없는 kind: {body.kind}"}, status_code=422)
    # 조직도(org_unit)는 관리자 전용 + 실제 ERP 계정 필요 — org_units 반영·사용자 재배치가
    # 조직/권한 데이터를 바꾸고, 로컬 admin 은 ERP 로그인이 없어 조직도를 스크레이프할 수 없다.
    # 백그라운드 스폰 전에 막는다(다른 kind 동작은 불변).
    if body.kind == "org_unit":
        actor_rank = role_rank(user.role.code if user.role is not None else None)
        if actor_rank < role_rank(ROLE_ADMIN):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="권한이 부족합니다.")
        if user.password_hash is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=erp_sync.ORG_UNIT_NEEDS_ERP_ACCOUNT_MSG,
            )
    password = _omnisol_password(request)
    if not password:
        return JSONResponse({"error": erp_sync.NO_CREDENTIALS_MSG}, status_code=409)
    started = await erp_sync.launch(
        request.app,
        [(body.kind, user.omnisol_userid, password)],
        trigger=erp_sync.TRIGGER_MANUAL,
        actor_user_id=user.id,
        sessionmaker=appdb.get_sessionmaker(),
    )
    if not started:
        return JSONResponse({"error": erp_sync.BUSY_MSG}, status_code=409)
    return {"started": True}


@router.get("/catalog/sync-status")
async def sync_status(request: Request, user: CurrentUser, db: DbSession, kind: str) -> dict:
    """동기화 상태(진행/마지막 결과) + DB 상의 syncedAt/count(kind 전체 — 카탈로그는 전사 공용)."""
    if kind not in _VALID_KINDS:
        return JSONResponse({"error": f"알 수 없는 kind: {kind}"}, status_code=422)
    sync_state = getattr(request.app.state, "catalog_sync_state", {})
    base = dict(sync_state.get(kind) or {"running": False})
    conds = [ErpCodeCatalog.kind == kind]
    synced_at = (
        await db.execute(select(func.max(ErpCodeCatalog.synced_at)).where(*conds))
    ).scalar()
    count = (
        await db.execute(select(func.count()).select_from(ErpCodeCatalog).where(*conds))
    ).scalar() or 0
    base["syncedAt"] = synced_at.isoformat() if synced_at else None
    base["count"] = count
    return base
