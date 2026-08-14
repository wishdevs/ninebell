'use client';

import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Dialog, DialogBody } from '@/components/ui/dialog';
import { EmptyState } from '@/components/ui/empty-state';
import { FormField } from '@/components/ui/form-field';
import { InlineConfirm } from '@/components/ui/inline-confirm';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SectionCard } from '@/components/ui/section-card';
import { Spinner } from '@/components/ui/spinner';
import { Switch } from '@/components/ui/switch';
import { Td, Th } from '@/components/ui/table-cell';
import { usePermissions } from '@/hooks/use-permissions';
import { errorMessage } from '@/lib/api/client';
import {
  createMerchantRule,
  deleteMerchantRule,
  fetchMerchantDict,
  updateMerchantRule,
  type MerchantRule,
  type MerchantRuleInput,
} from '@/lib/api/me-codes';
import { ROLES, roleAtLeast } from '@/lib/auth/permissions';

/** 쉼표 구분 문자열 → 소문자·중복 제거 키워드 배열(빈 토큰 제외). */
function parseKeywords(raw: string): string[] {
  const seen = new Set<string>();
  for (const token of raw.split(',')) {
    const k = token.trim().toLowerCase();
    if (k) seen.add(k);
  }
  return [...seen];
}

/**
 * 가맹점 분류 사전 CRUD 표. 조회는 전원, 추가/수정/삭제 버튼은 관리자에게만 노출한다
 * (백엔드가 최종 강제 — 여기선 UX 게이팅). 저장 후 목록을 재조회한다.
 */
