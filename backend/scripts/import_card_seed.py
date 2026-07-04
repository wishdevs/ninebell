"""전사 기초자료(법인카드 3년치 엑셀) → card_seed_selections 집계 임포터.

가맹점(정규화) 단위로 **최근성 가중** 최빈 계정과목·적요를 골라 upsert 한다. 최근 연도일수록
가중치를 크게(2^(year-BASE)) 줘서 조직·계정 규칙 변화를 반영한다(사용자 확정 2026-07-04:
'최근 데이터 우선'). 지점은 통합하지 않는다(가맹점명 정규화 그대로 = 지점 단위).

사용:
    cd backend && .venv/bin/python scripts/import_card_seed.py \
        "/path/AI자동화 법인카드 기초자료(230101~251231).xls" [--dry]

엑셀 컬럼(실측): 0=날짜(YYYY/MM/DD), 1=적요, 3=거래처명, 10=계정코드, 11=계정과목명.
멱등: norm_merchant 유니크로 재실행 시 갱신(기존 seed 전량 교체가 아니라 행별 upsert).
"""

from __future__ import annotations

import asyncio
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

import xlrd  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import dispose_engine, get_sessionmaker, init_engine  # noqa: E402
from app.models import CardSeedSelection  # noqa: E402
from app.services.card_learning import norm_merchant  # noqa: E402

# 최근성 가중 기준 연도 — 가중치 = 2^(year-BASE). 2023:1, 2024:2, 2025:4(최근이 2배씩).
RECENCY_BASE_YEAR = 2023
# 컬럼 인덱스(엑셀 실측).
C_DATE, C_NOTE, C_MERCHANT, C_ACCT_CODE, C_ACCT_NAME = 0, 1, 3, 10, 11


def _year_of(raw: object, datemode: int) -> int | None:
    """날짜 셀 → 연도. 'YYYY/MM/DD' 문자열 또는 xlrd 날짜(float) 모두 처리."""
    if isinstance(raw, float) and raw > 0:
        try:
            return xlrd.xldate_as_tuple(raw, datemode)[0]
        except Exception:  # noqa: BLE001
            return None
    s = str(raw).strip()
    if len(s) >= 4 and s[:4].isdigit():
        return int(s[:4])
    return None


def _recency_weight(year: int | None) -> float:
    if year is None:
        return 1.0
    return float(2 ** max(0, year - RECENCY_BASE_YEAR))


def aggregate(xls_path: str) -> list[dict]:
    """엑셀 전 시트 → 가맹점별 {norm_merchant, merchant, acct_code, acct_name, note, count,
    dominance, last_year} 집계 리스트. 최근성 가중 최빈으로 계정·적요 선정."""
    book = xlrd.open_workbook(xls_path)
    dm = book.datemode
    acct_w: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    note_w: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    total_w: dict[str, float] = collections.defaultdict(float)
    count: dict[str, int] = collections.defaultdict(int)
    last_year: dict[str, int] = {}
    sample: dict[str, tuple[int, str]] = {}  # norm → (year, raw name) — 최근 원문 표본

    for si in range(book.nsheets):
        sh = book.sheet_by_index(si)
        for r in range(1, sh.nrows):
            merch = str(sh.cell_value(r, C_MERCHANT)).strip()
            if not merch:
                continue
            key = norm_merchant(merch)
            if not key:
                continue
            year = _year_of(sh.cell_value(r, C_DATE), dm)
            w = _recency_weight(year)
            acct_code = str(sh.cell_value(r, C_ACCT_CODE)).strip()
            acct_name = str(sh.cell_value(r, C_ACCT_NAME)).strip()
            note = str(sh.cell_value(r, C_NOTE)).strip()
            if acct_name:
                acct_w[key][(acct_code, acct_name)] += w
            if note:
                note_w[key][note] += w
            total_w[key] += w
            count[key] += 1
            if year:
                last_year[key] = max(last_year.get(key, 0), year)
            # 표본 원문은 가장 최근 연도의 것을 남긴다(지점명 변화 대비).
            if key not in sample or (year or 0) >= sample[key][0]:
                sample[key] = (year or 0, merch)

    out: list[dict] = []
    for key, tw in total_w.items():
        acct = acct_w[key].most_common(1)
        note = note_w[key].most_common(1)
        top_acct_w = acct[0][1] if acct else 0.0
        out.append(
            {
                "norm_merchant": key,
                "merchant": sample[key][1],
                "acct_code": acct[0][0][0] if acct else None,
                "acct_name": acct[0][0][1] if acct else None,
                "note": note[0][0] if note else None,
                "count": count[key],
                "dominance": round(top_acct_w / tw, 4) if tw else 1.0,
                "last_year": last_year.get(key),
            }
        )
    return out


async def upsert(rows: list[dict]) -> tuple[int, int]:
    """norm_merchant 기준 upsert. 반환 (insert, update)."""
    ins = upd = 0
    async with get_sessionmaker()() as s:
        for row in rows:
            existing = (
                await s.execute(
                    select(CardSeedSelection).where(
                        CardSeedSelection.norm_merchant == row["norm_merchant"]
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                s.add(CardSeedSelection(**row))
                ins += 1
            else:
                for k, v in row.items():
                    setattr(existing, k, v)
                upd += 1
        await s.commit()
    return ins, upd


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    if not args:
        print("사용: import_card_seed.py <xls_path> [--dry]", file=sys.stderr)
        raise SystemExit(2)
    rows = aggregate(args[0])
    rows.sort(key=lambda r: -r["count"])
    print(f"집계: {len(rows)}개 가맹점 (총 거래 {sum(r['count'] for r in rows)})")
    print("상위 8 (거래순):")
    for r in rows[:8]:
        print(f"  {r['merchant'][:20]:22} n={r['count']:4} dom={r['dominance']:.2f} "
              f"y={r['last_year']} 계정={r['acct_name']} 적요='{(r['note'] or '')[:16]}'")
    if dry:
        print("[--dry] DB 미반영.")
        return
    init_engine(get_settings().database_url)
    ins, upd = await upsert(rows)
    print(f"upsert 완료: insert {ins} · update {upd}")
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
