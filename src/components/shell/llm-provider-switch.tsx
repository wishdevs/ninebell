'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api/client';
import { IS_DEV_ENV } from '@/lib/env';
import { cn } from '@/lib/utils';

/** GET/PUT `/dev/llm-provider` 응답 shape — 백엔드 계약과 동일. */
interface LlmProviderInfo {
  active: 'gemini' | 'etribe';
  source: 'env' | 'override';
  options: { id: 'gemini' | 'etribe'; label: string }[];
}

/**
 * 사이드바 하단 LLM 프로바이더 스위치 — 로컬 dev 전용 컨트롤.
 *
 * - 프로덕션 빌드에서는 fetch 조차 하지 않고 null 렌더(nav devOnly 관례와 동일한 이중 게이트).
 * - GET이 404/에러(게이트 off·서버 배포·미인증)면 흔적 없이 숨긴다(null 렌더).
 * - 클릭은 낙관 갱신 후 PUT, 실패 시 원복(홈 즐겨찾기 패턴 미러).
 * - 오버라이드는 서버 프로세스 메모리에만 저장 — 재시작 시 env 기본값으로 복귀한다.
 */
export function LlmProviderSwitch() {
  const [info, setInfo] = useState<LlmProviderInfo | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    // 이중 게이트: 프로덕션 빌드에서는 요청 자체를 보내지 않는다.
    // 개발 환경(로컬 dev·AWS 테스트 빌드)에서만 조회 — 프로덕션(온프렘)은 fetch 자체 생략.
    if (!IS_DEV_ENV) return;
    let cancelled = false;
    api
      .get<LlmProviderInfo>('/dev/llm-provider')
      .then((data) => {
        if (!cancelled) setInfo(data);
      })
      .catch(() => {
        // 404(게이트 off)·네트워크 오류 — 기능이 없는 것처럼 조용히 숨긴다.
        if (!cancelled) setInfo(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!info) return null;

  /** 옵션 클릭 → 낙관 갱신 + PUT, 실패 시 이전 상태로 원복. */
  async function select(provider: 'gemini' | 'etribe') {
    if (!info || pending || provider === info.active) return;
    const prev = info;
    setPending(true);
    setInfo({ ...info, active: provider, source: 'override' });
    try {
      const next = await api.put<LlmProviderInfo>('/dev/llm-provider', { provider });
      setInfo(next);
    } catch {
      setInfo(prev);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="border-border-subtle border-t px-4 py-2">
      <div className="mb-1.5 flex items-center gap-1.5">
        <span className="text-foreground-tertiary text-[10px] font-semibold tracking-widest uppercase">
          AI 모델
        </span>
        <span
          aria-hidden
          className="border-border text-foreground-tertiary rounded-[var(--radius-sm)] border px-1 text-[9px] font-semibold tracking-wider"
        >
          DEV
        </span>
      </div>
      <div
        role="radiogroup"
        aria-label="LLM 프로바이더 선택"
        className="border-border bg-surface flex items-center gap-0.5 rounded-[var(--radius-md)] border p-0.5 text-[11px] shadow-[var(--shadow-card)]"
      >
        {info.options.map((option) => {
          const selected = option.id === info.active;
          return (
            <button
              key={option.id}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={pending}
              title={option.label}
              onClick={() => select(option.id)}
              className={cn(
                'min-w-0 flex-1 truncate rounded-[var(--radius-sm)] px-2 py-1 font-medium transition-colors duration-[var(--duration-fast)] disabled:opacity-60',
                selected
                  ? 'bg-accent/15 text-accent'
                  : 'text-foreground-secondary hover:text-foreground hover:bg-muted',
              )}
            >
              {option.label}
            </button>
          );
        })}
      </div>
      {info.source === 'override' ? (
        <p
          className="text-foreground-tertiary mt-1 text-[10px]"
          title="프로세스 메모리 오버라이드 — 서버 재시작 시 env 기본값으로 복귀"
        >
          재시작 시 env 값으로 복귀
        </p>
      ) : null}
    </div>
  );
}
