'use client';

import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';

/** 클릭 후 알림이 뜨기까지의 지연(ms). */
const DELAY_MS = 3000;

type Perm = NotificationPermission | 'unsupported' | null;

/** 권한 상태 → 배지 라벨/색. */
const PERM_LABEL: Record<Exclude<Perm, null>, { text: string; cls: string }> = {
  granted: { text: '허용됨', cls: 'text-accent' },
  denied: { text: '차단됨', cls: 'text-danger' },
  default: { text: '미결정', cls: 'text-foreground-secondary' },
  unsupported: { text: '미지원', cls: 'text-danger' },
};

/**
 * 푸시 알람 테스트 — 현재 구현된 브라우저 Notification API(로컬 알림)가 실제로 뜨는지
 * 확인하는 버튼 + 현재 권한 상태 + macOS/Windows 알림 설정 안내.
 *
 * ⚠ 이건 '브라우저가 열려 있을 때만' 뜨는 로컬 알림이다(탭이 열려 있으면 백그라운드여도 뜸,
 * 브라우저를 닫으면 안 뜸 — 서버가 밀어주는 백그라운드 Web Push 아님).
 * macOS 에선 탭이 포커스 상태면 배너가 알림센터로만 갈 수 있어, 3초 안에 다른 탭/앱으로
 * 전환하면 배너를 확실히 볼 수 있다.
 */
export function PushAlarmTest() {
  const [countdown, setCountdown] = useState(0); // 0 = 대기 아님
  const [perm, setPerm] = useState<Perm>(null); // null = 마운트 전(SSR 하이드레이션 안전)
  const timers = useRef<number[]>([]);

  // 마운트 후 현재 권한 상태 읽기.
  useEffect(() => {
    if (typeof window === 'undefined' || !('Notification' in window)) {
      setPerm('unsupported');
      return;
    }
    setPerm(Notification.permission);
  }, []);

  // 언마운트 시 타이머 정리(3초 대기 중 화면 이탈 대비).
  useEffect(() => {
    return () => {
      timers.current.forEach((id) => window.clearTimeout(id));
      timers.current.forEach((id) => window.clearInterval(id));
    };
  }, []);

  async function run() {
    if (typeof window === 'undefined' || !('Notification' in window)) {
      toast.error('이 브라우저는 알림(Notification API)을 지원하지 않습니다.');
      return;
    }

    let permission = Notification.permission;
    if (permission === 'default') {
      // 사용자 제스처(클릭) 컨텍스트라 프롬프트가 뜬다.
      permission = await Notification.requestPermission();
    }
    setPerm(permission);
    if (permission !== 'granted') {
      toast.error('알림 권한이 없습니다. 아래 설정 방법을 참고해 허용해 주세요.');
      return;
    }

    // 3초 카운트다운 후 알림 발사.
    setCountdown(3);
    const interval = window.setInterval(() => {
      setCountdown((c) => (c > 1 ? c - 1 : 0));
    }, 1000);
    const timeout = window.setTimeout(() => {
      window.clearInterval(interval);
      setCountdown(0);
      try {
        new Notification('푸시 알람 테스트', {
          body: '3초 뒤 알림이 정상적으로 표시되었습니다. ✅',
          tag: 'push-alarm-test',
        });
      } catch {
        toast.error('알림 표시에 실패했습니다.');
      }
    }, DELAY_MS);
    timers.current = [interval, timeout];
  }

  const waiting = countdown > 0;
  const badge = perm ? PERM_LABEL[perm] : null;

  return (
    <section className="border-border bg-surface flex flex-col gap-4 rounded-md border p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-col gap-1">
          <h2 className="text-foreground text-sm font-semibold">푸시 알람 테스트</h2>
          <p className="text-foreground-secondary text-xs">
            클릭하면 3초 뒤 브라우저 알림이 뜹니다. 배너를 확실히 보려면 3초 안에 다른 탭·앱으로
            전환하세요.
          </p>
        </div>
        {badge ? (
          <span
            className="bg-muted inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium"
            aria-live="polite"
          >
            <span className="text-foreground-secondary">알림 권한</span>
            <span className={badge.cls}>{badge.text}</span>
          </span>
        ) : null}
      </div>

      <div>
        <Button onClick={run} disabled={waiting} aria-live="polite">
          {waiting ? `${countdown}초 후 알림…` : '푸시 알람 실행'}
        </Button>
      </div>

      {/* 알림이 안 뜰 때 OS 설정 안내(로컬 알림 = 브라우저 열려있을 때 기준). */}
      <details className="border-border/60 group border-t pt-3">
        <summary className="text-foreground-secondary hover:text-foreground cursor-pointer list-none text-xs font-medium select-none">
          알림이 안 보이나요? macOS · Windows 설정 방법 보기 ▾
        </summary>

        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          <OsGuide
            title="🍎 macOS"
            steps={[
              '브라우저: 주소창 왼쪽 🔒 → 알림 → 허용',
              '시스템 설정 → 알림 → Google Chrome → "알림 허용" 켜기 (배너 스타일 = 배너/지속)',
              '메뉴바 제어 센터 → 집중 모드(방해 금지) 끄기',
            ]}
          />
          <OsGuide
            title="🪟 Windows"
            steps={[
              '브라우저: 주소창 왼쪽 🔒 → 사이트 설정 → 알림 → 허용',
              '설정 → 시스템 → 알림 → Google Chrome 켜기',
              '집중 지원(방해 금지) 끄기',
            ]}
          />
        </div>

        <p className="text-foreground-secondary mt-3 text-[11px] leading-relaxed">
          ⚠ 이 알림은 <b>브라우저(이 탭)가 열려 있을 때만</b> 뜹니다. 탭이 백그라운드여도 뜨지만,
          브라우저를 닫으면 오지 않습니다. 탭을 <b>포커스</b>한 상태면 배너 대신 화면 내 토스트로
          보일 수 있어, 테스트할 땐 3초 안에 다른 탭·앱으로 전환하세요.
        </p>
      </details>
    </section>
  );
}

function OsGuide({ title, steps }: { title: string; steps: string[] }) {
  return (
    <div className="bg-muted/40 rounded-sm p-3">
      <h3 className="text-foreground mb-2 text-xs font-semibold">{title}</h3>
      <ol className="text-foreground-secondary flex list-decimal flex-col gap-1.5 pl-4 text-[11px] leading-relaxed">
        {steps.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ol>
    </div>
  );
}
