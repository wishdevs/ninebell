'use client';

import { useCallback, useEffect, useState } from 'react';
import { RiErrorWarningLine, RiHistoryLine, RiLockLine } from '@remixicon/react';
import { Button } from '@/components/ui/button';
import { PageHeader } from '@/components/ui/page-header';
import { Spinner } from '@/components/ui/spinner';
import { EmptyState } from '@/components/ui/empty-state';
import { StatusPill } from '@/components/ui/status-pill';
import { ApiError, api, toApiError } from '@/lib/api/client';
import { Td, Th } from '@/components/ui/table-cell';
import { PERMISSIONS, type Role } from '@/lib/auth/permissions';
import { useCan } from '@/components/permissions/perm-gate';
import { MEMBER_ROLE_LABEL } from '@/lib/data/members';
import { formatDateTime } from '@/lib/data/format';

/** `GET /logs` 한 행 — 접속(감사) 로그 응답 계약(camelCase)과 1:1. */
interface AccessLog {
  id: string;
  /** 성공 시 매칭된 사용자 id. 미상(실패) 시 null. */
  userId: string | null;
  omnisolUserid: string;
  /** 사용자 표시명. 미상 시 빈 문자열일 수 있다. */
  displayName: string;
  /** 미상 사용자(실패)면 null. */
  role: Role | null;
  status: 'success' | 'failed';
  errorMsg: string | null;
  ip: string | null;
  userAgent: string | null;
  loggedAt: string;
}

const PAGE_SIZE = 50;

type Phase = 'loading' | 'ready' | 'loadingMore' | 'error';

/**
 * 감사 로그 테이블 — 사용자 접속(로그인) 감시. logs:read(admin+) 권한이 없으면 접근 불가
 * 상태를 보여주고 fetch 자체를 하지 않는다. 권한이 있으면 `GET /logs?limit&offset`로
 * 최신순 페이지를 불러오고 "더 보기"로 이어서 적재한다.
 */
export function AuditClient() {
  const canRead = useCan(PERMISSIONS.LOGS_READ);
  const [rows, setRows] = useState<AccessLog[]>([]);
  const [phase, setPhase] = useState<Phase>('loading');
  const [error, setError] = useState<ApiError | null>(null);
  const [hasMore, setHasMore] = useState(false);

  const loadPage = useCallback(async (offset: number) => {
    const isFirst = offset === 0;
    setPhase(isFirst ? 'loading' : 'loadingMore');
    setError(null);
    try {
      const page = await api.get<AccessLog[]>(`/logs?limit=${PAGE_SIZE}&offset=${offset}`);
      setRows((prev) => (isFirst ? page : [...prev, ...page]));
      setHasMore(page.length === PAGE_SIZE);
      setPhase('ready');
    } catch (err: unknown) {
      setError(toApiError(err));
      setPhase('error');
    }
  }, []);

  useEffect(() => {
    if (canRead) loadPage(0);
  }, [canRead, loadPage]);

  return (
    <div className="animate-page-enter flex flex-col gap-8">
      <PageHeader
        caption="운영"
        title="감사"
        description="옴니솔 로그인 접속 기록입니다. 언제·누가·어디서 접속했는지와 성공·실패를 확인할 수 있습니다."
      />

      {!canRead ? (
        <EmptyState
          icon={<RiLockLine size={18} aria-hidden />}
          title="접근 권한이 없습니다"
          description="감사 로그는 관리자 이상만 열람할 수 있습니다."
        />
      ) : phase === 'loading' ? (
        <div className="text-muted-foreground flex items-center justify-center gap-2 py-16 text-sm">
          <Spinner size={18} label="로그 불러오는 중" />
          접속 기록을 불러오는 중…
        </div>
      ) : phase === 'error' && rows.length === 0 ? (
        <EmptyState
          icon={<RiErrorWarningLine size={18} aria-hidden />}
          title="접속 기록을 불러오지 못했습니다"
          description={error?.status === 0 ? '서버에 연결할 수 없습니다.' : (error?.message ?? '')}
          action={
            <Button variant="secondary" size="sm" onClick={() => loadPage(0)}>
              다시 시도
            </Button>
          }
        />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<RiHistoryLine size={18} aria-hidden />}
          title="접속 기록이 없습니다"
          description="아직 기록된 로그인 접속 이벤트가 없습니다."
        />
      ) : (
        <div className="flex flex-col gap-3">
          <p className="text-muted-foreground text-[length:var(--text-body-sm)]">
            총 <span className="text-foreground font-medium tabular-nums">{rows.length}</span>건
            {hasMore ? ' 이상' : ''}
          </p>

          <div className="border-border bg-surface overflow-x-auto rounded-[var(--radius-lg)] border shadow-[var(--shadow-card)]">
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead className="border-border text-foreground-tertiary border-b text-[length:var(--text-caption)] font-medium tracking-[0.04em] uppercase">
                <tr>
                  <Th>사용자</Th>
                  <Th>롤</Th>
                  <Th>접속시각</Th>
                  <Th>IP</Th>
                  <Th>상태</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((log) => (
                  <tr
                    key={log.id}
                    className="border-border-subtle row-hover border-b last:border-0"
                  >
                    <Td>
                      <div className="grid gap-0.5">
                        <p className="text-foreground font-medium">
                          {log.displayName || log.omnisolUserid}
                        </p>
                        <p className="text-muted-foreground font-mono text-xs">
                          {log.omnisolUserid}
                        </p>
                      </div>
                    </Td>

                    <Td className="text-muted-foreground text-xs">
                      {log.role ? MEMBER_ROLE_LABEL[log.role] : '—'}
                    </Td>

                    <Td className="text-muted-foreground text-xs tabular-nums">
                      {formatDateTime(log.loggedAt)}
                    </Td>

                    <Td className="text-muted-foreground font-mono text-xs">{log.ip || '—'}</Td>

                    <Td>
                      <div className="flex flex-col gap-0.5">
                        <StatusPill
                          label={log.status === 'success' ? '성공' : '실패'}
                          variant={log.status === 'success' ? 'success' : 'danger'}
                        />
                        {log.status === 'failed' && log.errorMsg ? (
                          <span
                            className="text-foreground-tertiary max-w-[16rem] truncate text-[11px]"
                            title={log.errorMsg}
                          >
                            {log.errorMsg}
                          </span>
                        ) : null}
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {hasMore ? (
            <div className="flex justify-center pt-1">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => loadPage(rows.length)}
                disabled={phase === 'loadingMore'}
              >
                {phase === 'loadingMore' ? (
                  <>
                    <Spinner size={14} />
                    불러오는 중…
                  </>
                ) : (
                  '더 보기'
                )}
              </Button>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

