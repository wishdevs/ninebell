"""에이전트 시드 픽스처 — 프론트 `src/lib/data/agents.ts`·`flows.ts` 의 5개 에이전트 이식.

타임스탬프는 프론트와 동일 앵커(NOW_ANCHOR = 2026-06-30T14:00:00+09:00 = 05:00Z)에서
상대 오프셋으로 계산해 화면 연속성을 유지한다(프론트 relativeFromNow 와 동일 의미).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

_ANCHOR = datetime(2026, 6, 30, 5, 0, 0, tzinfo=UTC)  # = 2026-06-30T14:00:00+09:00


def rel(*, minutes: int = 0, hours: int = 0, days: int = 0) -> datetime:
    return _ANCHOR - timedelta(minutes=minutes, hours=hours, days=days)


def _iso(*, minutes: int = 0, hours: int = 0, days: int = 0) -> str:
    return rel(minutes=minutes, hours=hours, days=days).isoformat()


# ── 법인카드 지출결의 플로우 그래프 (flows.ts CORPORATE_CARD_FLOW 이식) ──────
_STEP_X = 212
_BASE_Y = 160


def _col(i: int) -> dict:
    return {"x": i * _STEP_X, "y": _BASE_Y}


CORPORATE_CARD_FLOW: dict = {
    "nodes": [
        {"id": "access", "kind": "start", "status": "done", "title": "결의서 입력 접속", "sub": "전사공통(회계)", **_col(0)},
        {"id": "kind", "kind": "step", "status": "done", "title": "결의구분 = 카드", "sub": "추가(F3)", **_col(1)},
        {"id": "date", "kind": "step", "status": "done", "title": "회계일자 세팅", "sub": "카드 사용 월", **_col(2)},
        {"id": "ev", "kind": "step", "status": "done", "title": "증빙유형 선택", "sub": "01 매입 / 02 불공", **_col(3)},
        {"id": "card", "kind": "step", "status": "done", "title": "카드내역 조회·적용", "sub": "승인일→조회→적용", **_col(4)},
        {"id": "vat", "kind": "decision", "status": "done", "title": "부가세 구분", "sub": "간이·빈칸이면 02", **_col(5)},
        {"id": "both", "kind": "decision", "status": "done", "title": "매입·불공 동시?", "sub": "둘 다면 행 분리 등록", **_col(6)},
        {"id": "rowMae", "kind": "step", "status": "done", "title": "매입 행 입력", "sub": "증빙유형 01 매입", **_col(7)},
        {"id": "rowAdd", "kind": "step", "status": "done", "title": "F3 줄 추가", "sub": "불공용 행 추가", **_col(8)},
        {"id": "rowBul", "kind": "step", "status": "done", "title": "불공 행 입력", "sub": "증빙유형 02 불공", **_col(9)},
        {"id": "budget", "kind": "step", "status": "done", "title": "예산계정 매핑", "sub": "항목별 계정 선택", **_col(10)},
        {"id": "project", "kind": "step", "status": "done", "title": "프로젝트·일괄적용", "sub": "취소 내역 포함", **_col(11)},
        {"id": "memo", "kind": "step", "status": "active", "title": "적요 작성", "sub": "자금예정일 매핑", **_col(12)},
        {"id": "save", "kind": "step", "status": "pending", "title": "저장(F7)", "sub": "결의번호 생성", **_col(13)},
        {"id": "warn", "kind": "decision", "status": "pending", "title": "저장 시 경고?", "sub": "회계일자 확인", **_col(14)},
        {"id": "submit", "kind": "end", "status": "pending", "title": "전자결재 상신", "sub": "회계팀 + 증빙", **_col(15)},
    ],
    "edges": [
        {"id": "e-access-kind", "source": "access", "target": "kind"},
        {"id": "e-kind-date", "source": "kind", "target": "date"},
        {"id": "e-date-ev", "source": "date", "target": "ev"},
        {"id": "e-ev-card", "source": "ev", "target": "card"},
        {"id": "e-card-vat", "source": "card", "target": "vat"},
        {"id": "e-vat-both", "source": "vat", "target": "both", "label": "아니오 · 과세", "kind": "branch"},
        {"id": "e-vat-ev", "source": "vat", "target": "ev", "label": "예 ↩ 02", "kind": "loop"},
        {"id": "e-both-mae", "source": "both", "target": "rowMae", "label": "예 · 둘 다", "kind": "branch"},
        {"id": "e-mae-add", "source": "rowMae", "target": "rowAdd"},
        {"id": "e-add-bul", "source": "rowAdd", "target": "rowBul"},
        {"id": "e-bul-budget", "source": "rowBul", "target": "budget"},
        {"id": "e-both-budget", "source": "both", "target": "budget", "label": "아니오 · 한 종류", "kind": "skip"},
        {"id": "e-budget-project", "source": "budget", "target": "project"},
        {"id": "e-project-memo", "source": "project", "target": "memo"},
        {"id": "e-memo-save", "source": "memo", "target": "save"},
        {"id": "e-save-warn", "source": "save", "target": "warn"},
        {"id": "e-warn-submit", "source": "warn", "target": "submit", "label": "확인 후", "kind": "branch"},
    ],
}


# ── 5개 에이전트 ────────────────────────────────────────────────────────────
AGENT_FIXTURES: list[dict] = [
    {
        "id": "outbound-test",
        "name": "출고 데이터 테스트",
        "description": "로그인 → 메뉴 이동 → 조회 → 그리드 데이터 수집까지 자동 수행하는 읽기 전용 에이전트.",
        "drive": "browser",
        "interaction": "readonly",
        "target_system": "더존 옴니솔",
        "target_url": "erp.ninebell.co.kr",
        "status": "running",
        "progress": 58,
        "timeout_seconds": 120,
        "elapsed_seconds": 47,
        "current_action": "출고현황 그리드에서 84행을 읽는 중…",
        "run_count": 132,
        "success_rate": 99.2,
        "avg_seconds": 41,
        "last_run_at": rel(minutes=3),
        "flow_graph": None,
        "steps": [
            {"key": "login", "label": "로그인", "skill": "로그인", "status": "done", "detail": "더존 옴니솔 인증 후 세션 확보"},
            {"key": "usertype", "label": "유형 확인", "skill": "사용자 유형 확인", "status": "done", "detail": "법인/사업장·권한 유형 식별"},
            {"key": "menu", "label": "메뉴 이동", "skill": "메뉴 이동", "status": "done", "detail": "대상 업무 화면으로 이동"},
            {
                "key": "query", "label": "조회", "skill": "그리드 읽기", "status": "active",
                "detail": "기간·창고 조건으로 출고현황 조회",
                "substeps": [
                    {"label": "조회 조건 입력(기간/창고)", "status": "done"},
                    {"label": "조회 버튼 실행", "status": "done"},
                    {"label": "그리드 로딩 대기", "status": "active"},
                ],
            },
            {"key": "collect", "label": "데이터 수집", "skill": "그리드 읽기", "status": "pending", "detail": "그리드 행을 구조화 데이터로 추출"},
            {"key": "apply", "label": "결과 정리", "skill": None, "status": "pending", "detail": "수집 결과를 실행 이력에 기록"},
        ],
        "logs": [
            {"key": "l1", "at": _iso(minutes=3), "level": "info", "step": "로그인", "message": "더존 옴니솔 세션 시작"},
            {"key": "l2", "at": _iso(minutes=3), "level": "success", "step": "로그인", "message": "인증 성공 · 사용자 유형=법인"},
            {"key": "l3", "at": _iso(minutes=2), "level": "action", "step": "메뉴 이동", "message": "자재 > 출고현황 화면으로 이동"},
            {"key": "l4", "at": _iso(minutes=2), "level": "action", "step": "조회", "message": "조회 조건 입력: 기간=2026-06, 창고='본사'"},
            {"key": "l5", "at": _iso(minutes=1), "level": "info", "step": "조회", "message": "그리드 로딩 대기 중(84행 예상)"},
        ],
        "intervention": None,
    },
    {
        "id": "card-expense",
        "name": "법인카드 지출결의",
        "description": "결의서 입력 화면에서 카드 결의 행을 만들고 증빙유형·프로젝트를 사람 승인으로 선택한다.",
        "drive": "browser",
        "interaction": "approval",
        "target_system": "더존 옴니솔",
        "target_url": "erp.ninebell.co.kr",
        "status": "waiting_input",
        "progress": 46,
        "timeout_seconds": 180,
        "elapsed_seconds": 72,
        "current_action": "증빙유형 선택을 기다리는 중 — 사용자 승인 필요",
        "run_count": 57,
        "success_rate": 96.5,
        "avg_seconds": 88,
        "last_run_at": rel(minutes=12),
        "flow_graph": None,
        "steps": [
            {"key": "login", "label": "로그인", "skill": "로그인", "status": "done", "detail": "더존 옴니솔 인증 후 세션 확보"},
            {"key": "usertype", "label": "유형 확인", "skill": "사용자 유형 확인", "status": "done", "detail": "법인/사업장·권한 유형 식별"},
            {"key": "menu", "label": "메뉴 이동", "skill": "메뉴 이동", "status": "done", "detail": "대상 업무 화면으로 이동"},
            {"key": "row", "label": "결의행 생성", "skill": "필드 입력", "status": "done", "detail": "법인카드 승인내역에서 결의 대상 행 생성"},
            {
                "key": "evidence", "label": "증빙유형", "skill": "코드피커", "status": "active",
                "detail": "증빙유형 선택 — 사람 승인 지점",
                "substeps": [
                    {"label": "코드피커 열기", "status": "done"},
                    {"label": "증빙유형 후보 제시", "status": "done"},
                    {"label": "사용자 승인 대기", "status": "active"},
                ],
            },
            {"key": "project", "label": "프로젝트", "skill": "코드피커", "status": "pending", "detail": "프로젝트(검색형) 선택"},
            {"key": "apply", "label": "적용", "skill": None, "status": "pending", "detail": "입력값 적용(저장·상신은 사람이)"},
        ],
        "logs": [
            {"key": "l1", "at": _iso(minutes=12), "level": "success", "step": "로그인", "message": "인증 성공"},
            {"key": "l2", "at": _iso(minutes=11), "level": "action", "step": "메뉴 이동", "message": "회계 > 지출결의 입력 화면 이동"},
            {"key": "l3", "at": _iso(minutes=10), "level": "action", "step": "결의행 생성", "message": "법인카드 승인내역 3건 중 1건 결의행 생성"},
            {"key": "l4", "at": _iso(minutes=9), "level": "info", "step": "증빙유형", "message": "코드피커 열기 · 후보 4종 제시"},
            {"key": "l5", "at": _iso(minutes=9), "level": "warn", "step": "증빙유형", "message": "판단 필요 — 사용자 승인 대기"},
        ],
        "intervention": {
            "kind": "choice",
            "title": "증빙유형 선택",
            "prompt": "이 카드 결의 행에 적용할 증빙유형을 선택하세요. 선택 후 프로젝트 지정으로 이어집니다.",
            "options": [
                {"id": "ev-normal", "label": "일반경비", "hint": "대부분의 카드 지출"},
                {"id": "ev-entertain", "label": "접대비", "hint": "거래처 접대·경조사"},
                {"id": "ev-welfare", "label": "복리후생비", "hint": "임직원 복리후생"},
                {"id": "ev-education", "label": "교육훈련비", "hint": "교육·세미나·도서"},
            ],
            "messages": None,
            "placeholder": None,
        },
    },
    {
        "id": "card-chat",
        "name": "법인카드 지결 — 대화형 폼 채움",
        "description": "증빙·프로젝트 다음의 상세 필드를 자연어 한 문장으로 채운다. 부족하면 되묻는다.",
        "drive": "browser",
        "interaction": "conversational",
        "target_system": "더존 옴니솔",
        "target_url": "erp.ninebell.co.kr",
        "status": "waiting_input",
        "progress": 72,
        "timeout_seconds": 240,
        "elapsed_seconds": 151,
        "current_action": "상세 필드 입력을 위한 대화 입력을 기다리는 중",
        "run_count": 23,
        "success_rate": 89.1,
        "avg_seconds": 124,
        "last_run_at": rel(minutes=6),
        "flow_graph": CORPORATE_CARD_FLOW,
        "steps": [
            {"key": "access", "label": "결의서 입력 접속", "skill": "로그인·메뉴 이동", "status": "done", "detail": "전사공통(회계) 결의서 입력 화면 진입"},
            {"key": "kind", "label": "결의구분 = 카드", "skill": "필드 입력", "status": "done", "detail": "결의구분=카드 · 추가(F3)"},
            {"key": "date", "label": "회계일자 세팅", "skill": "필드 입력", "status": "done", "detail": "카드 사용 월을 먼저 입력"},
            {"key": "ev", "label": "증빙유형 선택", "skill": "코드피커", "status": "done", "detail": "01 매입 / 02 불공"},
            {"key": "card", "label": "카드내역 조회·적용", "skill": "그리드 읽기", "status": "done", "detail": "카드 → 승인일 → 조회 → 적용"},
            {"key": "vat", "label": "부가세 구분", "skill": "코드피커", "status": "done", "detail": "간이·빈칸이면 02 재선택(증빙유형으로 회귀)"},
            {
                "key": "both", "label": "매입·불공 동시?", "skill": "필드 입력", "status": "done",
                "detail": "한 카드 거래에 매입·불공이 함께면 둘을 별도 행으로 나눠 등록한다.",
                "substeps": [
                    {"label": "매입(01) 행 입력", "status": "done"},
                    {"label": "F3로 줄 추가", "status": "done"},
                    {"label": "불공(02) 별도 행 입력", "status": "done"},
                ],
            },
            {"key": "rowMae", "label": "매입 행 입력", "skill": "필드 입력", "status": "done", "detail": "증빙유형 01(매입) 행의 카드내역·금액 입력"},
            {"key": "rowAdd", "label": "F3 줄 추가", "skill": "필드 입력", "status": "done", "detail": "불공분을 담을 새 행을 F3로 추가"},
            {"key": "rowBul", "label": "불공 행 입력", "skill": "코드피커", "status": "done", "detail": "추가된 행을 증빙유형 02(불공)로 별도 등록"},
            {"key": "budget", "label": "예산계정 매핑", "skill": "코드피커", "status": "done", "detail": "사용 항목별 계정 선택"},
            {"key": "project", "label": "프로젝트·일괄적용", "skill": "코드피커", "status": "done", "detail": "취소 내역도 포함해 일괄적용"},
            {
                "key": "memo", "label": "적요 작성", "skill": "필드 입력", "status": "active",
                "detail": "적요·자금예정일 등 상세 필드를 대화로 채움",
                "substeps": [
                    {"label": "필수 필드 식별", "status": "done"},
                    {"label": "대화로 값 수집", "status": "active"},
                    {"label": "필드 매핑·입력", "status": "pending"},
                ],
            },
            {"key": "save", "label": "저장(F7)", "skill": "필드 입력", "status": "pending", "detail": "결의번호 자동 생성"},
            {"key": "warn", "label": "저장 시 경고?", "skill": None, "status": "pending", "detail": "회계일자·사용일 확인"},
            {"key": "submit", "label": "전자결재 상신", "skill": None, "status": "pending", "detail": "입력 적용까지만 — 저장·상신은 사람이"},
        ],
        "logs": [
            {"key": "l1", "at": _iso(minutes=6), "level": "success", "step": "증빙유형", "message": "증빙유형 적용: 일반경비"},
            {"key": "l2", "at": _iso(minutes=5), "level": "success", "step": "프로젝트", "message": "프로젝트 적용: 커머스 리뉴얼"},
            {"key": "l3", "at": _iso(minutes=4), "level": "action", "step": "상세 필드", "message": "필수 필드 식별: 적요, 사용부서, 금액"},
            {"key": "l4", "at": _iso(minutes=3), "level": "info", "step": "상세 필드", "message": "대화형 입력 대기 — 한 문장으로 입력 요청"},
        ],
        "intervention": {
            "kind": "chat",
            "title": "상세 필드 — 대화형 입력",
            "prompt": "남은 상세 필드를 한 문장으로 입력하면 에이전트가 알아서 채웁니다. 부족하면 되묻습니다.",
            "options": None,
            "placeholder": "예) 적요는 6월 팀 회식, 사용부서는 마케팅, 금액 184,000원",
            "messages": [
                {"id": "m1", "role": "agent", "at": _iso(minutes=4), "text": "상세 필드를 채울게요. 적요·사용부서·금액을 한 문장으로 알려주세요."},
                {"id": "m2", "role": "user", "at": _iso(minutes=3), "text": "적요는 6월 거래처 미팅 식대로 해줘"},
                {"id": "m3", "role": "agent", "at": _iso(minutes=3), "text": "적요=‘6월 거래처 미팅 식대’로 입력했어요. 사용부서와 금액도 알려주시겠어요?"},
            ],
        },
    },
    {
        "id": "card-md",
        "name": "법인카드 지출결의 MD",
        "description": "같은 업무를 매 단계 화면을 읽고 AI가 스스로 판단해 수행한다(비교·실험용).",
        "drive": "browser",
        "interaction": "autonomous",
        "target_system": "더존 옴니솔",
        "target_url": "erp.ninebell.co.kr",
        "status": "completed",
        "progress": 100,
        "timeout_seconds": 240,
        "elapsed_seconds": 167,
        "current_action": "적용 완료 — 최종 저장·상신은 사용자 확인 대기",
        "run_count": 11,
        "success_rate": 81.8,
        "avg_seconds": 167,
        "last_run_at": rel(hours=2),
        "flow_graph": None,
        "steps": [
            {"key": "login", "label": "로그인", "skill": "로그인", "status": "done", "detail": "더존 옴니솔 인증 후 세션 확보"},
            {"key": "usertype", "label": "유형 확인", "skill": "사용자 유형 확인", "status": "done", "detail": "법인/사업장·권한 유형 식별"},
            {"key": "menu", "label": "메뉴 이동", "skill": "메뉴 이동", "status": "done", "detail": "대상 업무 화면으로 이동"},
            {"key": "row", "label": "결의행 생성", "skill": "필드 입력", "status": "done", "detail": None},
            {"key": "evidence", "label": "증빙유형", "skill": "코드피커", "status": "done", "detail": None},
            {"key": "project", "label": "프로젝트", "skill": "코드피커", "status": "done", "detail": None},
            {"key": "apply", "label": "적용", "skill": None, "status": "done", "detail": "입력값 적용 완료"},
        ],
        "logs": [
            {"key": "l1", "at": _iso(hours=2, minutes=4), "level": "success", "step": "로그인", "message": "인증 성공"},
            {"key": "l2", "at": _iso(hours=2, minutes=2), "level": "action", "step": "증빙유형", "message": "AI 판단: 증빙유형=일반경비(신뢰도 0.92)"},
            {"key": "l3", "at": _iso(hours=2, minutes=1), "level": "action", "step": "프로젝트", "message": "AI 판단: 프로젝트=브랜드 사이트(신뢰도 0.76)"},
            {"key": "l4", "at": _iso(hours=2), "level": "success", "step": "적용", "message": "적용 완료 · 저장/상신 보류"},
        ],
        "intervention": None,
    },
    {
        "id": "bom-lookup",
        "name": "자재 BOM 조회",
        "description": "품목 BOM 구조를 조회해 구성 품목과 소요량을 수집하는 읽기 전용 에이전트.",
        "drive": "browser",
        "interaction": "readonly",
        "target_system": "더존 옴니솔",
        "target_url": "erp.ninebell.co.kr",
        "status": "idle",
        "progress": 0,
        "timeout_seconds": 120,
        "elapsed_seconds": 0,
        "current_action": "대기 중 — 실행을 시작하면 라이브 화면이 표시됩니다.",
        "run_count": 64,
        "success_rate": 98.4,
        "avg_seconds": 36,
        "last_run_at": rel(days=1),
        "flow_graph": None,
        "steps": [
            {"key": "login", "label": "로그인", "skill": "로그인", "status": "pending", "detail": "더존 옴니솔 인증 후 세션 확보"},
            {"key": "usertype", "label": "유형 확인", "skill": "사용자 유형 확인", "status": "pending", "detail": "법인/사업장·권한 유형 식별"},
            {"key": "menu", "label": "메뉴 이동", "skill": "메뉴 이동", "status": "pending", "detail": "대상 업무 화면으로 이동"},
            {"key": "query", "label": "조회", "skill": "그리드 읽기", "status": "pending", "detail": "품목코드로 BOM 조회"},
            {"key": "collect", "label": "데이터 수집", "skill": "그리드 읽기", "status": "pending", "detail": None},
            {"key": "apply", "label": "결과 정리", "skill": None, "status": "pending", "detail": None},
        ],
        "logs": [
            {"key": "l1", "at": _iso(days=1), "level": "info", "step": None, "message": "직전 실행 완료 · 구성품목 27건 수집"},
        ],
        "intervention": None,
    },
]
