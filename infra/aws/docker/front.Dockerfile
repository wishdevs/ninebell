# 빌드 컨텍스트 = 리포 루트.
#   docker build -f infra/aws/docker/front.Dockerfile \
#     --build-arg NEXT_PUBLIC_API_BASE="http://<ALB_DNS>:8080" -t <front-repo>:<tag> .
# ⚠ NEXT_PUBLIC_* 은 '빌드 타임'에 클라이언트 번들로 구워짐 → 반드시 build-arg 로 주입.
FROM node:20-bookworm-slim AS build
WORKDIR /app

ARG NEXT_PUBLIC_API_BASE
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE \
    NEXT_TELEMETRY_DISABLED=1

RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

# ── 런타임 ──
FROM node:20-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production TZ=Asia/Seoul NEXT_TELEMETRY_DISABLED=1

RUN npm install -g pm2 && corepack enable

# 빌드 산출물 통째 복사(standalone 미설정 → node_modules 포함). 필요시 next standalone 으로 슬림화.
COPY --from=build /app ./
COPY infra/aws/docker/ecosystem.config.js ./ecosystem.config.js

EXPOSE 3000
CMD ["pm2-runtime", "start", "ecosystem.config.js"]
