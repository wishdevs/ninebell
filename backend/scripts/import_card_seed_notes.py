"""전사 기초자료(법인카드 3년치 엑셀) → card_seed_notes 집계 임포터.

`import_card_seed.py`(가맹점 → 예산단위)와 **별개**로, **(가맹점 × 계정) 조합마다** 최근성 가중
최빈 적요를 골라 담는다. 카드 개입에서 사람이 예산단위(=계정)를 바꾸면 그 계정에 맞는 적요를
결정적으로 추천하기 위한 데이터. 최근 연도일수록 가중치를 크게(2^(year-BASE)) 줘서 규칙 변화를
반영한다. 지점은 통합하지 않는다(가맹점명 정규화 그대로 = 지점 단위).

`import_card_seed.py` 의 xls 읽기·`_year_of`·`_recency_weight`·컬럼 인덱스를 재사용하고,
`card_learning.norm_merchant` 로 가맹점 키를 만든다. 차이는 **집계 키가 (norm_merchant, acct_code)**
라는 점 — 같은 가맹점이라도 계정마다 별도 행/적요가 나온다.

사용:
    cd backend && .venv/bin/python scripts/import_card_seed_notes.py \
        "/path/AI자동화 법인카드 기초자료(230101~251231).xls" [--dry] [--to-db]

기본 동작: 집계 후 `app/data/card_seed_notes.json.gz` 로 write. --dry 는 집계·상위 표만(파일 미기록).
--to-db 는 gz write 에 더해 (norm_merchant, acct_code) 기준 DB upsert 도 수행.

멱등: (norm_merchant, acct_code) 유니크로 재실행 시 행별 upsert.
"""

from __future__ import annotations

import asyncio
import collections
import gzip
import json
import sys
from collections.abc import Iterable
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS_DIR.parent))  # backend 루트 (app.*)
sys.path.insert(0, str(_SCRIPTS_DIR))  # scripts (import_card_seed)

import xlrd  # noqa: E402
from sqlalchemy import select  # noqa: E402

# import_card_seed 의 xls 컬럼 인덱스·연도/가중 헬퍼를 그대로 재사용(DRY).
from import_card_seed import (  # noqa: E402
    C_ACCT_CODE,
    C_ACCT_NAME,
    C_DATE,
    C_MERCHANT,
    C_NOTE,
    _recency_weight,
    _year_of,
)

from app.config import get_settings  # noqa: E402
from app.db import dispose_engine, get_sessionmaker, init_engine  # noqa: E402
from app.models import CardSeedNote  # noqa: E402
from app.services.card_learning import norm_merchant  # noqa: E402

# gz 산출 경로 — 레포 커밋 시드(seed.seed_card_seed_notes 가 읽음).
GZ_PATH = _SCRIPTS_DIR.parent / "app" / "data" / "card_seed_notes.json.gz"

# 집계 레코드: (merchant, acct_code, acct_name, note, year).
Record = tuple[str, str, str, str, "int | None"]


def aggregate_rows(records: Iterable[Record]) -> list[dict]:
    """레코드 → (가맹점 × 계정) 조합별 최빈 적요 집계.

    집계 단위(조합 키) = (norm_merchant, acct_code). 같은 가맹점이라도 계정마다 별도 행이 나오고,
    각 행의 적요는 그 조합 안에서 최근성 가중 최빈. 계정코드 없는 레코드는 (가맹점 × 계정) 모델에
    맞지 않아 skip. 산출 dict: {norm_merchant, merchant, acct_code, acct_name, note, count,
    dominance, last_year}. dominance = 최빈적요 가중 / 그 조합 총가중.
    """
    note_w: dict[tuple[str, str], collections.Counter] = collections.defaultdict(collections.Counter)
    name_w: dict[tuple[str, str], collections.Counter] = collections.defaultdict(collections.Counter)
    total_w: dict[tuple[str, str], float] = collections.defaultdict(float)
    count: dict[tuple[str, str], int] = collections.defaultdict(int)
    last_year: dict[tuple[str, str], int] = {}
    sample: dict[tuple[str, str], tuple[int, str]] = {}  # 조합 → (year, raw merchant) 최근 표본

    for merch, acct_code, acct_name, note, year in records:
        merch = (merch or "").strip()
        key = norm_merchant(merch)
        acct_code = (acct_code or "").strip()
        if not key or not acct_code:
            continue  # 가맹점/계정코드 없으면 조합 키를 만들 수 없음.
        combo = (key, acct_code)
        w = _recency_weight(year)
        acct_name = (acct_name or "").strip()
        note = (note or "").strip()
        if note:
            note_w[combo][note] += w
        if acct_name:
            name_w[combo][acct_name] += w
        total_w[combo] += w
        count[combo] += 1
        if year:
            last_year[combo] = max(last_year.get(combo, 0), year)
        if combo not in sample or (year or 0) >= sample[combo][0]:
            sample[combo] = (year or 0, merch)

    out: list[dict] = []
    for combo, tw in total_w.items():
        norm, acct_code = combo
        top_note = note_w[combo].most_common(1)
        top_name = name_w[combo].most_common(1)
        top_note_w = top_note[0][1] if top_note else 0.0
        out.append(
            {
                "norm_merchant": norm,
                "merchant": sample[combo][1],
                "acct_code": acct_code,
                "acct_name": top_name[0][0] if top_name else None,
                "note": top_note[0][0] if top_note else None,
                "count": count[combo],
                "dominance": round(top_note_w / tw, 4) if tw else 0.0,
                "last_year": last_year.get(combo),
            }
        )
    return out


