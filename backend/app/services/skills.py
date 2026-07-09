"""공용 스킬 카탈로그 — 에이전트 스텝 `skill` 키의 단일 소스.

AgentStep.skill 은 여기 정의된 KEY(kebab-case)를 저장하고, 응답 직렬화 시
label 로 풀어 UI 에 노출한다(응답 shape 불변). 스텝이 새 스킬을 쓰면 반드시
여기에 먼저 등록한다 — tests/test_skills.py 가 픽스처 스킬 ∈ 카탈로그를 강제한다.

layer: 'omnisol'(더존 옴니솔 화면 조작) | 'common'(시스템 공통) | 'llm'(모델 판단).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillDef:
    key: str
    label: str
    description: str
    layer: str


def _skill(key: str, label: str, description: str, layer: str = "omnisol") -> SkillDef:
    return SkillDef(key=key, label=label, description=description, layer=layer)


SKILLS: dict[str, SkillDef] = {
    s.key: s
    for s in (
        _skill("login", "로그인", "더존 옴니솔에 인증해 작업 세션을 확보하는 공용 스킬."),
        _skill("user-type", "사용자 유형 확인", "사용자 패널에서 회계/인사 등 사용자 유형을 확인·전환하는 공용 스킬."),
        _skill("menu-nav", "메뉴 이동", "메뉴 트리를 탐색해 대상 업무 화면으로 진입하는 공용 스킬."),
        _skill("field-input", "필드 입력", "화면의 드롭다운·날짜·텍스트 필드에 값을 설정하는 공용 스킬."),
        _skill("codepicker", "코드피커", "코드 도움(돋보기) 팝업을 열어 코드 항목을 검색·선택하는 공용 스킬."),
        _skill("grid-read", "그리드 읽기", "조회 그리드의 행을 구조화 데이터로 읽어 보고하는 공용 스킬."),
        _skill("grid-input", "그리드 입력", "그리드 행별 셀 값을 채워 넣는 공용 스킬(사용자 개입 결합 가능)."),
        _skill(
            "budget-amount",
            "금액·예산 확인",
            "공급가액(거래금액)을 그리드 셀 에디터에 직접 타이핑하고 뜨는 예산현황 팝업을 확인해 반영하는 스킬. "
            "값만 주입(setValue)하면 예산 확인 트리거를 건너뛰어 저장이 거부되므로, 타이핑→커밋→예산현황 확인으로 "
            "처리해 공급가액·합계를 자동계산시킨다.",
        ),
        _skill(
            "subdetail-picker",
            "부가선택 코드피커",
            "결의 상세의 부가선택(관리항목) 위젯에서 상대계정거래처 등 항목을 돋보기로 검색·더블클릭해 등록하는 스킬. "
            "문서유형에 해당 항목이 없으면 자동으로 건너뛰고, 등록 시 딸려 추가되는 빈 상세행은 정리한다.",
        ),
        _skill("ai-recommend", "AI 추천", "행별 입력값(예산단위·프로젝트·적요)을 AI·개입학습 데이터로 추천하는 공용 스킬.", layer="llm"),
        _skill("doc-apply", "문서 반영", "선택한 행을 적용해 결의서 등 문서에 반영하는 공용 스킬."),
        _skill("save", "저장", "작성한 문서를 저장(F7)해 번호를 확정하는 공용 스킬."),
    )
}


def skill_label(key: str) -> str:
    """스킬 키 → 표시 라벨. 카탈로그에 없는 값(과거 자유 문자열)은 그대로 반환."""
    skill = SKILLS.get(key)
    return skill.label if skill is not None else key
