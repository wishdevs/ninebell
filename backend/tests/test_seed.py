"""시드 멱등성 검증."""

from __future__ import annotations

import gzip
import json

from sqlalchemy import func, select

from app.core.permissions import ALL_PERMISSIONS, DEFAULT_ROLES
from app.models import CardSeedSelection, Permission, Role, RolePermission
from app.services.seed import _CARD_SEED_PATH, seed_all, seed_card_seeds


async def test_seed_is_idempotent(sm):
    # sm 픽스처가 이미 1회 시드함 → 한 번 더 실행해도 중복이 없어야 한다.
    async with sm() as s:
        await seed_all(s)
        await s.commit()

    async with sm() as s:
        perms = (await s.execute(select(func.count()).select_from(Permission))).scalar_one()
        roles = (await s.execute(select(func.count()).select_from(Role))).scalar_one()
        rps = (await s.execute(select(func.count()).select_from(RolePermission))).scalar_one()

    assert perms == len(ALL_PERMISSIONS)
    assert roles == 3
    expected_rps = sum(len(codes) for (_name, _desc, codes) in DEFAULT_ROLES.values())
    assert rps == expected_rps


async def test_super_admin_and_admin_have_identical_full_permissions(sm):
    async with sm() as s:
        roles = {r.code: r for r in (await s.execute(select(Role))).scalars()}
        sa_codes = {rp.permission.code for rp in roles["super_admin"].role_permissions}
        admin_codes = {rp.permission.code for rp in roles["admin"].role_permissions}
        user_codes = {rp.permission.code for rp in roles["user"].role_permissions}

    assert sa_codes == set(ALL_PERMISSIONS)
    assert admin_codes == set(ALL_PERMISSIONS)
    assert user_codes == {"agents:read", "agents:run"}


async def test_card_seed_loaded_from_file_and_idempotent(sm):
    """전사 카드 기초자료가 gz 시드 파일 전량으로 적재되고, 재실행해도 중복이 없어야 한다."""
    expected = len(json.loads(gzip.open(_CARD_SEED_PATH, "rb").read().decode("utf-8")))
    assert expected > 0  # 시드 파일 비어있지 않음(회귀 방지).

    # sm 픽스처가 seed_all(→ seed_card_seeds)을 1회 실행함 → 전량 적재돼 있어야 한다.
    async with sm() as s:
        n1 = (await s.execute(select(func.count()).select_from(CardSeedSelection))).scalar_one()
    assert n1 == expected

    # 비어있을 때만 넣으므로 재실행해도 중복 없음.
    async with sm() as s:
        await seed_card_seeds(s)
        await s.commit()
    async with sm() as s:
        n2 = (await s.execute(select(func.count()).select_from(CardSeedSelection))).scalar_one()
    assert n2 == expected
