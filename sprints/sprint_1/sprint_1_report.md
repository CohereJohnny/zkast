# Sprint 1 — Report

**Sprint**: Foundation and scaffolding  
**Status**: Complete  
**Task tracker**: [sprint_1_tasks.md](sprint_1_tasks.md)  
**Merged delivery**: Pull request targeting `main` from branch `sprints/sprint-1` (see repo on GitHub).

## Executive summary

Sprint 1 established the zkast **monorepo**, **Docker Compose** runtime, **Next.js 14** workspace shell aligned with [specs/uiux.md](../../specs/uiux.md), a **FastAPI** pipeline skeleton with health and internal-contract stubs, and **Postgres** bootstrap via **Alembic** with a **single-user bypass** seed. All checklist items and Definition of Done criteria in [sprint_1_tasks.md](sprint_1_tasks.md) are satisfied. Telemetry hooks exist but remain **off by default** (**NFR-2**). Bypass authentication is explicitly **local / single-operator only** (**FR-33**, **NFR-11**).

## Goals vs outcomes

| Goal (from sprint brief) | Outcome |
| ------------------------- | ------- |
| Monorepo + package boundaries | Root **pnpm** workspace; `apps/web` (Node), `apps/pipeline` and `apps/migrations` (Python) documented. |
| Compose stack | **postgres**, **redis**, **falkordb**, one-shot **migrate**, **pipeline**, **web**; only web published on host port **3000**. |
| Web IA + design tokens | Seven placeholder routes, left rail, three-panel + chat drawer stub, skip link, tokenized Tailwind/CSS; dark default. |
| Pipeline API surface | `/healthz`, `/readyz`, `/version`, OpenAPI at `/openapi.json`, internal **501** stubs, request IDs, internal token guard. |
| Data model slice | `users`, `workspaces`, `memberships`; indexed `workspace_id` convention documented for future tables. |
| Secrets / observability | AES-256-GCM helpers in pipeline + smoke test; OTEL optional on web and pipeline. |

## Deliverables

- **Infra**: [docker-compose.yml](../../docker-compose.yml), [.env.example](../../.env.example), [.gitignore](../../.gitignore) (includes `.cursor/plans/`).
- **Web** (`apps/web/`): App Router, API routes under `/api/v1/*`, `pipeline-client`, bypass `auth`, Query provider + error boundary, Dockerfile (Node 22 / standalone).
- **Pipeline** (`apps/pipeline/`): FastAPI app, Dockerfile, `requirements.txt`, pytest + `tests/test_secrets.py`; README dev loop.
- **Migrations** (`apps/migrations/`): Alembic `0001_init`, Dockerfile, psycopg **v3** URL normalization in `alembic/env.py`; README.
- **Docs**: Root [README.md](../../README.md) (Quick Start, security note); per-app READMEs.
- **DX**: [scripts/run-pipeline-tests.sh](../../scripts/run-pipeline-tests.sh) and `pnpm run test:pipeline` at repo root.

## Verification performed

- `pnpm run build` (web production build).
- `pnpm run test:pipeline` (venv + AES-GCM smoke).
- `docker compose up --build`: migrate completes, pipeline healthy, web serves UI; `/api/v1/readyz` aggregates pipeline dependency checks when stack is healthy.

## Issues and resolutions

1. **Alembic + psycopg3**: Default SQLAlchemy URL scheme pointed at **psycopg2**, which is not installed in the migrate image. **Resolution**: normalize `DATABASE_URL` to `postgresql+psycopg://` in `apps/migrations/alembic/env.py`; document in `apps/migrations/README.md`. Operators must **rebuild** the migrate image after pulling.
2. **Local pytest**: Bare `pytest` on PATH fails without a venv. **Resolution**: `pnpm run test:pipeline` and README instructions using `python -m pytest`.

## Risks carried forward

- **Solo merge / branch protection**: If `main` requires an approving review, merging without a second reviewer may need a policy tweak or an extra approver.
- **No CI yet**: Branch protection does not require status checks; add GitHub Actions (build + pipeline tests) in a later sprint to harden merges.

## Recommendations for Sprint 2

Per [sprintplan.md](../sprintplan.md), Sprint 2 focuses on **Cohere + Graphiti** wiring: dependency additions, pipeline integration paths, and environment documentation (**COHERE_API_KEY**, etc.). Keep FalkorDB in Compose as the working graph target unless specs dictate a change.

## References

- [sprint_1_tasks.md](sprint_1_tasks.md) — full checklist and sprint review notes.
- [specs/techstack.md](../../specs/techstack.md), [specs/uiux.md](../../specs/uiux.md), [specs/apis.md](../../specs/apis.md).
