/**
 * 섹션 목차(앵커 내비게이션). 항목의 `id` 는 page.tsx 의 앵커 래퍼
 * `<div id=…>` 와 1:1 로 대응한다 — 섹션을 추가/삭제할 땐 두 곳을 함께 수정한다.
 */
const TOC_ITEMS = [
  { id: 'colors', label: '컬러' },
  { id: 'typography', label: '타이포그래피' },
  { id: 'depth', label: '깊이 · 레이어링' },
  { id: 'radius-shadow', label: '라운딩 · 그림자' },
  { id: 'motion', label: '모션' },
  { id: 'buttons', label: '버튼' },
  { id: 'badges', label: '배지 · 칩' },
  { id: 'domain-vocab', label: '도메인 상태 어휘' },
  { id: 'empty', label: '빈 상태' },
  { id: 'table-loading', label: '테이블 · 로딩' },
  { id: 'forms', label: '폼 · 탭' },
  { id: 'voice', label: '보이스 & 톤' },
] as const;

export function DesignSystemToc() {
  return (
    <nav aria-label="디자인 시스템 섹션 목차" className="flex flex-wrap gap-1.5">
      {TOC_ITEMS.map((item) => (
        <a
          key={item.id}
          href={`#${item.id}`}
          className="border-border bg-surface text-foreground-secondary hover:border-border-strong hover:text-foreground inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium transition-colors"
        >
          {item.label}
        </a>
      ))}
    </nav>
  );
}
