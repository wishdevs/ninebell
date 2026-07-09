# 빌드 컨텍스트 = 리포 루트.
#   docker build -f infra/aws/docker/front.Dockerfile \
#     --build-arg NEXT_PUBLIC_API_BASE="http://<ALB_DNS>:8080" -t <front-repo>:<tag> .
# ⚠ NEXT_PUBLIC_* 은 '빌드 타임'에 클라이언트 번들로 구워짐 → 반드시 build-arg 로 주입.
FROM node:22-bookworm-slim AS build
WORKDIR /app

ARG NEXT_PUBLIC_API_BASE
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE \
    NEXT_TELEMETRY_DISABLED=1

RUN corepack enable
COPY package.json pnpm-lock.yaml ./
# pnpm 11 은 빌드 스크립트 있는 의존성(sharp 등)을 기본 차단하고 CI 에서 에러(ERR_PNPM_IGNORED_BUILDS).
# 설치는 완료되므로(|| true) 뒤이어 필요한 것만 명시적으로 rebuild. rebuild 실패 시 빌드 중단(안전).
RUN pnpm install --frozen-lockfile || true
RUN pnpm rebuild sharp unrs-resolver
COPY . .
# pnpm build 는 실행 전 deps 재검증(verify-deps-before-run)에서 또 ignored-builds 로 막힘 →
# pnpm 스크립트 래퍼를 우회해 next 를 직접 호출(위에서 sharp 등 rebuild 완료·node_modules 정상).
RUN node_modules/.bin/next build

# ── 런타임 ──
FROM node:20-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production TZ=Asia/Seoul NEXT_TELEMETRY_DISABLED=1

RUN npm install -g pm2 && corepack enable

# 빌드 산출물 통째 복사(standalone 미설정 → node_modules 포함). 필요시 next standalone 으로 슬림화.
COPY --from=build /app ./
COPY infra/aws/docker/ecosystem.config.js ./ecosystem.config.js
COPY infra/aws/docker/server.js ./server.js

EXPOSE 3000
CMD ["pm2-runtime", "start", "ecosystem.config.js"]
