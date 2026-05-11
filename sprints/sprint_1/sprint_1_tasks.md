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

- [ ] Scaffold Next.js 14 + TypeScript + Tailwind per [techstack.md](../../specs/techstack.md).
- [ ] Implement CSS variables / Tailwind theme mapping **Visual Design System** tokens ([uiux.md](../../specs/uiux.md)): `bg-canvas`, `bg-surface`, accents, typography families (Plus Jakarta Sans, Crimson Pro, JetBrains Mono).
- [ ] Layout: persistent left rail + main region; skip-to-content link (**Accessibility**).
- [ ] Placeholder routes matching IA: Documents, Notes, Graph, Chat, Snapshots, Targets, Settings — each with empty/loading states per [uiux.md](../../specs/uiux.md) States Reference.
- [ ] Route handlers for `/api/v1/healthz`, `/api/v1/readyz`, `/api/v1/version` proxying or aggregating pipeline status ([apis.md](../../specs/apis.md)).
- [ ] Internal HTTP client to pipeline (shared secret header per [apis.md](../../specs/apis.md)).
- [ ] TanStack Query + minimal error boundary pattern for future data views.

## Pipeline service (FastAPI)

- [ ] FastAPI app with lifespan, structured JSON logging, request IDs.
- [ ] `/healthz`, `/readyz`, `/version` ([apis.md](../../specs/apis.md)).
- [ ] OTEL SDK wired with env toggle OFF by default self-hosted (**NFR-2**, **NFR-7**).
- [ ] Placeholder `POST /internal/v1/*` 501 stubs with stable OpenAPI schema export for codegen.

## Data + migrations

- [ ] Postgres migrations for P0 core tables (minimal slice): `User` (bypass), `Workspace`, `Membership` (single owner row), empty stubs or nullable FKs for downstream entities per [datamodel.md](../../specs/datamodel.md).
- [ ] Migration tooling (e.g. Alembic on pipeline side or shared migrate job — pick one and document).
- [ ] Row-level conventions: `workspace_id` on all workspace-scoped tables.

## Infra + Docker

- [ ] Root `docker-compose.yml`: services **web**, **pipeline**, **postgres:16**, **redis:7**, **falkordb** image per [techstack.md](../../specs/techstack.md).
- [ ] `.env.example`: `MASTER_ENCRYPTION_KEY`, `COHERE_API_KEY` (optional Sprint 1), `DATABASE_URL`, `REDIS_URL`, `FALKORDB_*`, `INTERNAL_PIPELINE_TOKEN`, `NEXT_PUBLIC_*` only if strictly needed.
- [ ] Networks: pipeline reachable from web; FalkorDB not exposed publicly.
- [ ] Optional **otel-collector** service commented out or profile `observability`.

## Design + UX

- [ ] Apply focus ring token (`accent-primary` 2px + offset) globally.
- [ ] Dark theme default; light theme toggle stub (can defer full parity to Sprint 8 if needed — document choice).
- [ ] Icon set: Lucide only for chrome introduced this sprint (**UI checklist**: no emoji icons).

## Docs

- [ ] Root `README.md`: prerequisites, `cp .env.example .env`, `docker compose up`, URLs.
- [ ] Document bypass-auth behavior and security warning for exposed installs (**FR-33**).

---

## Definition of Done

- [ ] Fresh clone → compose up → landing page loads with rail + placeholders.
- [ ] Postgres migrations apply cleanly on empty volume.
- [ ] No secrets committed; `.env.example` complete.
- [ ] `pnpm run build` (or npm) passes for web; `pytest` passes minimal smoke for pipeline (if tests added).
- [ ] OTEL code paths compile but emit nothing when disabled.

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

### Gaps / issues

### Next sprint prep
