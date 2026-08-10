"""릴리스 노트 파일 시드 — app/data/releases/*.md → changelog_entries.

리포 파일이 단일 소스라 AWS·온프렘 두 DB 가 같은 이력을 갖는다. 시드는 insert-if-absent —
이미 있는 버전은 손대지 않아 화면에서 고친 내용이 재시작에 덮이지 않는다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import ChangelogEntry
from app.services.changelog_seed import RELEASES_DIR, load_release_files, seed_changelog

# 파싱 테스트는 동기라 모듈 전역 asyncio 마크를 두지 않고 async 테스트에만 붙인다.


def _write(tmp_path: Path, name: str, text: str) -> Path:
    """릴리스 파일을 전용 하위 디렉터리에 쓴다(tmp_path 는 테스트 SQLite 파일과 공용)."""
    d = tmp_path / "releases"
    d.mkdir(exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")
    return d


VALID = """---
version: v9.9.0
title: 테스트 릴리스: 콜론 포함 제목
releasedAt: 2026-08-05
hasMajorFix: true
---

### 추가

- **공통** — 무언가
"""


def test_parses_frontmatter_and_body(tmp_path):
    files = load_release_files(_write(tmp_path, "v9.9.0.md", VALID))
    assert len(files) == 1
    rf = files[0]
    assert rf.version == "v9.9.0"
    assert rf.title == "테스트 릴리스: 콜론 포함 제목"  # 첫 ':' 만 구분자
    assert rf.released_at.isoformat() == "2026-08-05"
    assert rf.has_major_fix is True
    assert rf.status == "released"  # 생략 시 기본값
    assert rf.body_md.startswith("### 추가")


def test_skips_malformed_files_without_raising(tmp_path):
    _write(tmp_path, "a.md", "frontmatter 없음\n")
    _write(tmp_path, "b.md", "---\nversion: v1\n")  # 닫히지 않음
    _write(tmp_path, "c.md", "---\nversion: v1\ntitle: t\n---\n\n")  # 본문 없음
    _write(tmp_path, "d.md", "---\nversion: v1\ntitle: t\nreleasedAt: 어제\n---\n\nx\n")
    d = _write(tmp_path, "ok.md", VALID)
    files = load_release_files(d)
    assert [f.version for f in files] == ["v9.9.0"]  # 나머지는 건너뛰고 스타트업 계속


def test_sorted_by_release_date(tmp_path):
    _write(tmp_path, "z.md", VALID.replace("v9.9.0", "v9.9.1").replace("2026-08-05", "2026-09-01"))
    d = _write(tmp_path, "a.md", VALID)
    assert [f.version for f in load_release_files(d)] == ["v9.9.0", "v9.9.1"]


@pytest.mark.asyncio
async def test_seed_inserts_then_is_idempotent(sm, tmp_path):
    d = _write(tmp_path, "v9.9.0.md", VALID)
    async with sm() as db:
        assert await seed_changelog(db, d) == 1
        await db.commit()

        entry = (
            await db.execute(select(ChangelogEntry).where(ChangelogEntry.version == "v9.9.0"))
        ).scalar_one()
        assert entry.has_major_fix is True

        # 재시작(재시드)해도 추가 없음.
        assert await seed_changelog(db, d) == 0


@pytest.mark.asyncio
async def test_seed_does_not_overwrite_screen_edits(sm, tmp_path):
    d = _write(tmp_path, "v9.9.0.md", VALID)
    async with sm() as db:
        await seed_changelog(db, d)
        await db.commit()
        entry = (
            await db.execute(select(ChangelogEntry).where(ChangelogEntry.version == "v9.9.0"))
        ).scalar_one()
        entry.title = "화면에서 고친 제목"
        await db.commit()

        assert await seed_changelog(db, d) == 0
        await db.refresh(entry)
        assert entry.title == "화면에서 고친 제목"  # 파일이 덮어쓰지 않는다


@pytest.mark.asyncio
async def test_seed_all_loads_shipped_releases(sm):
    """conftest 의 seed_all 이 리포 릴리스 파일을 실제로 적재했는가."""
    async with sm() as db:
        versions = set((await db.execute(select(ChangelogEntry.version))).scalars().all())
    assert {p.version for p in load_release_files()} <= versions


def test_shipped_release_files_all_parse():
    """실제 리포에 들어있는 릴리스 파일이 전부 유효해야 한다(오타 방지 게이트)."""
    shipped = sorted(RELEASES_DIR.glob("*.md"))
    assert shipped, "app/data/releases 에 릴리스 파일이 없습니다."
    parsed = load_release_files()
    assert len(parsed) == len(shipped), "파싱에 실패한 릴리스 파일이 있습니다."
    versions = [p.version for p in parsed]
    assert len(versions) == len(set(versions)), f"버전 중복: {versions}"