def _read_records(xls_path: str) -> list[Record]:
    """엑셀 전 시트 → 레코드 리스트(merchant, acct_code, acct_name, note, year)."""
    book = xlrd.open_workbook(xls_path)
    dm = book.datemode
    records: list[Record] = []
    for si in range(book.nsheets):
        sh = book.sheet_by_index(si)
        for r in range(1, sh.nrows):
            merch = str(sh.cell_value(r, C_MERCHANT)).strip()
            if not merch:
                continue
            records.append(
                (
                    merch,
                    str(sh.cell_value(r, C_ACCT_CODE)).strip(),
                    str(sh.cell_value(r, C_ACCT_NAME)).strip(),
                    str(sh.cell_value(r, C_NOTE)).strip(),
                    _year_of(sh.cell_value(r, C_DATE), dm),
                )
            )
    return records


def aggregate(xls_path: str) -> list[dict]:
    """엑셀 → (가맹점 × 계정) 조합별 집계 리스트."""
    return aggregate_rows(_read_records(xls_path))


def write_gz(rows: list[dict], path: Path = GZ_PATH) -> None:
    """집계 결과를 gzip+json 으로 write(ensure_ascii=False). seed 가 읽는 레포 커밋 포맷."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False)


async def upsert(rows: list[dict]) -> tuple[int, int]:
    """(norm_merchant, acct_code) 기준 upsert. 반환 (insert, update)."""
    ins = upd = 0
    async with get_sessionmaker()() as s:
        for row in rows:
            existing = (
                await s.execute(
                    select(CardSeedNote).where(
                        CardSeedNote.norm_merchant == row["norm_merchant"],
                        CardSeedNote.acct_code == row["acct_code"],
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                s.add(CardSeedNote(**row))
                ins += 1
            else:
                for k, v in row.items():
                    setattr(existing, k, v)
                upd += 1
        await s.commit()
    return ins, upd


def _print_report(rows: list[dict]) -> None:
    merchants = {r["norm_merchant"] for r in rows}
    print(
        f"집계: {len(rows)}개 (가맹점 × 계정) 조합 · 고유 가맹점 {len(merchants)}개 · "
        f"총 거래 {sum(r['count'] for r in rows)}"
    )
    top = sorted(rows, key=lambda r: -r["count"])[:12]
    print("상위 12 (거래순): 가맹점 · 계정 · 적요 · count")
    for r in top:
        print(
            f"  {r['merchant'][:18]:20} [{r['acct_code']:>6} {(r['acct_name'] or '')[:8]:8}] "
            f"n={r['count']:4} dom={r['dominance']:.2f} 적요='{(r['note'] or '')[:16]}'"
        )
    # 같은 가맹점이 복수 계정에 나오는 사례(핵심 검증) — 계정 수 많은 순 상위.
    by_merchant: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rows:
        by_merchant[r["norm_merchant"]].append(r)
    multi = sorted(
        ((m, rs) for m, rs in by_merchant.items() if len(rs) >= 2),
        key=lambda mr: -len(mr[1]),
    )
    print(f"\n복수 계정 가맹점: {len(multi)}개 (같은 가맹점이 2개 이상 계정에 등장)")
    for _m, rs in multi[:8]:
        name = sorted(rs, key=lambda r: -r["count"])[0]["merchant"][:16]
        combos = ", ".join(
            f"{(r['acct_name'] or r['acct_code'])[:8]}→'{(r['note'] or '')[:10]}'(n={r['count']})"
            for r in sorted(rs, key=lambda r: -r["count"])[:4]
        )
        print(f"  {name:18} [{len(rs)}계정] {combos}")


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    to_db = "--to-db" in sys.argv
    if not args:
        print("사용: import_card_seed_notes.py <xls_path> [--dry] [--to-db]", file=sys.stderr)
        raise SystemExit(2)
    rows = aggregate(args[0])
    _print_report(rows)
    if dry:
        print("\n[--dry] 파일/DB 미반영.")
        return
    write_gz(rows)
    print(f"\ngz write: {GZ_PATH} ({GZ_PATH.stat().st_size:,} bytes)")
    if to_db:
        init_engine(get_settings().database_url)
        ins, upd = await upsert(rows)
        print(f"upsert 완료: insert {ins} · update {upd}")
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
