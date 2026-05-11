# Sprint 1 — Foundation and Scaffolding

**Duration**: 2 weeks  
**Goal**: Establish monorepo, Docker Compose stack, Next.js 14 app shell with design tokens and IA from [uiux.md](../../specs/uiux.md), FastAPI pipeline skeleton, Postgres schema bootstrap for core tenancy/workspace tables, single-user bypass auth, encrypted secrets handling, and OTEL hooks (disabled by default). Satisfies **NFR-1**, **NFR-3**, **NFR-7** (stubs), **FR-32–FR-33** (workspace shell only).

## Inputs

- Specs in [specs/](../../specs/).
- No prior application code.

## Outputs (demonstrable)

- `docker compose up` starts: **web**, **pipeline**, **postgres**, **redis**, **falkordb** (placeholder wiring OK if Graphiti not connected until Sprint 2).
- Browser loads workspace shell: left rail (Documents, Notes, Graph, Chat, Snapshots, Targets, Settings), placeholder three-panel layout + chat drawer hook (empty states).
- Health/readiness endpoints return dependency status.
- Default workspace exists for bypass user; master encryption key documented.

## Dependencies

- None (first sprint).

---

## Web tier (Next.js 14 App Router, RSC-first)

- [x] Scaffold Next.js 14 + TypeScript + Tailwind per [techstack.md](../../specs/techstack.md).
- [x] Implement CSS variables / Tailwind theme mapping **Visual Design System** tokens ([uiux.md](../../specs/uiux.md)): `bg-canvas`, `bg-surface`, accents, typography families (Plus Jakarta Sans, Crimson Pro, JetBrains Mono).
- [x] Layout: persistent left rail + main region; skip-to-content link (**Accessibility**).
- [x] Placeholder routes matching IA: Documents, Notes, Graph, Chat, Snapshots, Targets, Settings — each with empty/loading states per [uiux.md](../../specs/uiux.md) States Reference.
- [x] Route handlers for `/api/v1/healthz`, `/api/v1/readyz`, `/api/v1/version` proxying or aggregating pipeline status ([apis.md](../../specs/apis.md)).
- [x] Internal HTTP client to pipeline (shared secret header per [apis.md](../../specs/apis.md)).
- [x] TanStack Query + minimal error boundary pattern for future data views.

## Pipeline service (FastAPI)

- [x] FastAPI app with lifespan, structured JSON logging, request IDs.
- [x] `/healthz`, `/readyz`, `/version` ([apis.md](../../specs/apis.md)).
- [x] OTEL SDK wired with env toggle OFF by default self-hosted (**NFR-2**, **NFR-7**).
- [x] Placeholder `POST /internal/v1/*` 501 stubs with stable OpenAPI schema export for codegen.

## Data + migrations

- [x] Postgres migrations for P0 core tables (minimal slice): `User` (bypass), `Workspace`, `Membership` (single owner row), empty stubs or nullable FKs for downstream entities per [datamodel.md](../../specs/datamodel.md).
- [x] Migration tooling (e.g. Alembic on pipeline side or shared migrate job — pick one and document).
- [x] Row-level conventions: `workspace_id` on all workspace-scoped tables.

## Infra + Docker

- [x] Root `docker-compose.yml`: services **web**, **pipeline**, **postgres:16**, **redis:7**, **falkordb** image per [techstack.md](../../specs/techstack.md).
- [x] `.env.example`: `MASTER_ENCRYPTION_KEY`, `COHERE_API_KEY` (optional Sprint 1), `DATABASE_URL`, `REDIS_URL`, `FALKORDB_*`, `INTERNAL_PIPELINE_TOKEN`, `NEXT_PUBLIC_*` only if strictly needed.
- [x] Networks: pipeline reachable from web; FalkorDB not exposed publicly.
- [x] Optional **otel-collector** service commented out or profile `observability`.

## Design + UX

- [x] Apply focus ring token (`accent-primary` 2px + offset) globally.
- [x] Dark theme default; light theme toggle stub (can defer full parity to Sprint 8 if needed — document choice).
- [x] Icon set: Lucide only for chrome introduced this sprint (**UI checklist**: no emoji icons).

## Docs

- [x] Root `README.md`: prerequisites, `cp .env.example .env`, `docker compose up`, URLs.
- [x] Document bypass-auth behavior and security warning for exposed installs (**FR-33**).

---

## Definition of Done

- [x] Fresh clone → compose up → landing page loads with rail + placeholders.
- [x] Postgres migrations apply cleanly on empty volume.
- [x] No secrets committed; `.env.example` complete.
- [x] `pnpm run build` (or npm) passes for web; `pytest` passes minimal smoke for pipeline (if tests added).
- [x] OTEL code paths compile but emit nothing when disabled.

## Risks and mitigations

| Risk | Mitigation |
| ---- | ---------- |
| Monorepo tooling friction | Standardize on single package manager + workspace README |
| Tailwind v4 vs v3 drift | Pin versions in README; match Next.js LTS docs |

## Out of scope (later sprints)

- Real Graphiti/Cohere wiring (**Sprint 2**).
- PDF upload (**Sprint 3**).
- Full entity graph (**Sprint 4+**).

---

## Sprint review (fill at end)

### Demo readiness

- Monorepo scaffold (**pnpm** workspace, `apps/web`, `apps/pipeline`, `apps/migrations`).
- **Docker Compose**: Postgres, Redis, FalkorDB, one-shot migrate, pipeline, web; documented Quick Start in root **README.md**.
- **Web**: Next.js 14 shell — design tokens, left rail, seven placeholder routes, `/api/v1/healthz|readyz|version`, bypass auth + workspace lookup, OTEL stub off by default.
- **Pipeline**: FastAPI — `/healthz`, `/readyz`, `/version`, internal 501 stubs, AES-GCM helpers + pytest smoke.
- **Data**: Alembic `0001_init` — users, workspaces, memberships + bypass seed.

### Gaps / issues

- **Alembic + psycopg3**: SQLAlchemy defaults `postgresql://` to psycopg2; **fixed** by rewriting to `postgresql+psycopg://` in `apps/migrations/alembic/env.py` (see **apps/migrations/README.md**). Rebuild `migrate` image after pulling.
- **`gh`/CI**: branch protection and PR automation require a valid GitHub token (run `gh auth login` locally if CLI reports keyring errors).

### Next sprint prep

- Sprint 2: Graphiti / Cohere wiring, real ingestion path (per **sprints/sprintplan.md**).
