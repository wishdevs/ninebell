"""세금계산서 codegen 녹화(2026-08-19)가 F7 저장한 잔존 전표 1건 정리 — 유일한 쓰기 액션.

재사용(신규 작성 아님): `e2e.product_cycle.erp_verify_and_delete` 그대로 — 결의구분 필터 조회 →
3중 가드(결의자=로그인계정 · 결의구분=fg_code · 미결 DOCU_NO 공백, `row_is_ours`) → 상세 대조 →
F6 삭제 → 잔존 0 확인까지 이미 구현돼 있다(hakjagum/gyeongjo 스모크 사이클과 동일 엔진).

fg_code="51" 은 tax_invoice_read_probe.py 실측(D3, 2026-08-19)으로 확정된 값.

Usage:
    cd /Users/wishdev/et-works/dashboard-design/backend
    .venv/bin/python e2e/tax_invoice_cleanup.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 루트

from e2e.product_cycle import erp_verify_and_delete  # noqa: E402

GUBUN_LABEL = "세금계산서"
TAX_INVOICE_FG = "51"  # tax_invoice_read_probe.py D3 실측(2026-08-19)


async def main() -> None:
    result = await erp_verify_and_delete(
        gubun_label=GUBUN_LABEL, fg_code=TAX_INVOICE_FG, tag="tax_invoice_cleanup", want_detail=True,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str), flush=True)
    ok = bool(result.get("before") == 1 and result.get("all_ours") and result.get("deleted") and result.get("after") == 0)
    print(f"\n[CLEANUP] {'PASS — 잔존 0' if ok else 'FAIL/확인 필요'}", flush=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
