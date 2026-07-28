'use client';

import { useCallback, useState } from 'react';
import { RiGitCommitLine } from '@remixicon/react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { DatePicker } from '@/components/ui/date-picker';
import { Dialog, DialogBody } from '@/components/ui/dialog';
import { FilterPill } from '@/components/ui/filter-pill';
import { FormField } from '@/components/ui/form-field';
import { InlineConfirm } from '@/components/ui/inline-confirm';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ListStatePanel } from '@/components/ui/list-state';
import { ListToolbar } from '@/components/ui/list-toolbar';
import { MarkdownContent } from '@/components/ui/markdown-content';
import { PageHeader } from '@/components/ui/page-header';
import { Pagination } from '@/components/ui/pagination';
import { SearchInput } from '@/components/ui/search-input';
import { SelectItem } from '@/components/ui/select-dropdown';
import { Spinner } from '@/components/ui/spinner';
import { StatusPill } from '@/components/ui/status-pill';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { usePermissions } from '@/hooks/use-permissions';
import { usePagedQuery, type Page } from '@/hooks/use-paged-query';
import { useListParams } from '@/hooks/use-list-params';
import { errorMessage } from '@/lib/api/client';
import {
  createChangelogEntry,
  deleteChangelogEntry,
  fetchChangelog,
  updateChangelogEntry,
  type ChangelogEntry,
  type ChangelogInput,
  type ChangelogStatus,
} from '@/lib/api/changelog';
import { ROLES, roleAtLeast } from '@/lib/auth/permissions';
import { cn } from '@/lib/utils';

const PAGE_SIZE = 20;

/**
 * 새 릴리스 작성 시 채워두는 본문 뼈대. 표준 섹션은 6개(추가·개선·주요 수정·수정·변경·
 * 보안·개인정보)지만, 매 릴리스에 다 쓰이지 않아 자주 쓰는 3개만 미리 넣는다.
 * 전체 섹션 정의와 제외 대상은 docs/CHANGELOG-ENTRY.md 참조.
 */
const BODY_TEMPLATE = '### 추가\n- \n\n### 개선\n- \n\n### 수정\n- \n';

/**
 * 버전 문자열이 릴리스 날짜를 그대로 담고 있는가(예: '2026.07.28' + releasedAt 2026-07-28).
 * 날짜식 버전을 쓰면 레일에 같은 날짜가 두 번 찍히므로, 이때만 날짜 줄을 숨긴다.
 * semver('v1.4.0') 처럼 날짜와 무관한 버전은 그대로 날짜를 함께 보여준다.
 */
function versionRepeatsDate(version: string, releasedAt: string): boolean {
  return version.replace(/\./g, '-') === releasedAt;
}

/**
 * 'yyyy-mm-dd' → '2026. 7. 28.'. 공용 formatDate 와 달리 Date 파싱을 거치지 않는다 —
 * 달력 날짜라 시간대와 무관하게 항상 같은 날짜를 찍어야 한다.
 */
function formatReleaseDate(ymd: string): string {
  const [y, m, d] = ymd.split('-');
  if (!y || !m || !d) return ymd;
  return `${y}. ${Number(m)}. ${Number(d)}.`;
}

