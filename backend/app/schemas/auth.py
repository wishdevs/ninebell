"""인증 관련 요청/응답 스키마."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import CamelModel


class LoginBody(BaseModel):
    userid: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)
    # '로그인 상태 유지' — true 면 연장 세션(remember_ttl), false/미지정이면 기본(12h).
    remember: bool = False


class SignupBody(BaseModel):
    """POST /auth/signup — 로그인이 signupRequired 를 반환한 뒤 프론트가 제출.

    프론트는 camelCase 로 보낸다(signupToken/displayName/agreedTerms).
    displayName/department 는 로그인 프리필 값(사용자 수정 가능), email 은 필수 입력.
    """

    model_config = ConfigDict(populate_by_name=True)

    signup_token: str = Field(min_length=1, alias="signupToken")
    display_name: str = Field(min_length=1, max_length=255, alias="displayName")
    department: str | None = Field(default=None, max_length=255)
    # 지금은 선택 입력(누락/빈문자열 허용). 추후 필수화 예정.
    email: str | None = Field(default=None, max_length=320)
    agreed_terms: bool = Field(alias="agreedTerms")


class AuthMeUpdate(CamelModel):
    """PATCH /auth/me — 본인 프로필(이름/부서/이메일) 수정. 로그인 식별자·롤은 변경 불가."""

    display_name: str = Field(min_length=1, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    # 빈 문자열은 "이메일 지움"으로 취급(None 정규화는 라우터에서).
    email: str | None = Field(default=None, max_length=320)


class AuthMe(CamelModel):
    """GET /auth/me — 현재 사용자 + 평탄화된 권한."""

    id: str
    omnisol_userid: str
    display_name: str | None
    department: str | None
    email: str | None
    role: str
    permissions: list[str]
    last_login_at: datetime | None
