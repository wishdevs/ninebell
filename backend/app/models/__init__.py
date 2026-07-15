"""ORM 모델 패키지 — 모든 모델을 임포트해 mapper 등록 + Base.metadata 채움."""

from __future__ import annotations

from app.models.access_log import AccessLog
from app.models.agent import Agent
from app.models.agent_group import AgentGroup
from app.models.agent_intervention import AgentIntervention
from app.models.agent_log import AgentLog
from app.models.agent_run import AgentRun
from app.models.agent_step import AgentStep
from app.models.agent_template import AgentTemplate
from app.models.base import Base
from app.models.card_ai_note import CardAiNote
from app.models.card_learned_note import CardLearnedNote
from app.models.card_learned_selection import CardLearnedSelection
from app.models.card_seed_note import CardSeedNote
from app.models.card_seed_selection import CardSeedSelection
from app.models.erp_code_catalog import ErpCodeCatalog
from app.models.org_unit import AgentOrgAccess, OrgUnit
from app.models.permission import Permission
from app.models.role import Role
from app.models.role_permission import RolePermission
from app.models.user import User
from app.models.user_code_favorite import UserCodeFavorite

__all__ = [
    "Base",
    "User",
    "Role",
    "Permission",
    "RolePermission",
    "AccessLog",
    "Agent",
    "AgentGroup",
    "AgentStep",
    "AgentLog",
    "AgentIntervention",
    "AgentRun",
    "AgentTemplate",
    "OrgUnit",
    "AgentOrgAccess",
    "UserCodeFavorite",
    "ErpCodeCatalog",
    "CardLearnedSelection",
    "CardSeedSelection",
    "CardLearnedNote",
    "CardSeedNote",
    "CardAiNote",
]
