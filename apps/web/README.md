# zkast web (Next.js 14)

App Router + TypeScript + Tailwind v3. Uses React Server Components by default; client islands include TanStack Query provider, nav rail (active route), chat drawer stub, and error boundary.

## Prerequisites

- Node **22+**
- **pnpm 9.x** (Corepack: `corepack enable`)

## Local development

From the **repository root**:

```bash
cp .env.example .env
# Edit .env — set MASTER_ENCRYPTION_KEY and INTERNAL_PIPELINE_TOKEN. Defaults use 127.0.0.1 for Postgres (Compose publishes 5432) and pipeline (Compose publishes 8000).

pnpm install
pnpm dev
```

Open `http://localhost:3000` (redirects to `/documents`).

Environment variables are read from the **repository root** `.env` / `.env.local` (via `next.config.mjs`), so you do not need to duplicate them under `apps/web/` for local dev. Optional overrides can still live in `apps/web/.env.local`.

### Useful routes

| Path | Purpose |
| ---- | ------- |
| `/api/v1/healthz` | Web liveness |
| `/api/v1/readyz` | Aggregates pipeline `/readyz` (needs running pipeline + env) |
| `/api/v1/version` | Web + pipeline versions |

### Against Docker Compose pipeline only

Point `PIPELINE_INTERNAL_URL` at `http://127.0.0.1:8000` when Compose publishes pipeline port **8000** (default in root `docker-compose.yml`).

## Build / lint

```bash
pnpm --filter web build
pnpm --filter web lint
```

## Docker

Built from repo root (see root `docker-compose.yml`): context `.`, Dockerfile `apps/web/Dockerfile`.

## Telemetry stub

When `ZKAST_OTEL_ENABLED=true`, `src/instrumentation.ts` loads `src/lib/otel-register.ts` (Node SDK). Default is off (**NFR-2**).

## Theme

Root layout sets `<html data-theme="dark">` only; light-theme tokens exist in CSS for a future Sprint 8 parity pass ([specs/uiux.md](../../specs/uiux.md)).
