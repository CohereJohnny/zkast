# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS base
RUN corepack enable && corepack prepare pnpm@9.15.4 --activate
WORKDIR /app

FROM base AS deps
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json ./apps/web/
RUN pnpm install --frozen-lockfile --filter web...

FROM base AS builder
COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/apps/web/node_modules ./apps/web/node_modules
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web ./apps/web

ARG DATABASE_URL=postgresql://zkast:zkast@postgres:5432/zkast
ARG INTERNAL_PIPELINE_TOKEN=build-time-placeholder
ARG PIPELINE_INTERNAL_URL=http://pipeline:8000
ENV DATABASE_URL=$DATABASE_URL \
    INTERNAL_PIPELINE_TOKEN=$INTERNAL_PIPELINE_TOKEN \
    PIPELINE_INTERNAL_URL=$PIPELINE_INTERNAL_URL \
    NEXT_TELEMETRY_DISABLED=1

RUN pnpm --filter web build

FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nodejs \
  && adduser --system --uid 1001 nextjs

COPY --from=builder /app/apps/web/public ./apps/web/public

COPY --from=builder --chown=nextjs:nodejs /app/apps/web/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/.next/static ./apps/web/.next/static

USER nextjs

EXPOSE 3000

WORKDIR /app/apps/web
CMD ["node", "server.js"]
