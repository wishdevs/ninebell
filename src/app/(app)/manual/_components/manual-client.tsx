'use client';

import Link from 'next/link';
import { RiBookOpenLine, RiErrorWarningLine } from '@remixicon/react';
import { PageHeader } from '@/components/ui/page-header';
import { Spinner } from '@/components/ui/spinner';
import { EmptyState } from '@/components/ui/empty-state';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import Image from 'next/image';
import { type Agent, filterByDebugMode } from '@/lib/data/agents';
import {
  AGENT_MANUAL_SECTIONS,
  AGENT_NODE_LABEL,
  GENERAL_MANUAL_SECTIONS,
  MANUAL_CONTENT,
  type ManualDocMeta,
  type ManualField,
  findGeneralDoc,
} from '@/lib/data/manual';
import { useDebugMode } from '@/lib/debug-mode';
import { useApiResource } from '@/app/(app)/_lib/use-api-resource';

/**
 * 메뉴얼 — 왼쪽 분류(섹션별 문서 목록) + 오른쪽 본문.
 *
 * 문서 목록은 정적 등록부(lib/data/manual.ts)가 기준이다 — 일반 문서
 * (GENERAL_MANUAL_SECTIONS) + 에이전트 문서(AGENT_MANUAL_SECTIONS, 종전 `GET /agents`
 * 파생 → 정적 전환 2026-08-13). **`GET /agents` 응답과 교집합을 취해** 조직구분
 * (AgentOrgAccess) 접근 필터를 재현한다. 각 문서는 `/manual/{id}` 고유 주소를
 * 가지며, `docId`가 없으면(/manual) 안내 화면을 보여준다.
 * (비인증 공개 분기는 개발환경 전용으로 잠시 있었다가 2026-08-14 회수 — 인증 필수.)
 */
