"""프로덕션 app.erp.api_client 를 실 ERP 로 검증 — 읽기 전용, DB 미접근.

code_sync 가 쓰는 바로 그 fetch_catalog_rows 를 세 kind 로 호출해 실제 수집 건수·행 shape 를
확인한다. 저장/상신 없음(조회 GET 만). 로그인 자격증명은 .env 의 E2E_USERID/E2E_PASSWORD.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/api_client_live_probe.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_ENV = Path(__file__).resolve().parents[1] / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(errors="ignore").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))

from app.erp import api_client  # noqa: E402

USERID = os.environ.get("E2E_USERID") or ""
PASSWORD = os.environ.get("E2E_PASSWORD") or ""


async def main() -> int:
    if not (USERID and PASSWORD):
        print("E2E_USERID / E2E_PASSWORD 를 .env 에 설정하세요.", file=sys.stderr)
        return 2
    ok = True
    for kind in ("budget_unit", "project", "partner"):
        try:
            rows = await api_client.fetch_catalog_rows(kind, USERID, PASSWORD)
        except Exception as exc:  # noqa: BLE001
            print(f"[{kind}] 실패: {exc}")
            ok = False
            continue
        sample = rows[0] if rows else None
        codes = {r["code"] for r in rows}
        print(f"[{kind}] {len(rows)}행 (고유 code {len(codes)})  sample={sample}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
