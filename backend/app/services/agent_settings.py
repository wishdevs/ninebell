"""에이전트별 세부설정 — 선언적 스키마(코드 단일 소스) + 저장값 오버레이/검증.

설정 항목의 정의(키·라벨·타입·기본값·범위)는 여기 AGENT_SETTINGS_SCHEMA 가 유일
소스이고, DB(agents.settings JSON)에는 관리자가 저장한 값만 담는다. 에이전트가
20개로 늘어도 이 딕셔너리에 SettingDef 목록을 추가하는 것으로 확장한다.

- effective_settings: 스키마 기본값 위에 저장값을 덮어 실효값을 만든다(미지 키 무시).
- validate_settings: 관리자 PATCH 입력을 스키마로 검증한다(위반 시 ValueError 한국어).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SettingDef:
    key: str
    label: str
    type: str  # 'number' (향후 'string' | 'boolean' 확장)
    default: int | str | bool
    description: str
    min: int | None = None
    max: int | None = None
    unit: str | None = None


# 에이전트 id → 설정 항목 정의 목록. 스키마가 없는 에이전트는 설정 기능 자체가 없다.
AGENT_SETTINGS_SCHEMA: dict[str, list[SettingDef]] = {
    "card-chat": [
        SettingDef(
            key="acct_cutoff_day",
            label="회계시점 결정일",
            type="number",
            default=9,  # 현행 동작(10일 미만=전월)과 동치 — N일까지 전월, N+1일부터 당월.
            min=1,
            max=28,
            unit="일",
            description=(
                "이 날까지는 전월 회계월로, 다음 날부터는 당월로 처리합니다. "
                "예: 4 → 4일까지 전월, 5일부터 당월."
            ),
        ),
    ],
}


def settings_schema_dicts(agent_id: str) -> list[dict] | None:
    """직렬화용 스키마(camelCase 키: key/label/type/default/min/max/unit/description).

    스키마가 없는 에이전트는 None(응답에 미포함 — 옵셔널 컨벤션).
    """
    defs = AGENT_SETTINGS_SCHEMA.get(agent_id)
    if defs is None:
        return None
    return [asdict(d) for d in defs]


def effective_settings(agent_id: str, stored: dict | None) -> dict:
    """스키마 기본값 위에 저장값을 오버레이한 실효 설정(스키마에 없는 키는 무시).

    스키마가 없는 에이전트는 빈 dict.
    """
    defs = AGENT_SETTINGS_SCHEMA.get(agent_id)
    if not defs:
        return {}
    stored = stored or {}
    return {d.key: stored.get(d.key, d.default) for d in defs}


def validate_settings(agent_id: str, incoming: dict) -> dict:
    """관리자 PATCH 입력 검증 — 키∈스키마·타입·min/max. 위반 시 ValueError(한국어).

    통과한 키만 담은 새 dict 를 반환한다(원본 불변).
    """
    defs = {d.key: d for d in AGENT_SETTINGS_SCHEMA.get(agent_id, [])}
    if not defs:
        raise ValueError("이 에이전트는 설정 항목이 없습니다.")
    validated: dict = {}
    for key, value in incoming.items():
        d = defs.get(key)
        if d is None:
            raise ValueError(f"알 수 없는 설정 항목입니다: {key}")
        if d.type == "number":
            # bool 은 int 의 서브클래스라 명시 배제(True 가 1로 저장되는 사고 방지).
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"'{d.label}' 값은 정수여야 합니다.")
            if d.min is not None and value < d.min:
                raise ValueError(f"'{d.label}' 값은 {d.min} 이상이어야 합니다.")
            if d.max is not None and value > d.max:
                raise ValueError(f"'{d.label}' 값은 {d.max} 이하여야 합니다.")
        else:  # 향후 'string' | 'boolean' 타입 추가 시 여기서 분기.
            raise ValueError(f"지원하지 않는 설정 타입입니다: {d.type}")
        validated[key] = value
    return validated
