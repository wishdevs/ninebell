'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { Spinner } from '@/components/ui/spinner';
import { ApiError, api } from '@/lib/api/client';

/** 회원가입 유도 시 sessionStorage에 넘길 pending 정보 키. */
const SIGNUP_STORAGE_KEY = 'nb_signup';
/** '아이디 저장' 프리필 키(localStorage). 비밀번호는 절대 저장하지 않는다. */
const REMEMBERED_ID_KEY = 'nb_remembered_userid';

/** 개발 환경 전용 빠른 로그인 계정(테스트 자격증명). 프로덕션 빌드에선 렌더되지 않는다
 * (NODE_ENV 정적 치환으로 트리셰이킹). 실 배포엔 포함되지 않으므로 테스트 편의용으로만 쓴다. */
const DEV_QUICK_ACCOUNTS: ReadonlyArray<{ userid: string; password: string }> = [
  { userid: 'admin', password: '1111' },
  { userid: '이트라이브', password: '1111' },
  { userid: '이트라이브2', password: '1111' },
];

/**
 * `POST /auth/login` 응답 계약.
 * - 기존 유저/로컬 계정: 세션 발급 후 `{ ok: true }`.
 * - 옴니솔 첫 접속(유저 없음): 세션 미발급, 회원가입 유도 `{ signupRequired, signupToken, prefill }`.
 */
type LoginResponse =
  | { ok: true }
  | {
      signupRequired: true;
      signupToken: string;
      prefill: { displayName: string; department: string | null };
    };

/**
 * 옴니솔(더존 ERP) 자격증명 로그인 폼.
 *
 * 옴니솔이 사실상 IdP라 이메일이 아닌 **옴니솔 아이디 + 비밀번호**로 인증한다.
 * `POST /auth/login`이 자격증명을 검증한 뒤 응답을 분기한다: 세션이 발급되면
 * 홈으로, 첫 접속이면 prefill을 저장하고 회원가입으로 유도한다. 자격증명
 * 오류(401)는 인라인 메시지로 노출한다.
 */
export function LoginForm() {
  const router = useRouter();
  const [userid, setUserid] = useState('');
  const [password, setPassword] = useState('');
  const [saveId, setSaveId] = useState(false);
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // 마운트 시 저장된 아이디를 프리필(있으면 '아이디 저장'도 체크 상태로 복원).
  useEffect(() => {
    const saved = localStorage.getItem(REMEMBERED_ID_KEY);
    if (saved) {
      setUserid(saved);
      setSaveId(true);
    }
  }, []);

  async function login(uid: string, pw: string) {
    if (submitting) return;
    setError(null);
    setSubmitting(true);
    // 아이디 저장은 제출 시점 기준으로 반영(비밀번호는 저장하지 않는다).
    if (saveId) localStorage.setItem(REMEMBERED_ID_KEY, uid.trim());
    else localStorage.removeItem(REMEMBERED_ID_KEY);
    try {
      const res = await api.post<LoginResponse>('/auth/login', {
        userid: uid,
        password: pw,
        remember,
      });
      if ('signupRequired' in res && res.signupRequired) {
        // 첫 접속 — 세션 미발급. prefill+토큰을 넘겨 회원가입 단계로 유도한다.
        sessionStorage.setItem(
          SIGNUP_STORAGE_KEY,
          JSON.stringify({
            signupToken: res.signupToken,
            displayName: res.prefill.displayName,
            department: res.prefill.department,
          }),
        );
        router.push('/signup');
        return;
      }
      // 세션 쿠키 발급 완료 → 보호 라우트로. refresh로 미들웨어가 쿠키를 재평가하게 한다.
      router.replace('/');
      router.refresh();
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 401) {
        setError('아이디 또는 비밀번호가 올바르지 않습니다.');
      } else if (err instanceof ApiError && err.status === 0) {
        setError('서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.');
      } else {
        setError('로그인 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.');
      }
      setSubmitting(false);
    }
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await login(userid, password);
  }

  /** 개발 전용 빠른 로그인 — 필드에 채워 보여주고 바로 로그인한다(상태 반영은 화면 표시용). */
  function quickLogin(uid: string, pw: string) {
    setUserid(uid);
    setPassword(pw);
    void login(uid, pw);
  }

  return (
    <form onSubmit={handleSubmit} className="grid gap-5" noValidate>
      <FormField id="userid" label="옴니솔 아이디" required error={error ?? undefined}>
        <Input
          id="userid"
          name="userid"
          type="text"
          autoComplete="username"
          placeholder="옴니솔 로그인 아이디"
          value={userid}
          aria-invalid={error ? true : undefined}
          onChange={(event) => {
            setUserid(event.target.value);
            if (error) setError(null);
          }}
          required
        />
      </FormField>

      <FormField id="password" label="비밀번호" required>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          placeholder="••••••••"
          value={password}
          aria-invalid={error ? true : undefined}
          onChange={(event) => {
            setPassword(event.target.value);
            if (error) setError(null);
          }}
          required
        />
      </FormField>

      <div className="flex items-center justify-between gap-4">
        <label className="text-foreground-secondary flex cursor-pointer items-center gap-2 text-[length:var(--text-body-sm)]">
          <input
            type="checkbox"
            className="accent-accent h-4 w-4 cursor-pointer"
            checked={saveId}
            onChange={(event) => setSaveId(event.target.checked)}
          />
          <span>아이디 저장</span>
        </label>
        <label className="text-foreground-secondary flex cursor-pointer items-center gap-2 text-[length:var(--text-body-sm)]">
          <input
            type="checkbox"
            className="accent-accent h-4 w-4 cursor-pointer"
            checked={remember}
            onChange={(event) => setRemember(event.target.checked)}
          />
          <span>로그인 상태 유지</span>
        </label>
      </div>

      <Button type="submit" disabled={submitting}>
        {submitting ? (
          <>
            <Spinner size={16} />
            로그인 중…
          </>
        ) : (
          '로그인'
        )}
      </Button>

      {process.env.NODE_ENV !== 'production' ? (
        <div className="border-border/60 mt-1 flex flex-col gap-2 border-t border-dashed pt-4">
          <span className="text-foreground-tertiary text-[length:var(--text-body-sm)]">
            개발 전용 · 빠른 로그인
          </span>
          <div className="flex flex-wrap gap-2">
            {DEV_QUICK_ACCOUNTS.map((acct) => (
              <Button
                key={acct.userid}
                type="button"
                variant="secondary"
                size="sm"
                disabled={submitting}
                onClick={() => quickLogin(acct.userid, acct.password)}
              >
                {acct.userid}
              </Button>
            ))}
          </div>
        </div>
      ) : null}
    </form>
  );
}
