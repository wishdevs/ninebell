# syntax=docker/dockerfile:1
# 프론트(Next.js 16 standalone). 빌드는 CI에서 1회.
# ⚠ NEXT_PUBLIC_* 는 번들에 구워진다 → 프록시 뒤 same-origin '/api' 로 빌드하면
#    이미지 하나가 모든 프록시 환경에서 동작(build once, deploy many).
FROM node:22-alpine AS deps
WORKDIR /app
# package-lock.json 이 아직 없어 npm install 사용. 재현성 위해 lock 커밋 후 `npm ci` 로 전환 권장.
COPY package.json ./
RUN npm install

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_BASE=/api
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
RUN npm run build          # next.config 의 output:'standalone' 필요

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S app && adduser -S app -G app
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
USER app
EXPOSE 3000
# standalone 산출물의 진입점. Caddy 가 이 3000 포트로 프록시.
CMD ["node", "server.js"]
