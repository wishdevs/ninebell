"""ChangelogEntry ORM 모델 — 릴리스(버전) 단위 변경사항 기록.

대시보드/에이전트에 무엇이 추가·수정·삭제됐는지를 릴리스 단위로 묶어 남긴다.
본문(body_md)은 마크다운이며, 화면은 이를 그대로 렌더한다(추가/수정 섹션은 본문 안에서 표현).

작성은 대부분 Claude Code 가 커밋 후 `POST /changelog` 로 등록하고, 사람은 화면에서
검토·수정·삭제한다. status='draft' 는 관리자에게만 보이고, 'released' 만 전 사용자에게 노출된다.
released_at 이 표시·정렬 기준(최신순)이며, 등록 시각(created_at)과 별개로 지정할 수 있다.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, Date, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPkMixin


class ChangelogEntry(UuidPkMixin, Base, TimestampMixin):
    __tablename__ = "changelog_entries"

    # 릴리스 식별자(중복 불가). 예: "v1.4.0" 또는 "2026.07.28".
    version: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    # 한 줄 요약 제목. 예: "법인카드 에이전트 개선".
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # 마크다운 본문(### 추가 / ### 개선 / ### 주요 수정 등 섹션 포함).
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    # 잘못 저장·미저장·실행 불가·개인정보 등 '반드시 확인해야 할' 수정 포함 여부.
    # 목록 배지·필터가 본문을 파싱하지 않도록 구조화한 유일한 분류 필드(나머지는 본문 섹션).
    has_major_fix: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # 'draft'=관리자만 열람(작성 중), 'released'=전 사용자 공개.
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="released")
    # 릴리스 날짜 — 목록 정렬(내림차순)·화면 표기 기준.
    # '시각'이 아니라 '달력 날짜'라 Date 다. timestamptz 로 두면 KST↔UTC 왕복에서 하루가
    # 밀려(2026-07-28 → 2026-07-27T15:00Z) 수정 저장마다 날짜가 뒤로 걸어간다.
    released_at: Mapped[date] = mapped_column(Date, nullable=False, index=True)
