/**
 * 메뉴얼 문서 등록부 — 에이전트 외 문서의 자리(사용자 요청 2026-08-10).
 *
 * 메뉴얼의 왼쪽 분류는 두 소스를 합친다:
 *   1) 여기 정적 등록부(GENERAL_MANUAL_SECTIONS) — 에이전트가 아닌 문서(시작 안내·공통 기능 등)
 *   2) `GET /agents` 파생 섹션 — 에이전트별 사용 설명(manual-client 가 그룹으로 묶음)
 *
 * 새 비-에이전트 문서는 아래에 한 줄 추가하면 목록·고유 주소(/manual/{id})가 바로 생긴다.
 * 본문은 아직 전 문서 공통 "준비 중" — 콘텐츠 소스가 정해지면 id 로 연결한다.
 * ⚠ id 는 에이전트 id 와 같은 주소 공간을 쓴다 — 에이전트 id(card-chat 등)와 겹치지 않게 지을 것.
 */

export interface ManualDocMeta {
  id: string;
  name: string;
}

export interface ManualSectionDef {
  label: string;
  items: ManualDocMeta[];
}

export const GENERAL_MANUAL_SECTIONS: ManualSectionDef[] = [
  {
    label: '일반',
    items: [
      { id: 'getting-started', name: '대시보드 시작하기' },
      { id: 'run-and-intervene', name: '에이전트 실행과 개입' },
    ],
  },
];

/** 정적 등록부에서 id 로 문서를 찾는다(없으면 undefined). 섹션 라벨을 함께 돌려준다. */
export function findGeneralDoc(
  id: string,
): { sectionLabel: string; doc: ManualDocMeta } | undefined {
  for (const section of GENERAL_MANUAL_SECTIONS) {
    const doc = section.items.find((d) => d.id === id);
    if (doc) return { sectionLabel: section.label, doc };
  }
  return undefined;
}
