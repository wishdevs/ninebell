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
  GENERAL_MANUAL_SECTIONS,
  MANUAL_CONTENT,
  findGeneralDoc,
} from '@/lib/data/manual';
import { useDebugMode } from '@/lib/debug-mode';
import { useApiResource } from '@/app/(app)/_lib/use-api-resource';
import { useOptionalCurrentUser } from '@/app/(app)/providers/user-provider';

/**
 * 메뉴얼 — 왼쪽 분류(섹션별 문서 목록) + 오른쪽 본문.
 *
 * 문서 목록은 정적 등록부(lib/data/manual.ts)가 기준이다 — 일반 문서
 * (GENERAL_MANUAL_SECTIONS) + 에이전트 문서(AGENT_MANUAL_SECTIONS, 종전 `GET /agents`
 * 파생 → 정적 전환 2026-08-13). 비로그인(dev 공개)은 API 의존 없이 정적 목록을
 * 그대로 렌더하고, **로그인 상태는 종전처럼 `GET /agents` 응답과 교집합을 취해**
 * 조직구분(AgentOrgAccess) 접근 필터를 그대로 재현한다. 각 문서는 `/manual/{id}`
 * 고유 주소를 가지며, `docId`가 없으면(/manual) 안내 화면을 보여준다.
 */
export function ManualClient({ docId }: { docId?: string }) {
  const debugMode = useDebugMode();
  // 로그인 여부 = UserProvider 존재(앱 셸 분기, manual/layout.tsx). 로그인 시에만
  // `GET /agents` 를 불러 백엔드 조직접근 필터(agent_visibility)를 목차에 반영한다.
  // 비로그인은 path null → 요청 0회·즉시 success(data null)로 정적 목록 경로.
  const me = useOptionalCurrentUser();
  const { status, data, error, reload } = useApiResource<Agent[]>(me ? '/agents' : null);

  // 에이전트 목록과 **동일 노출 규칙** — (1) 로그인 시 `GET /agents` 응답에 있는 id 만
  // 남긴다(조직구분 접근 필터·hidden 제외를 서버와 동일 소스로 재현), (2) 디버그 전용
  // (agents.ts DEBUG_ONLY_AGENT_IDS)은 일반 모드에서 목차·본문 어디에도 나오지 않는다
  // (직접 /manual/{id} 도 미해석).
  const accessibleIds = data ? new Set(data.map((agent) => agent.id)) : null;
  const agentSections = AGENT_MANUAL_SECTIONS.map((section) => ({
    label: section.label,
    items: filterByDebugMode(
      accessibleIds ? section.items.filter((item) => accessibleIds.has(item.id)) : section.items,
      debugMode,
    ),
  })).filter((section) => section.items.length > 0);
  const sections = [...GENERAL_MANUAL_SECTIONS, ...agentSections];

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
        description="에이전트별 사용 방법을 설명하는 문서입니다. 왼쪽 목록에서 문서를 선택하세요."
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
            <div className="flex flex-col gap-5 lg:sticky lg:top-6">
              <p className="text-foreground-tertiary px-2 text-[length:var(--text-caption)] font-medium tracking-[0.08em] uppercase">
                목차
              </p>
              {sections.map((section) => (
                <div key={section.label} className="flex flex-col gap-1">
                  {/* 카테고리 라벨 — 항목보다 확실히 강하게(본문색 볼드). */}
                  <p className="text-foreground px-2 text-[13px] font-bold">{section.label}</p>
                  {section.items.map((item) => {
                    const active = item.id === docId;
                    return (
                      <Link
                        key={item.id}
                        href={`/manual/${item.id}`}
                        aria-current={active ? 'page' : undefined}
                        className={cn(
                          // 문서 트리 가이드라인(border-l) — 활성은 액센트 바 + 액센트 텍스트
                          // (앱 사이드바의 '흰 카드+링' 활성과 다른 문법으로 구별).
                          'border-l-2 py-1.5 pr-2 pl-3 text-[length:var(--text-body-sm)] transition-colors',
                          active
                            ? 'border-accent text-accent font-semibold'
                            : 'border-border/60 text-muted-foreground hover:border-border-strong hover:text-foreground',
                        )}
                      >
                        {item.name}
                      </Link>
                    );
                  })}
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
                          {sec.paragraphs?.map((para) =>
                            para.startsWith('⚠') ? (
                              // 경고 문단(⚠ 접두) — 본문에 묻히지 않게 콜아웃 박스로 격상.
                              <div
                                key={para.slice(0, 24)}
                                className="border-warning/40 bg-warning/10 flex items-start gap-2.5 rounded-[var(--radius-md)] border px-4 py-3"
                              >
                                <RiErrorWarningLine
                                  size={17}
                                  aria-hidden
                                  className="text-warning mt-1 shrink-0"
                                />
                                <p className="text-foreground text-[15px] leading-[1.7]">
                                  {para.replace(/^⚠\s*/, '')}
                                </p>
                              </div>
                            ) : (
                              <p
                                key={para.slice(0, 24)}
                                className="text-foreground-secondary text-[15px] leading-[1.8]"
                              >
                                {para}
                              </p>
                            ),
                          )}
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
                          {sec.fields ? (
                            <dl className="border-border divide-border divide-y rounded-[var(--radius-md)] border">
                              {sec.fields.map((field) => (
                                <div
                                  key={field.name}
                                  className="grid grid-cols-[8.5rem_1fr] gap-4 px-4 py-3.5"
                                >
                                  <dt className="flex flex-col items-start gap-1">
                                    <span className="text-foreground text-[15px] font-semibold">
                                      {field.name}
                                    </span>
                                    {field.tag ? (
                                      <span className="bg-muted text-foreground-tertiary rounded-full px-2 py-0.5 text-[11px]">
                                        {field.tag}
                                      </span>
                                    ) : null}
                                  </dt>
                                  <dd className="text-foreground-secondary text-[15px] leading-[1.7]">
                                    {field.desc}
                                  </dd>
                                </div>
                              ))}
                            </dl>
                          ) : null}
                        </section>
                      ))}
                    </div>
                  );
                })()}
              </article>
            ) : docId ? (
              <EmptyState
                title="문서를 찾을 수 없습니다"
                description="주소가 잘못되었거나 삭제된 문서입니다. 왼쪽 목록에서 다시 선택하세요."
              />
            ) : (
              <EmptyState
                icon={<RiBookOpenLine size={18} aria-hidden />}
                title="문서를 선택하세요"
                description="왼쪽 목록에서 보고 싶은 메뉴얼을 선택하면 이곳에 내용이 표시됩니다."
              />
            )}
          </section>
        </div>
      )}
    </div>
  );
}
