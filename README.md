# zkast

**zkast** (“zettelkasten + cast”) is a planned application that ingests **PDFs**, generates **atomic Zettelkasten-style notes**, builds an **Obsidian-style knowledge graph** backed by [Graphiti](https://github.com/getzep/graphiti), and supports **grounded chat** over your corpus using **Cohere** (with citations). After review, you can **persist** snapshots to a graph database you control—**Neo4j** or **Postgres with Apache AGE**.

The product is specified as **self-hostable first** (Docker Compose, BYO Cohere key) with a path toward multi-user and SaaS later.

This repository currently holds **specifications** and a **sprint implementation plan**. Application code will land incrementally starting with [Sprint 1](sprints/sprint_1/sprint_1_tasks.md).

## Vision

- Turn unstructured PDFs into **atomic notes** with provenance (document + pages).
- Maintain a **working graph** (entities, typed relationships, temporal validity) you can explore and edit before anything is written to production graph stores.
- **Chat with your knowledge graph**: answers grounded in your notes and graph, with **inline citations** (Cohere Chat document grounding).
- **Optional persistence** to **Neo4j 5.26+** or **Postgres + AGE** using a stable, documented external-graph contract.

See [specs/prd.md](specs/prd.md) for goals, functional requirements, non-functional requirements, and phased scope (P0 / P1 / P2).

## Repository layout

| Path | Purpose |
| ---- | ------- |
| [specs/](specs/) | Product and technical specifications (PRD, personas, user stories, data model, APIs, UI/UX, tech stack). |
| [sprints/](sprints/) | Master sprint plan, P0 task breakdown (Sprints 1–8), backlog, tech debt, and bug log templates. |

### Specifications

- [specs/prd.md](specs/prd.md) — Product requirements  
- [specs/personas.md](specs/personas.md) — User personas  
- [specs/userstories.md](specs/userstories.md) — Epics and user stories  
- [specs/datamodel.md](specs/datamodel.md) — Working-store entities, ERD, external-graph contract  
- [specs/techstack.md](specs/techstack.md) — Intended stack (Next.js 14, FastAPI, Graphiti, Cohere, FalkorDB, etc.)  
- [specs/apis.md](specs/apis.md) — HTTP API behavior contracts  
- [specs/uiux.md](specs/uiux.md) — Information architecture, design tokens, accessibility  

### Sprints and delivery

- [sprints/sprintplan.md](sprints/sprintplan.md) — P0 dependency graph, sprint summaries, P1 outline, release target **v0.1.0** after Sprint 8  
- [sprints/sprint_1/](sprints/sprint_1/) … [sprints/sprint_8/](sprints/sprint_8/) — Per-sprint task checklists  
- [sprints/backlog.md](sprints/backlog.md) — P2 and parking-lot items  
- [sprints/tech_debt.md](sprints/tech_debt.md) — Non-blocking refactors log  
- [sprints/bug_swatting.md](sprints/bug_swatting.md) — Critical bug log template  

## Planned architecture (summary)

High-level shape from [specs/techstack.md](specs/techstack.md):

- **Web**: Next.js 14 (App Router), TypeScript, Tailwind CSS, React Server Components where practical.
- **Pipeline**: Python (FastAPI) for PDF parsing, Graphiti, and Cohere-backed extraction and chat.
- **Data**: Postgres for relational metadata; FalkorDB as the default working graph for Graphiti in self-hosted setups.
- **LLM (P0)**: Cohere only—Command (via OpenAI-compatible chat API), Embed v3, Rerank v3.

Detailed diagrams and rationale live in the tech stack spec.

## Getting started (today)

There is **no runnable application** in this repo yet. To contribute or implement:

1. Read [specs/prd.md](specs/prd.md) and [specs/techstack.md](specs/techstack.md).  
2. Follow [sprints/sprintplan.md](sprints/sprintplan.md) and execute [sprints/sprint_1/sprint_1_tasks.md](sprints/sprint_1/sprint_1_tasks.md) first (monorepo, Docker Compose, app shell, Postgres, Redis, FalkorDB).  
3. Track progress by checking off tasks in each `sprint_N_tasks.md` and use [sprints/tech_debt.md](sprints/tech_debt.md) / [sprints/bug_swatting.md](sprints/bug_swatting.md) as needed.

When Sprint 1 is complete, this README should be updated with concrete commands (`docker compose up`, environment variables, and development URLs).

## License

Not specified in this repository yet. Add a `LICENSE` file when you choose one for the project.

## Acknowledgments

- Knowledge graph engine: [Graphiti](https://github.com/getzep/graphiti) (Zep / Apache-2.0).  
- Product direction and extraction evolution are documented in [specs/techstack.md](specs/techstack.md) (including future LangExtract / additional providers in later phases).
