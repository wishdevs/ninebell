"""nbkit.browser — 앱-불문 브라우저 조작 프리미티브.

actions(재시도 click/fill/evaluate·실클릭) · waits(networkidle+폴백·조건 폴링) ·
frames(trusted 키보드) · detection(인증/팝업/요소카운트) · debug(스크린샷/콘솔).

모든 함수는 Playwright ``Page`` 를 느슨하게(``Any``) 받아 라이브 브라우저 없이도 import 된다.
"""

from __future__ import annotations