export function ManualClient({ docId }: { docId?: string }) {
  const debugMode = useDebugMode();
  const { status, data, error, reload } = useApiResource<Agent[]>('/agents');

  // 에이전트 목록과 **동일 노출 규칙** — (1) `GET /agents` 응답에 있는 id 만
  // 남긴다(조직구분 접근 필터·hidden 제외를 서버와 동일 소스로 재현), (2) 디버그 전용
  // (agents.ts DEBUG_ONLY_AGENT_IDS)은 일반 모드에서 목차·본문 어디에도 나오지 않는다
  // (직접 /manual/{id} 도 미해석).
  const accessibleIds = data ? new Set(data.map((agent) => agent.id)) : null;
  const agentSections = AGENT_MANUAL_SECTIONS.map((section) => {
    // standalone(비-에이전트 부속 문서, 예: 발주 패턴)은 교집합 대상이 아니다 — 같은 분류의
    // 에이전트 문서가 하나라도 보일 때만 함께 노출한다(분류 접근권한을 그대로 따른다).
    const items = filterByDebugMode(
      accessibleIds
        ? section.items.filter((item) => item.standalone || accessibleIds.has(item.id))
        : section.items,
      debugMode,
    );
    const hasAgentDoc = items.some((item) => !item.standalone);
    return { label: section.label, items: hasAgentDoc ? items : [] };
  }).filter((section) => section.items.length > 0);

  // 목차 3단(seoya 원본 구조 복원 2026-08-14) — 최상위(일반·에이전트) 아래에 '에이전트'
  // 묶음만 하위 분류(결의서입력·구매팀·회계전표)를 갖는다. 그 묶음의 items(에이전트 실행과
  // 개입 = 특정 에이전트에 속하지 않는 공통 문서)가 하위 분류보다 **먼저** 온다.
  const tree = GENERAL_MANUAL_SECTIONS.map((section) => ({
    label: section.label,
    items: section.items,
    groups: section.label === AGENT_NODE_LABEL ? agentSections : undefined,
  }));

  // 선택 해석: 에이전트 문서 → 정적(비-에이전트) 문서 순 — 같은 주소 공간(/manual/{id}).
  const selectedAgentDoc = docId
    ? agentSections
        .flatMap((section) => section.items.map((item) => ({ sectionLabel: section.label, item })))
        .find(({ item }) => item.id === docId)
    : undefined;
  const selectedGeneral = !selectedAgentDoc && docId ? findGeneralDoc(docId) : undefined;
  const selected = selectedAgentDoc
    ? { sectionLabel: selectedAgentDoc.sectionLabel, title: selectedAgentDoc.item.name }
    : selectedGeneral
      ? { sectionLabel: selectedGeneral.sectionLabel, title: selectedGeneral.doc.name }
      : undefined;

  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-6">
      <PageHeader
        caption="도움말"
        title="메뉴얼"
        description="에이전트별 사용 방법을 설명하는 문서입니다. 목록에서 문서를 선택하세요."
      />

      {status === 'loading' ? (
        <div className="text-muted-foreground flex items-center justify-center gap-2 py-16 text-sm">
          <Spinner size={18} label="문서 목록 불러오는 중" />
          문서 목록을 불러오는 중…
        </div>
      ) : status === 'error' ? (
        <EmptyState
          icon={<RiErrorWarningLine size={18} aria-hidden />}
          title="문서 목록을 불러오지 못했습니다"
          description={error?.status === 0 ? '서버에 연결할 수 없습니다.' : (error?.message ?? '')}
          action={
            <Button variant="secondary" size="sm" onClick={reload}>
              다시 시도
            </Button>
          }
        />
      ) : (
        // "한 권의 문서" 레이아웃(2026-08-10) — 목차와 본문을 **한 카드**에 담아 앱
        // 사이드바와 구조적으로 격리한다(종전: 목차가 앱 네비와 같은 문법으로 떠 있어
        // 사이드바가 두 개로 보였다). 목차 열은 옅은 배경 + 세로 구분선으로 톤을 나눈다.
        <div className="border-border bg-surface overflow-hidden rounded-[var(--radius-lg)] border lg:grid lg:grid-cols-[240px_minmax(0,1fr)]">
          <nav
            aria-label="메뉴얼 목차"
            className="border-border/60 bg-muted/30 border-b p-4 lg:border-r lg:border-b-0"
          >
            {/* 모바일에선 목차가 본문 위에 전체 폭으로 쌓인다 — 항목이 20개라 뷰포트를 다 먹어
                문서를 골라도 본문이 화면 밖에 있었다. 45vh 로 캡해 목차는 제자리에서 스크롤하고
                본문 헤딩이 폴드 위로 올라오게 한다(lg 이상은 종전 sticky 그대로). */}
            <div className="flex max-h-[45vh] flex-col gap-5 overflow-y-auto lg:sticky lg:top-6 lg:max-h-none lg:overflow-visible">
              <p className="text-foreground-tertiary px-2 text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
                목차
              </p>
              {tree.map((node) => (
                <div key={node.label} className="flex flex-col gap-1">
                  {/* 최상위 라벨(일반·에이전트) — 항목보다 확실히 강하게(본문색 볼드). */}
                  <p className="text-foreground px-2 text-[13px] font-bold">{node.label}</p>
                  {node.items.map((item) => (
                    <DocLink key={item.id} item={item} active={item.id === docId} />
                  ))}
                  {node.groups?.map((group) => (
                    <div key={group.label} className="mt-2 flex flex-col gap-1">
                      {/* 하위 분류 라벨(결의서입력·구매팀·회계전표) — 최상위와 항목 사이 톤. */}
                      <p className="text-foreground-secondary px-2 pl-3 text-[12px] font-semibold">
                        {group.label}
                      </p>
                      {group.items.map((item) => (
                        <DocLink key={item.id} item={item} active={item.id === docId} />
                      ))}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </nav>

          {/* 본문 — 선택된 문서 헤딩 + 공백(준비 중) 본문. 하단 여백을 넉넉히 둬
                  끝까지 스크롤해도 마지막 문단이 화면 바닥에 붙지 않게 한다(2026-08-10). */}
          <section className="min-h-[420px] p-6 pb-28">
            {selected ? (
              <article className="flex max-w-[960px] flex-col gap-2">
                {selected.sectionLabel ? (
                  <p className="text-foreground-tertiary text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
                    {selected.sectionLabel}
                  </p>
                ) : null}
                <h2 className="text-foreground text-[length:var(--text-heading)] leading-tight font-semibold tracking-tight">
                  {selected.title}
                </h2>
                {(() => {
                  const content = docId ? MANUAL_CONTENT[docId] : undefined;
                  if (!content) {
                    return (
                      <p className="text-muted-foreground mt-4 text-sm leading-relaxed">
                        문서 준비 중입니다.
                      </p>
                    );
                  }
                  return (
                    <div className="mt-3 flex flex-col gap-10">
                      <p className="text-foreground-secondary text-[16px] leading-[1.8]">
                        {content.intro}
                      </p>
                      {content.sections.map((sec, secIndex) => (
                        <section key={sec.title} className="flex flex-col gap-3">
                          {/* 스텝 배지 — 제목의 수동 번호("1.") 대신 자동 번호를 원형으로. */}
                          <h3 className="text-foreground flex items-center gap-2.5 text-[17px] font-semibold tracking-tight">
                            <span className="bg-accent/10 text-accent grid size-7 shrink-0 place-items-center rounded-full text-[14px] font-bold">
                              {secIndex + 1}
                            </span>
                            {sec.title}
                          </h3>
                          {sec.paragraphs ? <SectionBody paragraphs={sec.paragraphs} /> : null}
                          {sec.image ? (
                            <figure className="flex flex-col gap-1.5">
                              {/* 메뉴얼 스크린샷은 1630×1000 캡처 규격(public/manual-assets) — 960 컨테이너에 축소 표시. */}
                              <Image
                                unoptimized
                                src={sec.image.src}
                                alt={sec.image.alt}
                                width={1630}
                                height={1000}
                                className="border-border h-auto w-full rounded-[var(--radius-md)] border"
                              />
                              {sec.image.caption ? (
                                <figcaption className="text-foreground-tertiary pt-0.5 text-[13px] leading-relaxed">
                                  {sec.image.caption}
                                </figcaption>
                              ) : null}
                            </figure>
                          ) : null}
                          {sec.fields ? <FieldList fields={sec.fields} /> : null}
                        </section>
                      ))}
                    </div>
                  );
                })()}
              </article>
            ) : docId ? (
              <EmptyState
                title="문서를 찾을 수 없습니다"
                description="주소가 잘못되었거나 삭제된 문서입니다. 목록에서 다시 선택하세요."
              />
            ) : (
              <EmptyState
                icon={<RiBookOpenLine size={18} aria-hidden />}
                title="문서를 선택하세요"
                description="목록에서 보고 싶은 메뉴얼을 선택하면 이곳에 내용이 표시됩니다."
              />
            )}
          </section>
        </div>
      )}
    </div>
  );
}

/**
 * 목차의 문서 링크 한 줄 — 트리 가이드라인(border-l) + 활성 액센트.
 *
 * 들여쓰기(ml-3)는 **모든 문서에 동일**하다(사용자 지정 2026-08-13). 하위 분류를 거치든
 * 최상위 묶음 직속이든(일반의 문서, 에이전트 실행과 개입) 문서는 한 깊이로 정렬한다 —
 * 분류 라벨만 계층을 나타내고 문서끼리는 형제로 보이게 하는 것이 의도다.
 */
function DocLink({ item, active }: { item: ManualDocMeta; active: boolean }) {
  return (
    <Link
      href={`/manual/${item.id}`}
      aria-current={active ? 'page' : undefined}
      className={cn(
        // 활성은 액센트 바 + 액센트 텍스트(앱 사이드바의 '흰 카드+링' 활성과 다른 문법으로 구별).
        'ml-3 border-l-2 py-1.5 pr-2 pl-3 text-[length:var(--text-body-sm)] transition-colors',
        active
          ? 'border-accent text-accent font-semibold'
          : 'border-border/60 text-muted-foreground hover:border-border-strong hover:text-foreground',
      )}
    >
      {item.name}
    </Link>
  );
}

/** 본문 문단 블록 — 불릿 목록 한 덩어리, 또는 ⚠ 경고 하나. */
type BodyBlock = { kind: 'list'; items: string[] } | { kind: 'warn'; text: string };

/**
 * 섹션 본문(2026-08-13) — 매뉴얼 문체에 맞춰 문단을 **불릿 목록**으로 낸다.
 * 연속한 일반 문단은 하나의 <ul> 로 묶고, ⚠ 접두 문단을 만나면 목록을 끊어
 * 경고 콜아웃을 끼운 뒤 다시 새 목록을 연다 — 원문 순서가 그대로 유지된다.
 * 경고는 목록 항목이 아니라 박스로 남긴다(본문에 묻히면 안 되는 안전 문구).
 */
function SectionBody({ paragraphs }: { paragraphs: string[] }) {
  const blocks: BodyBlock[] = [];
  for (const para of paragraphs) {
    if (para.startsWith('⚠')) {
      blocks.push({ kind: 'warn', text: para.replace(/^⚠\s*/, '') });
      continue;
    }
    const last = blocks[blocks.length - 1];
    if (last?.kind === 'list') last.items.push(para);
    else blocks.push({ kind: 'list', items: [para] });
  }

  return (
    <>
      {blocks.map((block, blockIndex) =>
        block.kind === 'warn' ? (
          <div
            key={blockIndex}
            className="border-warning/40 bg-warning/10 flex items-start gap-2.5 rounded-[var(--radius-md)] border px-4 py-3"
          >
            <RiErrorWarningLine size={17} aria-hidden className="text-warning mt-1 shrink-0" />
            <p className="text-foreground text-[15px] leading-[1.7]">{block.text}</p>
          </div>
        ) : (
          // ⚠ ul 에 flex 를 주면 li 의 display:list-item 이 죽어 불릿이 사라진다 — space-y 로 간격을 준다.
          <ul key={blockIndex} className="marker:text-foreground-tertiary list-disc space-y-2 pl-5">
            {block.items.map((item, itemIndex) => (
              <li
                key={itemIndex}
                className="text-foreground-secondary pl-1 text-[15px] leading-[1.8]"
              >
                {item}
              </li>
            ))}
          </ul>
        ),
      )}
    </>
  );
}

/**
 * 입력 항목 목록(2026-08-13 재설계) — 이름·꼬리표를 한 줄에 두고 설명을 아래에 흘리는
 * 정의 블록. 각 항목은 왼쪽 레일(목차와 같은 border-l 문법)로 묶는다.
 *
 * 종전 `grid-cols-[8.5rem_1fr]` 표를 버린 이유(실측, 1280/375 뷰포트):
 *   · 라벨 열이 136px 고정이라 '유형'·'금액' 같은 2~3자 이름에 폭을 낭비했다
 *     (본문 661px 중 설명 몫은 475px).
 *   · 이름 위에 꼬리표가 세로로 쌓여 dt 가 46px 가 되고, 한 줄짜리 설명 행까지
 *     75px 로 끌어올렸다 — 8항목 표가 604px.
 *   · 열 폭이 고정이라 모바일에서 접히지 않았다. 375px 에서 설명 열이 107px(줄당 7자)로
 *     눌리고 표 높이가 1049px 가 됐다.
 * 지금 구조는 고정 열이 없어 폭이 좁아지면 설명이 자연히 아래로 흐른다.
 */
function FieldList({ fields }: { fields: readonly ManualField[] }) {
  return (
    // 배경 없이 왼쪽 레일만으로 묶는다(사용자 지정 2026-08-13) — 채움을 빼도 레일이 반복되며
    // 하나의 참조 블록으로 읽히고, 본문 카드 위에 색면이 하나 줄어 페이지가 가벼워진다.
    // ml-5 는 위 불릿 목록의 pl-5 와 같은 값 — 레일이 불릿 본문과 같은 축에 서서
    // 섹션에 딸린 하위 블록으로 한 단 들여쓰인다.
    <dl className="ml-5 flex flex-col gap-3.5">
      {fields.map((field) => (
        <div key={field.name} className="border-border-strong/60 border-l-2 pl-3.5">
          {/* 이름 + 꼬리표를 한 줄에 — 좁아지면 wrap 으로 꼬리표만 아래로 내려간다. */}
          <dt className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-foreground text-[15px] font-semibold">{field.name}</span>
            {field.tag ? (
              // 패널을 뺐으므로 알약은 다시 muted 채움 — 흰 카드 위에서 회색 칩으로 읽힌다.
              <span className="bg-muted text-foreground-tertiary rounded-full px-2 py-0.5 text-[11px] whitespace-nowrap">
                {field.tag}
              </span>
            ) : null}
          </dt>
          <dd className="text-foreground-secondary mt-1 text-[15px] leading-[1.7]">{field.desc}</dd>
        </div>
      ))}
    </dl>
  );
}
