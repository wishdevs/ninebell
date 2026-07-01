# NINEBELL — 더존 옴니솔 자동화 대시보드

`/Users/wishdev/et-works/ax` 프로젝트의 **프론트엔드 디자인만 추출**한 기본형(base template)입니다.
백엔드·인증·API 없이 **더미데이터**로만 동작하며, 전체 레이아웃과 대표 페이지 유형들을 담았습니다.

> 모든 UI를 1:1로 클론한 것이 아니라, "전체 레이아웃은 이렇고 / 페이지에는 이런 유형·저런 유형이 있다"를
> 보여주기 위한 골격입니다. 새 화면을 만들 때 여기서 패턴을 복제해 시작하세요.

## 기술 스택

- **Next.js 16** (App Router) · **React 19**
- **Tailwind CSS v4** (`globals.css`의 디자인 토큰 기반)
- **Radix UI** (popover / select / tabs / tooltip / slot)
- **recharts** (차트), **lucide-react** (아이콘), **sonner** (토스트), **next-themes** (라이트/다크)
- 폰트: **Pretendard**(본문·한글) + **Geist**(영문/숫자 디스플레이) + **Geist Mono**

## 실행

```bash
pnpm install
pnpm dev      # http://localhost:3000  →  / 로 진입
pnpm build    # 프로덕션 빌드 검증
pnpm tsc      # 타입 체크
```

로그인 화면은 `/login`, 나머지는 인증 가드 없이 바로 접근됩니다(더미).

## 디자인 시스템

원본의 시각 언어를 그대로 가져왔습니다 — *Swiss 타이포그래피 + Bento 대시보드 표면*.

- **색상**: OKLCH 기반, 라이트/다크 둘 다 1급 시민. 모든 색은 `globals.css`의 시맨틱 토큰
  (`--background`, `--surface`, `--foreground`, `--accent`, `--success/warning/danger/info`, sentiment 팔레트 등).
- **타이포 스케일**: 14px 본문 기준, `--text-caption … --text-hero`.
- **반경/그림자/모션**: 4px 스케일 반경, 다단계 그림자, `--ease-out` 모션 토큰.
- 실제 토큰·컴포넌트는 **`/design-system`** 페이지에서 한눈에 확인할 수 있습니다.

## 페이지 유형 (아키타입)

| 경로 | 유형 | 핵심 패턴 |
|------|------|-----------|
| `/login` | 인증 | 좌측 폼 + 우측 오로라 히어로 split 레이아웃 |
| `/` | 대시보드 홈 | PageHeader + 알림 피드 + Bento 인사이트 카드 + 스파크라인 |
| `/analytics` | 애널리틱스 | KPI 행 + recharts(영역/막대/도넛) + 데이터 테이블, 기간 전환 |
| `/works` | 리스트 + 마스터/디테일 | 필터 칩 + 데이터 테이블 + 상세 패널 + 상태 배지 |
| `/projects` | 카드 그리드 | 상태 필터 탭 + 프로젝트 카드 + 진행률 + 빈 상태 |
| `/projects/[slug]` | 상세 + 탭 | 엔티티 헤더 + 탭(개요/업무/활동/파일) |
| `/members` | 관리 테이블 + CRUD | 행 액션 + 상태 칩 + 초대/확인 다이얼로그 + 토스트 |
| `/settings` | 설정(탭 폼) | 탭 + 폼 필드 + 스위치 + 위험 구역 |
| `/design-system` | 레퍼런스 | 토큰·컴포넌트 쇼케이스 |

## 디렉토리 구조

```
src/
├── app/
│   ├── globals.css            # 디자인 토큰 (원본에서 그대로 추출)
│   ├── layout.tsx             # 루트: 폰트 + 테마 + 토스터
│   ├── fonts/                 # Pretendard / Geist (woff2)
│   ├── (auth)/                # 인증 레이아웃(오로라 히어로) + 로그인
│   └── (app)/                 # 대시보드 셸 레이아웃 + 모든 앱 페이지
│       └── <route>/_components/   # 페이지 전용 컴포넌트(라우팅에서 제외)
├── components/
│   ├── ui/                    # 디자인 시스템 프리미티브(원본 추출)
│   ├── shell/                 # 사이드바 · 토프바 · 워크스페이스 스위처 · 사용자 메뉴
│   └── theme-provider.tsx
└── lib/
    ├── utils.ts               # cn()
    └── data/                  # 모든 더미데이터(워크스페이스/홈/애널리틱스/업무/프로젝트/멤버)
```

## 더미데이터

`src/lib/data/*`의 정적 배열/객체가 전부입니다. 네트워크 호출 없음.
실제 백엔드를 붙일 때는 이 모듈들을 데이터 패칭 레이어(서버 컴포넌트/React Query 등)로 교체하면
컴포넌트는 거의 그대로 재사용할 수 있도록 형태를 맞춰 두었습니다.

## 출처

레이아웃·토큰·컴포넌트 패턴은 사내 `ax` 프론트엔드에서 추출했습니다.
백엔드·인증·권한·실데이터 로직은 의도적으로 모두 제거했습니다.
