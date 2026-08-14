"""릴리스 노트 파일(app/data/releases/*.md) → changelog_entries 멱등 시드.

릴리스를 **리포 파일**로 관리하는 이유: main 푸시 하나가 AWS(ECS)와 온프렘 두 곳에 동시
배포되는데 DB 는 서로 다르다. API 로만 등록하면 한쪽에만 남는다. 파일로 두면 배포와 함께
따라가서 양쪽이 같은 변경 이력을 갖는다.

**insert-if-absent** 다 — version 이 이미 있으면 건드리지 않는다. 화면에서 고친 내용을
재시작이 덮어쓰지 않게 하기 위함이며, seed_card_seed_notes 등 기존 시드 관례와 같다.
파일을 고쳐서 반영하려면 화면에서 해당 릴리스를 지우고 재시작하거나 화면에서 직접 고친다.

파일 형식(frontmatter + 마크다운 본문):

    ---
    version: v1.2.0
    title: 외상매출금 에이전트 추가
    releasedAt: 2026-08-05
    hasMajorFix: false
    status: released
    ---

    ### 추가
    - **외상매출금** — ...

작성 규약(섹션·메이저/마이너 판정)은 docs/CHANGELOG-ENTRY.md 참조.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChangelogEntry

logger = logging.getLogger(__name__)

RELEASES_DIR = Path(__file__).resolve().parent.parent / "data" / "releases"

_REQUIRED = ("version", "title", "releasedAt")


@dataclass(frozen=True)
class ReleaseFile:
    version: str
    title: str
    released_at: date
    has_major_fix: bool
    status: str
    body_md: str


def _parse(text: str, source: str) -> ReleaseFile | None:
    """frontmatter + 본문 파싱. 형식이 깨지면 None(경고 후 건너뜀 — 스타트업 실패 방지)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        logger.warning("릴리스 파일 frontmatter 없음 — 건너뜀: %s", source)
        return None
    try:
        end = lines.index("---", 1)
    except ValueError:
        logger.warning("릴리스 파일 frontmatter 가 닫히지 않음 — 건너뜀: %s", source)
        return None

    meta: dict[str, str] = {}
    for raw in lines[1:end]:
        if not raw.strip():
            continue
        key, sep, value = raw.partition(":")  # 제목에 ':' 가 있어도 첫 구분자만 쓴다.
        if not sep:
            logger.warning("릴리스 파일 frontmatter 형식 오류(%s) — 건너뜀: %s", raw, source)
            return None
        meta[key.strip()] = value.strip()

    missing = [k for k in _REQUIRED if not meta.get(k)]
    if missing:
        logger.warning("릴리스 파일 필수 항목 누락%s — 건너뜀: %s", missing, source)
        return None

    body = "\n".join(lines[end + 1 :]).strip()
    if not body:
        logger.warning("릴리스 파일 본문 비어있음 — 건너뜀: %s", source)
        return None

    try:
        released_at = date.fromisoformat(meta["releasedAt"])
    except ValueError:
        logger.warning("릴리스 날짜 형식 오류(%s) — 건너뜀: %s", meta["releasedAt"], source)
        return None

    status = meta.get("status", "released")
    if status not in ("draft", "released"):
        logger.warning("릴리스 status 값 오류(%s) — 건너뜀: %s", status, source)
        return None

    return ReleaseFile(
        version=meta["version"],
        title=meta["title"],
        released_at=released_at,
        has_major_fix=meta.get("hasMajorFix", "false").lower() == "true",
        status=status,
        body_md=body + "\n",
    )


def load_release_files(directory: Path = RELEASES_DIR) -> list[ReleaseFile]:
    """디렉터리의 *.md 를 읽어 파싱 성공한 것만 날짜 오름차순으로 반환."""
    if not directory.exists():
        return []
    parsed = [
        rf
        for path in sorted(directory.glob("*.md"))
        if (rf := _parse(path.read_text(encoding="utf-8"), path.name)) is not None
    ]
    return sorted(parsed, key=lambda r: (r.released_at, r.version))


async def seed_changelog(db: AsyncSession, directory: Path = RELEASES_DIR) -> int:
    """없는 버전만 추가한다. 이미 있는 버전은 손대지 않는다(화면 수정 보존). 추가 건수 반환."""
    files = load_release_files(directory)
    if not files:
        return 0
    existing = set(
        (await db.execute(select(ChangelogEntry.version))).scalars().all()
    )
    added = 0
    for rf in files:
        if rf.version in existing:
            continue
        db.add(
            ChangelogEntry(
                version=rf.version,
                title=rf.title,
                body_md=rf.body_md,
                status=rf.status,
                has_major_fix=rf.has_major_fix,
                released_at=rf.released_at,
            )
        )
        added += 1
    if added:
        logger.info("릴리스 노트 %d건 시드됨(app/data/releases).", added)
    return added
