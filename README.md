# zkast

**zkast** (“zettelkasten + cast”) is a planned application that ingests **PDFs**, generates **atomic Zettelkasten-style notes**, builds an **Obsidian-style knowledge graph** backed by [Graphiti](https://github.com/getzep/graphiti), and supports **grounded chat** over your corpus using **Cohere** (with citations). After review, you can **persist** snapshots to a graph database you control—**Neo4j** or **Postgres with Apache AGE**.

The product is specified as **self-hostable first** (Docker Compose, BYO Cohere key) with a path toward multi-user and SaaS later.

## Repository layout

| Path | Purpose |
| ---- | ------- |
| [specs/](specs/) | Product and technical specifications |
| [sprints/](sprints/) | Sprint plans and task checklists |
| [apps/web/](apps/web/) | Next.js 14 web UI |
| [apps/pipeline/](apps/pipeline/) | FastAPI pipeline service |
| [apps/migrations/](apps/migrations/) | Alembic migrations (Compose one-shot `migrate`) |

### Specifications

- [specs/prd.md](specs/prd.md) — Product requirements  
- [specs/personas.md](specs/personas.md) — User personas  
- [specs/userstories.md](specs/userstories.md) — Epics and user stories  
- [specs/datamodel.md](specs/datamodel.md) — Working-store entities, ERD  
- [specs/techstack.md](specs/techstack.md) — Stack choices  
- [specs/apis.md](specs/apis.md) — HTTP contracts  
- [specs/uiux.md](specs/uiux.md) — IA, design tokens, accessibility  

### Sprints

- [sprints/sprintplan.md](sprints/sprintplan.md) — Master plan  
- [sprints/sprint_1/sprint_1_tasks.md](sprints/sprint_1/sprint_1_tasks.md) — Sprint 1 checklist  

## Prerequisites

- **Docker Desktop** or Docker Engine + Compose v2  
- **pnpm 9.x** and **Node 22+** (for local web dev / `pnpm build`; the Compose `web` image uses Node 22)  
- **Python 3.12** (for local pipeline dev — optional if you only use Compose)

## Quick start (Docker Compose)

1. Copy env template and **fill secrets** (values must be non-empty where noted):

   ```bash
   cp .env.example .env
   ```

   Generate keys:

   ```bash
   openssl rand -base64 32   # MASTER_ENCRYPTION_KEY
   openssl rand -hex 32      # INTERNAL_PIPELINE_TOKEN (opaque shared secret)
   ```

2. Start the stack (builds images, runs migrations once, then pipeline + web):

   ```bash
   docker compose up --build
   ```

3. Open the UI: **http://localhost:3000** (redirects to `/documents`). Placeholder routes: Documents, Notes, Graph, Chat, Snapshots, External Targets, Settings.

4. Smoke-check aggregated readiness from the web tier:

   ```bash
   curl -s http://localhost:3000/api/v1/readyz | jq .
   ```

   Expect `status: "ok"` when Postgres, Redis, FalkorDB, and pipeline checks are healthy.

### Dev builds (without Docker)

```bash
pnpm install
pnpm run build          # Next.js production build (web package)
```

Pipeline tests — from the repo root (creates `apps/pipeline/.venv` if missing):

```bash
pnpm run test:pipeline
```

Or manually:

```bash
cd apps/pipeline
python3 -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export MASTER_ENCRYPTION_KEY="$(openssl rand -base64 32)"
python -m pytest
```

## Security note (**FR-33**, **NFR-11**)

Sprint 1 ships **bypass authentication** for a **single local operator**. It is **not** safe to expose this configuration to the public internet. Treat Compose + `.env` as **trusted LAN / single-user dev only** until real auth ships in later sprints.

## Vision

- Turn unstructured PDFs into **atomic notes** with provenance (document + pages).
- Maintain a **working graph** you can explore and edit before persistence.
- **Grounded chat** with inline citations.
- **Optional persistence** to **Neo4j 5.26+** or **Postgres + AGE**.

## License

Not specified in this repository yet. Add a `LICENSE` file when you choose one for the project.

## Acknowledgments

- Knowledge graph engine: [Graphiti](https://github.com/getzep/graphiti) (Zep / Apache-2.0).
