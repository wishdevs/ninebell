"""결재 배치 계획 — 하위(계정정보) 건수 기준으로 결재 그룹을 짠다(순수 함수·브라우저 무관).

사용자 규칙(2026-07-27, 외상매출금):
  1. 전체 대상 건수를 파악하고, 각 전표의 **하위 그리드 건수**를 파악한다.
  2. 하위 건수가 **단독으로 200 이상**인 전표는 **먼저 단독 결재**한다.
  3. 나머지는 여러 전표를 묶되 **합계가 200이 안 되도록**(< 200) 일괄 결재한다.

⚠ 건수를 못 읽은 행(count < 0)은 **단독 그룹**으로 뺀다 — 알 수 없는 값을 0으로 취급해 묶으면
  그 배치가 한도를 넘길 수 있다(모르면 안전한 쪽으로).

묶는 방식은 **조회 순서 그대로의 순차 그리디**다(정렬 재배치 없음). 결재 순서가 조회 화면의
순서와 같아야 사람이 로그·화면을 대조하기 쉽고, 재현성도 높다.
"""

from __future__ import annotations

from dataclasses import dataclass

# 사용자 확정 임계값 — 한 번의 결재에 담기는 하위 라인 합계 상한(이 값 '미만'까지 허용).
DETAIL_BATCH_LIMIT = 200


@dataclass(frozen=True)
class ApprovalTarget:
    """결재 대상 한 건 — 마스터 그리드 행 인덱스·전표번호·하위 건수."""

    idx: int
    docu_no: str | None
    count: int  # 하위(계정정보) 행수. < 0 = 읽지 못함.


@dataclass(frozen=True)
class ApprovalGroup:
    """한 번의 결재로 올릴 묶음."""

    targets: tuple[ApprovalTarget, ...]
    kind: str  # "solo"(단독 200↑) | "unknown"(건수 미상 단독) | "batch"(합계 < 200)

    @property
    def total(self) -> int:
        return sum(t.count for t in self.targets if t.count > 0)

    @property
    def docu_nos(self) -> list[str]:
        return [t.docu_no for t in self.targets if t.docu_no]

    @property
    def indexes(self) -> list[int]:
        return [t.idx for t in self.targets]


def plan_approval_groups(
    targets: list[ApprovalTarget], limit: int = DETAIL_BATCH_LIMIT
) -> list[ApprovalGroup]:
    """규칙대로 결재 그룹을 만든다 — 단독(200↑·미상)이 **먼저**, 그 뒤 합계 < limit 묶음들.

    반환 순서 = 실제 결재 순서. 각 묶음의 ``total`` 은 항상 ``limit`` 미만이다(단독 제외).
    """
    solo: list[ApprovalGroup] = []
    batches: list[ApprovalGroup] = []
    current: list[ApprovalTarget] = []
    running = 0

    def close_current() -> None:
        nonlocal current, running
        if current:
            batches.append(ApprovalGroup(tuple(current), "batch"))
            current, running = [], 0

    for t in targets:
        if t.count < 0:
            solo.append(ApprovalGroup((t,), "unknown"))  # 미상 → 안전하게 단독.
            continue
        if t.count >= limit:
            solo.append(ApprovalGroup((t,), "solo"))  # 단독으로 이미 한도 이상.
            continue
        if running + t.count >= limit:
            close_current()  # 이 건을 더하면 한도에 닿는다 → 현재 묶음을 끊는다.
        current.append(t)
        running += t.count
    close_current()
    return solo + batches