/** 오늘 날짜를 로컬 기준 'yyyy-mm-dd' 로. DatePicker 값 규약과 동일. */
function todayIso(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/**
 * 변경사항(릴리스 노트) 타임라인 — 릴리스 단위 기록을 최신순으로 보여준다.
 * 조회는 로그인한 전원(백엔드가 일반 사용자에게는 released 만 반환), 추가/수정/삭제 UI 는
 * 관리자에게만 노출한다(백엔드가 최종 강제 — 여기선 UX 게이팅).
 * 파라미터·페칭·툴바·상태 3분기는 공용 레일(useListParams·usePagedQuery·ListToolbar·
 * ListStatePanel) 소유 — 이 파일은 타임라인 렌더와 작성 폼만 가진다.
 */
export function ChangelogClient() {
  const { role } = usePermissions();
  const isAdmin = roleAtLeast(role, ROLES.ADMIN);

  const {
    searchInput,
    setSearchInput,
    search,
    filters,
    setFilter,
    page,
    setPage,
    isFiltered,
    reset,
  } = useListParams({ filters: { status: 'all', major: 'all' } });

  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  // undefined = 다이얼로그 닫힘, null = 새 릴리스, ChangelogEntry = 수정 대상.
  const [editing, setEditing] = useState<ChangelogEntry | null | undefined>(undefined);

  // 상태 필터는 관리자에게만 의미가 있다(일반 사용자는 서버가 released 로 고정).
  const statusFilter = (isAdmin ? filters.status : 'all') as ChangelogStatus | 'all';
  // 'all' = 필터 없음(undefined), 'only' = 주요 수정 포함 릴리스만.
  const majorFilter = filters.major === 'only' ? true : undefined;

  const fetchPage = useCallback(
    async ({ limit, offset }: { limit: number; offset: number }): Promise<Page<ChangelogEntry>> => {
      const { items, total } = await fetchChangelog({
        limit,
        offset,
        q: search,
        status: statusFilter,
        hasMajorFix: majorFilter,
      });
      return { rows: items, total };
    },
    [search, statusFilter, majorFilter],
  );

  const { rows, total, phase, error, reload } = usePagedQuery(fetchPage, {
    page,
    pageSize: PAGE_SIZE,
    setPage,
  });

  async function removeOne(id: string) {
    setConfirmId(null);
    setBusyId(id);
    try {
      await deleteChangelogEntry(id);
      toast.success('릴리스를 삭제했습니다.');
      reload();
    } catch (err) {
      toast.error(errorMessage(err, '삭제하지 못했습니다.'));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="animate-page-enter flex max-w-[var(--content-max)] flex-col gap-8">
      <PageHeader
        caption="변경 이력"
        title="변경사항"
        description="대시보드와 에이전트에 무엇이 추가·수정됐는지를 릴리스 단위로 기록합니다."
        action={
          isAdmin ? (
            <Button variant="primary" size="sm" onClick={() => setEditing(null)}>
              릴리스 추가
            </Button>
          ) : null
        }
      />

      <ListToolbar isFiltered={isFiltered} onReset={reset}>
        <SearchInput
          value={searchInput}
          onChange={setSearchInput}
          placeholder="버전·제목·본문 검색"
          ariaLabel="변경사항 검색"
        />
        <FilterPill
          label="수정"
          ariaLabel="주요 수정 필터"
          value={filters.major}
          active={filters.major !== 'all'}
          onValueChange={(v) => setFilter('major', v)}
        >
          <SelectItem value="all">전체</SelectItem>
          <SelectItem value="only">주요 수정 포함</SelectItem>
        </FilterPill>
        {isAdmin ? (
          <FilterPill
            label="공개"
            ariaLabel="공개 상태 필터"
            value={filters.status}
            active={filters.status !== 'all'}
            onValueChange={(v) => setFilter('status', v)}
          >
            <SelectItem value="all">전체</SelectItem>
            <SelectItem value="released">배포됨</SelectItem>
            <SelectItem value="draft">미공개</SelectItem>
          </FilterPill>
        ) : null}
      </ListToolbar>

      <ListStatePanel
        phase={phase}
        error={error}
        loadingLabel="변경사항을 불러오는 중…"
        errorTitle="변경사항을 불러오지 못했습니다"
        onRetry={reload}
        isEmpty={rows.length === 0}
        empty={{
          icon: <RiGitCommitLine size={18} aria-hidden />,
          title: '기록된 변경사항이 없습니다',
          description: isFiltered
            ? '검색·필터 조건에 맞는 릴리스가 없습니다.'
            : isAdmin
              ? '‘릴리스 추가’로 첫 변경 기록을 남겨보세요.'
              : '아직 공개된 변경 기록이 없습니다.',
        }}
      >
        <div className="flex flex-col gap-6">
          <ol className="flex flex-col">
            {rows.map((entry) => (
              <li
                key={entry.id}
                className="group grid gap-2 pb-6 last:pb-0 md:grid-cols-[7rem_1.25rem_1fr] md:gap-x-4"
              >
                {/* 버전·날짜 — 타임라인의 시각적 앵커. */}
                <div className="flex items-baseline gap-2 md:flex-col md:items-end md:gap-1 md:pt-4">
                  <p className="text-foreground font-mono text-[length:var(--text-body-sm)] font-semibold tabular-nums">
                    {entry.version}
                  </p>
                  {versionRepeatsDate(entry.version, entry.releasedAt) ? null : (
                    <p className="text-foreground-tertiary text-xs tabular-nums">
                      {formatReleaseDate(entry.releasedAt)}
                    </p>
                  )}
                </div>

                {/* 연결선 + 노드 — 마지막 항목은 선을 노드에서 끊는다. 주요 수정이 있는
                    릴리스는 노드 색으로 표시해 레일만 훑어도 눈에 띄게 한다. */}
                <div className="relative hidden justify-center md:flex" aria-hidden>
                  <span className="bg-border absolute inset-y-0 w-px group-last:h-6" />
                  <span
                    className={cn(
                      'ring-background relative mt-[1.15rem] size-2.5 shrink-0 rounded-full ring-4',
                      entry.hasMajorFix ? 'bg-warning' : 'bg-accent',
                    )}
                  />
                </div>

                <article className="border-border bg-surface rounded-[var(--radius-lg)] border p-5 transition-shadow hover:shadow-sm">
                  <header className="flex flex-wrap items-start justify-between gap-3">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <h2 className="text-foreground text-[length:var(--text-body)] font-semibold">
                        {entry.title}
                      </h2>
                      <StatusPill
                        label={entry.status === 'released' ? '배포됨' : '미공개'}
                        variant={entry.status === 'released' ? 'success' : 'info'}
                      />
                      {entry.hasMajorFix ? (
                        <StatusPill label="주요 수정 포함" variant="warn" />
                      ) : null}
                    </div>

                    {isAdmin ? (
                      confirmId === entry.id ? (
                        <InlineConfirm
                          question="삭제할까요?"
                          confirmLabel="삭제"
                          onConfirm={() => removeOne(entry.id)}
                          onCancel={() => setConfirmId(null)}
                          disabled={busyId !== null}
                        />
                      ) : (
                        <div className="inline-flex shrink-0 items-center gap-1">
                          <button
                            type="button"
                            onClick={() => setEditing(entry)}
                            disabled={busyId !== null}
                            className="text-foreground-secondary hover:text-foreground hover:bg-muted rounded-[var(--radius-sm)] px-2 py-1 text-xs transition-colors disabled:opacity-40"
                          >
                            수정
                          </button>
                          <button
                            type="button"
                            onClick={() => setConfirmId(entry.id)}
                            disabled={busyId !== null}
                            aria-label={`${entry.version} 릴리스 삭제`}
                            className="text-foreground-tertiary hover:text-danger hover:bg-danger/10 rounded-[var(--radius-sm)] px-2 py-1 text-xs transition-colors disabled:opacity-40"
                          >
                            {busyId === entry.id ? <Spinner size={12} /> : '삭제'}
                          </button>
                        </div>
                      )
                    ) : null}
                  </header>

                  <div className="border-border/60 mt-4 border-t pt-4">
                    <MarkdownContent content={entry.bodyMd} />
                  </div>
                </article>
              </li>
            ))}
          </ol>

          <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
        </div>
      </ListStatePanel>

      {isAdmin && editing !== undefined ? (
        <ChangelogDialog
          key={editing?.id ?? '__new__'}
          initial={editing}
          onClose={() => setEditing(undefined)}
          onSaved={reload}
        />
      ) : null}
    </div>
  );
}

interface ChangelogDialogProps {
  /** null = 새 릴리스, ChangelogEntry = 수정. */
  initial: ChangelogEntry | null;
  onClose: () => void;
  onSaved: () => void;
}

/** 릴리스 추가/수정 폼. `key`로 대상별 리마운트되므로 초기값은 useState 초기화로 채운다. */
function ChangelogDialog({ initial, onClose, onSaved }: ChangelogDialogProps) {
  const isEdit = initial !== null;
  const [version, setVersion] = useState(initial?.version ?? '');
  const [title, setTitle] = useState(initial?.title ?? '');
  const [bodyMd, setBodyMd] = useState(initial?.bodyMd ?? BODY_TEMPLATE);
  const [releasedAt, setReleasedAt] = useState(initial?.releasedAt ?? todayIso());
  const [released, setReleased] = useState(initial ? initial.status === 'released' : true);
  const [hasMajorFix, setHasMajorFix] = useState(initial?.hasMajorFix ?? false);
  const [preview, setPreview] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit() {
    const v = version.trim();
    const t = title.trim();
    if (!v) {
      setError('버전을 입력해주세요. (예: v1.4.0)');
      return;
    }
    if (!t) {
      setError('제목을 입력해주세요.');
      return;
    }
    if (!bodyMd.trim()) {
      setError('본문을 입력해주세요.');
      return;
    }
    const payload: ChangelogInput = {
      version: v,
      title: t,
      bodyMd,
      status: released ? 'released' : 'draft',
      hasMajorFix,
      releasedAt,
    };
    setSaving(true);
    try {
      if (isEdit && initial) {
        await updateChangelogEntry(initial.id, payload);
        toast.success('릴리스를 수정했습니다.');
      } else {
        await createChangelogEntry(payload);
        toast.success('릴리스를 추가했습니다.');
      }
      onSaved();
      onClose();
    } catch (err) {
      toast.error(errorMessage(err, '저장하지 못했습니다.'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      size="xl"
      title={isEdit ? '릴리스 수정' : '릴리스 추가'}
      description="본문은 마크다운입니다. 표준 섹션은 추가 · 개선 · 주요 수정 · 수정 · 변경 · 보안·개인정보 6개이며, 해당 없는 섹션은 빼면 됩니다."
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={onClose} disabled={saving}>
            취소
          </Button>
          <Button variant="primary" size="sm" onClick={handleSubmit} disabled={saving}>
            {saving ? <Spinner size={14} /> : '저장'}
          </Button>
        </>
      }
    >
      <DialogBody>
        {error ? (
          <p role="alert" className="text-danger text-xs leading-relaxed">
            {error}
          </p>
        ) : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <FormField
            id="cl-version"
            label="버전"
            required
            hint="중복 불가. 예: v1.4.0 · 2026.07.28"
          >
            <Input
              id="cl-version"
              value={version}
              placeholder="v1.4.0"
              onChange={(e) => {
                setVersion(e.target.value);
                if (error) setError(null);
              }}
            />
          </FormField>

          <FormField id="cl-date" label="릴리스 날짜" hint="목록 정렬(최신순) 기준입니다.">
            <DatePicker value={releasedAt} onChange={setReleasedAt} ariaLabel="릴리스 날짜" />
          </FormField>
        </div>

        <FormField id="cl-title" label="제목" required hint="이번 릴리스를 한 줄로 요약합니다.">
          <Input
            id="cl-title"
            value={title}
            placeholder="법인카드 에이전트 개선"
            onChange={(e) => {
              setTitle(e.target.value);
              if (error) setError(null);
            }}
          />
        </FormField>

        <div className="grid gap-1.5">
          <div className="flex items-center justify-between gap-3">
            <Label htmlFor="cl-body">본문 (마크다운)</Label>
            <div className="inline-flex items-center gap-1">
              <button
                type="button"
                onClick={() => setPreview(false)}
                aria-pressed={!preview}
                className={
                  preview
                    ? 'text-foreground-tertiary hover:text-foreground hover:bg-muted rounded-[var(--radius-sm)] px-2 py-1 text-xs transition-colors'
                    : 'bg-muted text-foreground rounded-[var(--radius-sm)] px-2 py-1 text-xs font-medium'
                }
              >
                작성
              </button>
              <button
                type="button"
                onClick={() => setPreview(true)}
                aria-pressed={preview}
                className={
                  preview
                    ? 'bg-muted text-foreground rounded-[var(--radius-sm)] px-2 py-1 text-xs font-medium'
                    : 'text-foreground-tertiary hover:text-foreground hover:bg-muted rounded-[var(--radius-sm)] px-2 py-1 text-xs transition-colors'
                }
              >
                미리보기
              </button>
            </div>
          </div>

          {preview ? (
            <div className="border-border bg-surface min-h-[18rem] rounded-[var(--radius-md)] border p-4">
              {bodyMd.trim() ? (
                <MarkdownContent content={bodyMd} />
              ) : (
                <p className="text-foreground-tertiary text-xs">본문이 비어 있습니다.</p>
              )}
            </div>
          ) : (
            <Textarea
              id="cl-body"
              value={bodyMd}
              rows={14}
              spellCheck={false}
              className="font-mono text-xs"
              placeholder={BODY_TEMPLATE}
              onChange={(e) => {
                setBodyMd(e.target.value);
                if (error) setError(null);
              }}
            />
          )}
        </div>

        <div className="flex items-center justify-between gap-3">
          <div className="grid gap-0.5">
            <Label htmlFor="cl-major">주요 수정 포함</Label>
            <p className="text-muted-foreground text-xs">
              잘못 저장·미저장·실행 불가·개인정보 수정이 있으면 켭니다. 목록에 배지가 붙고 필터로
              걸러집니다. 본문에는 <code>### 주요 수정</code> 섹션으로 적어주세요.
            </p>
          </div>
          <Switch id="cl-major" checked={hasMajorFix} onCheckedChange={setHasMajorFix} />
        </div>

        <div className="flex items-center justify-between gap-3">
          <div className="grid gap-0.5">
            <Label htmlFor="cl-released">공개(배포됨)</Label>
            <p className="text-muted-foreground text-xs">
              끄면 미공개(draft)로 관리자에게만 보입니다.
            </p>
          </div>
          <Switch id="cl-released" checked={released} onCheckedChange={setReleased} />
        </div>
      </DialogBody>
    </Dialog>
  );
}
