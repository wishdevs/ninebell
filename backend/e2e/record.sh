#!/bin/sh
# 옴니솔 플로우 녹화 헬퍼 — flow-buildout 단계 1 입력을 만든다.
#
#   ./e2e/record.sh <flow-name> [--reuse]
#     <flow-name>  녹화 파일 이름(예: eap_cancel) → e2e/artifacts/<flow-name>_codegen.py
#     --reuse      직전 녹화의 로그인 세션을 재사용(로그인 단계 생략)
#
# 브라우저를 닫으면 파일이 저장된다. 저장 위치는 gitignore 대상인 e2e/artifacts/ 고정.
#
# ⚠ 녹화 파일에는 **로그인 비밀번호가 평문으로 남는다**. artifacts 밖으로 옮기지 말고,
#   이식이 끝나면 지운다. 이식한 스크립트는 반드시 env(E2E_USERID/E2E_PASSWORD)로 바꾼다.
# ⚠ 녹화는 메뉴 경로·버튼·팝업까지만 확정한다. 캔버스 그리드 셀 입력·성공 판정 신호·
#   타이밍·행 구조는 여전히 프로브가 필요하다(references/1b-codegen-recording.md).
set -e

cd "$(dirname "$0")/.." || exit 1

FLOW="$1"
if [ -z "$FLOW" ]; then
  echo "usage: ./e2e/record.sh <flow-name> [--reuse]" >&2
  exit 2
fi

BASE="${ERP_BASE:-https://erp.ninebell.co.kr}"
ART="e2e/artifacts"
OUT="$ART/${FLOW}_codegen.py"
STATE="$ART/${FLOW}_state.json"
mkdir -p "$ART"

set -- --target python-async -o "$OUT" --save-storage "$STATE"
if [ "$2" = "--reuse" ] && [ -f "$STATE" ]; then
  set -- "$@" --load-storage "$STATE"
  echo "[record] 로그인 세션 재사용: $STATE"
fi

echo "[record] $BASE → $OUT"
echo "[record] 플로우를 실제로 클릭한 뒤 브라우저를 닫으면 저장됩니다."
.venv/bin/playwright codegen "$BASE" "$@"

echo "[record] 저장 완료: $OUT"
echo "[record] ⚠ 이 파일에는 비밀번호가 평문으로 들어 있습니다 — 커밋 금지, 이식 후 삭제하세요."