export function MerchantDictClient() {
  const { role } = usePermissions();
  const isAdmin = roleAtLeast(role, ROLES.ADMIN);

  const [rows, setRows] = useState<MerchantRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  // undefined = 다이얼로그 닫힘, null = 새 규칙, MerchantRule = 수정 대상.
  const [editing, setEditing] = useState<MerchantRule | null | undefined>(undefined);

  const load = useCallback(() => {
    setLoading(true);
    fetchMerchantDict()
      .then(setRows)
      .catch((err) => toast.error(errorMessage(err, '가맹점 사전을 불러오지 못했습니다.')))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function removeOne(id: string) {
    setConfirmId(null);
    setBusyId(id);
    try {
      await deleteMerchantRule(id);
      setRows((prev) => prev.filter((r) => r.id !== id));
      toast.success('규칙을 삭제했습니다.');
    } catch (err) {
      toast.error(errorMessage(err, '삭제하지 못했습니다.'));
    } finally {
      setBusyId(null);
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner size={20} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <span className="text-foreground-tertiary text-[length:var(--text-body-sm)] tabular-nums">
          {rows.length}건
        </span>
        {isAdmin ? (
          <Button variant="primary" size="sm" onClick={() => setEditing(null)}>
            규칙 추가
          </Button>
        ) : null}
      </div>

      {rows.length === 0 ? (
        <EmptyState
          title="등록된 규칙이 없습니다"
          description={
            isAdmin
              ? '‘규칙 추가’로 카드 표기명 키워드와 업종/계정을 등록하세요.'
              : '아직 등록된 가맹점 분류 규칙이 없습니다.'
          }
        />
      ) : (
        <SectionCard>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[880px] text-[length:var(--text-body-sm)]">
              <thead>
                <tr>
                  <Th>카테고리</Th>
                  {/* 칩이 여러 개라 좁으면 한 줄에 하나씩 쌓인다 — 열 최소 폭 확보(모바일). */}
                  <Th className="min-w-[280px]">키워드</Th>
                  <Th>계정</Th>
                  <Th>구분</Th>
                  <Th>출처</Th>
                  <Th className="text-right">우선순위</Th>
                  <Th>활성</Th>
                  {isAdmin ? <Th className="text-right">액션</Th> : null}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="border-border/60 border-t">
                    <Td className="font-medium whitespace-nowrap">{r.category}</Td>
                    <Td>
                      <div className="flex flex-wrap gap-1">
                        {r.keywords.map((k) => (
                          <span
                            key={k}
                            className="bg-muted text-foreground-secondary inline-flex items-center rounded-full px-2 py-0.5 text-[11px]"
                          >
                            {k}
                          </span>
                        ))}
                      </div>
                    </Td>
                    <Td className="whitespace-nowrap">
                      {r.acct ? r.acct : <span className="text-foreground-tertiary">—</span>}
                    </Td>
                    <Td>
                      {r.strong ? (
                        <span
                          className="bg-accent/10 text-accent inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold"
                          title="계정 확정 폴백"
                        >
                          결정적
                        </span>
                      ) : (
                        <span
                          className="bg-muted text-foreground-tertiary inline-flex items-center rounded-full px-2 py-0.5 text-[11px]"
                          title="AI 힌트만"
                        >
                          힌트
                        </span>
                      )}
                    </Td>
                    <Td className="text-foreground-secondary whitespace-nowrap">{r.source}</Td>
                    <Td className="text-foreground-tertiary text-right tabular-nums">
                      {r.sortOrder}
                    </Td>
                    <Td className="whitespace-nowrap">
                      {r.enabled ? (
                        <span className="text-foreground-secondary">활성</span>
                      ) : (
                        <span className="text-foreground-tertiary">비활성</span>
                      )}
                    </Td>
                    {isAdmin ? (
                      <Td className="text-right whitespace-nowrap">
                        {confirmId === r.id ? (
                          <InlineConfirm
                            question="삭제할까요?"
                            confirmLabel="삭제"
                            onConfirm={() => removeOne(r.id)}
                            onCancel={() => setConfirmId(null)}
                            disabled={busyId !== null}
                          />
                        ) : (
                          <div className="inline-flex items-center gap-1">
                            <button
                              type="button"
                              onClick={() => setEditing(r)}
                              disabled={busyId !== null}
                              className="text-foreground-secondary hover:text-foreground hover:bg-muted rounded-[var(--radius-sm)] px-2 py-1 transition-colors disabled:opacity-40"
                            >
                              수정
                            </button>
                            <button
                              type="button"
                              onClick={() => setConfirmId(r.id)}
                              disabled={busyId !== null}
                              aria-label={`${r.category} 규칙 삭제`}
                              className="text-foreground-tertiary hover:text-danger hover:bg-danger/10 rounded-[var(--radius-sm)] px-2 py-1 transition-colors disabled:opacity-40"
                            >
                              {busyId === r.id ? <Spinner size={12} /> : '삭제'}
                            </button>
                          </div>
                        )}
                      </Td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>
      )}

      {isAdmin && editing !== undefined ? (
        <MerchantRuleDialog
          key={editing?.id ?? '__new__'}
          initial={editing}
          onClose={() => setEditing(undefined)}
          onSaved={load}
        />
      ) : null}
    </div>
  );
}

interface MerchantRuleDialogProps {
  /** null = 새 규칙, MerchantRule = 수정. */
  initial: MerchantRule | null;
  onClose: () => void;
  onSaved: () => void;
}

/** 규칙 추가/수정 폼 다이얼로그. `key`로 대상별 리마운트되므로 초기값은 useState 초기화로 채운다. */
function MerchantRuleDialog({ initial, onClose, onSaved }: MerchantRuleDialogProps) {
  const isEdit = initial !== null;
  const [category, setCategory] = useState(initial?.category ?? '');
  const [keywords, setKeywords] = useState(initial ? initial.keywords.join(', ') : '');
  const [acct, setAcct] = useState(initial?.acct ?? '');
  const [strong, setStrong] = useState(initial?.strong ?? false);
  const [source, setSource] = useState(initial?.source ?? '큐레이션');
  const [sortOrder, setSortOrder] = useState(String(initial?.sortOrder ?? 0));
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit() {
    const cat = category.trim();
    const kws = parseKeywords(keywords);
    if (!cat) {
      setError('카테고리를 입력해주세요.');
      return;
    }
    if (kws.length === 0) {
      setError('키워드를 최소 1개 입력해주세요.');
      return;
    }
    const parsedOrder = Number(sortOrder);
    const payload: MerchantRuleInput = {
      keywords: kws,
      category: cat,
      acct: acct.trim() ? acct.trim() : null,
      strong,
      source: source.trim() || '큐레이션',
      sortOrder: Number.isFinite(parsedOrder) ? parsedOrder : 0,
      enabled,
    };
    setSaving(true);
    try {
      if (isEdit && initial) {
        await updateMerchantRule(initial.id, payload);
        toast.success('규칙을 수정했습니다.');
      } else {
        await createMerchantRule(payload);
        toast.success('규칙을 추가했습니다.');
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
      title={isEdit ? '규칙 수정' : '규칙 추가'}
      description="카드 표기명 키워드로 미등록 가맹점의 업종/계정을 인식하는 규칙입니다."
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

        <FormField id="mr-category" label="카테고리" required hint="업종 유형 (예: 주유·유류)">
          <Input
            id="mr-category"
            value={category}
            placeholder="주유·유류"
            onChange={(e) => {
              setCategory(e.target.value);
              if (error) setError(null);
            }}
          />
        </FormField>

        <FormField
          id="mr-keywords"
          label="키워드"
          required
          hint="카드 표기명 부분일치 키워드. 쉼표로 구분 (소문자 저장)."
        >
          <Input
            id="mr-keywords"
            value={keywords}
            placeholder="gs칼텍스, s-oil, 주유소"
            onChange={(e) => {
              setKeywords(e.target.value);
              if (error) setError(null);
            }}
          />
        </FormField>

        <FormField
          id="mr-acct"
          label="계정"
          hint="결정적 계정명(선택). 있으면 ‘결정적’으로 계정 확정 폴백에 쓰입니다."
        >
          <Input
            id="mr-acct"
            value={acct}
            placeholder="차량유지비"
            onChange={(e) => setAcct(e.target.value)}
          />
        </FormField>

        <FormField id="mr-source" label="출처" hint="‘내부’ / ‘웹’ / ‘내부+웹’ / ‘큐레이션’">
          <Input id="mr-source" value={source} onChange={(e) => setSource(e.target.value)} />
        </FormField>

        <FormField id="mr-sort" label="우선순위" hint="오름차순으로 첫 매칭을 채택합니다.">
          <Input
            id="mr-sort"
            type="number"
            value={sortOrder}
            onChange={(e) => setSortOrder(e.target.value)}
          />
        </FormField>

        <div className="flex items-center justify-between gap-3">
          <div className="grid gap-0.5">
            <Label htmlFor="mr-strong">결정적 (strong)</Label>
            <p className="text-muted-foreground text-xs">
              켜면 계정 확정 폴백, 끄면 AI 힌트로만 사용합니다.
            </p>
          </div>
          <Switch id="mr-strong" checked={strong} onCheckedChange={setStrong} />
        </div>

        <div className="flex items-center justify-between gap-3">
          <div className="grid gap-0.5">
            <Label htmlFor="mr-enabled">활성</Label>
            <p className="text-muted-foreground text-xs">끄면 매칭에서 제외됩니다.</p>
          </div>
          <Switch id="mr-enabled" checked={enabled} onCheckedChange={setEnabled} />
        </div>
      </DialogBody>
    </Dialog>
  );
}
