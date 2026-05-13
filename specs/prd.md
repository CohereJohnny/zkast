# zkast — Product Requirements Document

## Overview

**zkast** ("zettelkasten + cast") is an application that turns a user's library of PDFs into an evolving, navigable knowledge graph by applying the Zettelkasten method with LLM assistance.

Users upload PDFs, the system extracts atomic notes (Zettel), derives entities and relationships, and assembles them into an Obsidian-style temporal context graph that the user can explore and curate. Once the user is satisfied with the staged graph, they can persist it to a graph database they own (Neo4j or Postgres with the Apache AGE extension).

zkast is **hybrid by design**: it ships as a self-hostable open-source application first, but its data model, auth surface, and isolation boundaries are built so the same codebase can be operated as a multi-tenant SaaS later.

## Problem Statement

Knowledge workers, researchers, and students accumulate large collections of PDFs (papers, reports, books, manuals). The information inside them is largely inert:

- Documents are read linearly and forgotten.
- Notes, when taken at all, live in disconnected silos (Notion pages, Apple Notes, scattered Markdown).
- Relationships between ideas across documents are invisible.
- Existing AI summarization tools produce flat summaries with no durable structure that the user owns and can query later.

Existing knowledge-graph and RAG tools either require manual graph construction (Obsidian, Logseq), produce static one-shot graphs (GraphRAG), or are opaque managed services that lock users out of their own data.

zkast fills the gap between "read a PDF" and "own a structured, queryable knowledge graph of the ideas inside it."

## Vision

> Every document you read becomes a permanent, interconnected part of a knowledge graph you own.

zkast aims to be the shortest path from `unstructured PDF -> atomic notes -> reviewed knowledge graph -> graph database the user controls`.

## Target Users (Summary)

See [personas.md](personas.md) for detail. In short:

- Research-heavy knowledge workers (primary).
- PhD students and academic researchers.
- Self-hosting power users who want their knowledge stack on-prem.
- (P2) SaaS subscribers who want the same product without operating it.
- Workspace admins for self-hosted/team deployments.

## Goals

- **G-1**: Ingest PDFs and convert them into atomic, Zettelkasten-compliant notes with provenance back to source pages.
- **G-2**: Extract entities and relationships from notes and build a coherent knowledge graph per workspace.
- **G-3**: Allow users to review, edit, and approve the staged graph before any persistence step.
- **G-4**: Let users persist the approved graph into a graph database they own (Neo4j or Postgres+AGE) without lock-in.
- **G-5**: Run fully self-hosted on a single machine via Docker Compose, with no required external SaaS dependency beyond an LLM provider key the user supplies.
- **G-6**: Preserve a clean upgrade path to multi-user and SaaS modes without re-architecting the working data model.
- **G-7**: Be LLM-provider agnostic by design. **P0 ships with Cohere as the single supported provider** (Command for chat/extraction, Embed v4 — `embed-v4.0` — for embeddings, Rerank v4 — `rerank-v4.0-fast` — for the cross-encoder). Additional providers (OpenAI, Gemini, Anthropic, Ollama, generic OpenAI-compatible) are added in P1 without requiring an architectural change.
- **G-8**: Let users **chat with their knowledge graph** in natural language and receive answers that are grounded in their own atomic notes, entities, and documents, with **inline citations** that resolve back to the source. Grounded chat is a first-class P0 feature and exploits Cohere Chat's native document-grounding and citation outputs.

## Non-Goals

- **NG-1**: zkast is not a general-purpose document management system; it does not replace Dropbox, Google Drive, or a DMS.
- **NG-2**: zkast is a **knowledge-graph-grounded** chat assistant. It is NOT a general-purpose chat assistant: it does not browse the web, execute code, generate images, or answer questions that cannot be grounded in the workspace's own notes and documents. Ungrounded requests are explicitly refused.
- **NG-3**: zkast does not host or rent out a graph database. Persistence targets are always user-owned and user-configured.
- **NG-4**: zkast does not perform OCR on handwritten or low-quality scanned PDFs in P0 (deferred to a later phase).
- **NG-5**: zkast does not perform real-time collaborative editing of notes or the graph in P0/P1.
- **NG-6**: zkast does not offer mobile-native applications in P0/P1; the web UI must be usable on tablet but is not a mobile-first product.

## Functional Requirements

### Ingestion

- **FR-1**: A user can upload one or more PDFs to a workspace.
- **FR-2**: A user can see the upload and ingestion status (queued, parsing, extracting, building graph, ready, failed) for each document.
- **FR-3**: The system parses the PDF into text chunks with page-level provenance (chunk -> page number(s) -> document).
- **FR-4**: The system tolerates ingestion failures on a per-document basis without corrupting the workspace's existing graph.
- **FR-5**: A user can re-ingest a document. The previous working-graph rows whose only provenance was the prior version are swept by orphan cleanup; user-edited entities (`is_user_edited = true`) and manual edges (`origin = manual`) are preserved. A new `IngestionRun` is recorded; existing `GraphSnapshot` rows are immutable and unaffected.
- **FR-6**: A user can delete a document; deletion clearly indicates which atomic notes, entities, and edges trace back exclusively to that document and offers to remove them.

### Atomic Note Generation (Zettelkasten)

- **FR-7**: The system produces atomic notes (one idea per note) from each document, following Zettelkasten principles (atomicity, autonomy, linkage, source attribution).
- **FR-8**: Each atomic note has: a title, a body, source citation (document + page range), generated tags, and links to related notes.
- **FR-9**: A user can read, edit, retitle, retag, merge, split, or delete any atomic note.
- **FR-10**: A user can manually create an atomic note that is not derived from any document.
- **FR-11**: A user can manually create or remove a link between two atomic notes.

### Knowledge Graph Construction

- **FR-12**: The system extracts entities (people, organizations, concepts, locations, works, dates, custom types) and typed relationships from atomic notes and chunks.
- **FR-13**: The graph supports temporal validity on edges (`valid_from`, `valid_to`) so facts can be superseded rather than deleted.
- **FR-14**: Every entity and every edge traces back to the atomic note(s) and episode(s) that produced it.
- **FR-15**: The system deduplicates entities across documents within a workspace (e.g., "Albert Einstein" mentioned in three papers maps to one entity).
- **FR-16**: A user can define custom entity types and edge types for their workspace.

### Graph Review and Editing

- **FR-17**: A user can visualize the working graph as an interactive, Obsidian-style force-directed graph.
- **FR-18**: A user can filter the graph by document, tag, entity type, edge type, or time range.
- **FR-19**: A user can select any node or edge and see its provenance, properties, and originating atomic notes.
- **FR-20**: A user can rename, merge, split, or delete entities directly from the graph view.
- **FR-21**: A user can add, edit, or delete edges directly from the graph view.
- **FR-22**: The user can mark a graph as "reviewed" to create a named **GraphSnapshot**.

### Persistence to External Graph Database

- **FR-23**: A user can configure one or more **External Graph Targets** per workspace, of type Neo4j or Postgres+AGE.
- **FR-24**: The system can test the connection to an External Graph Target before any write attempt.
- **FR-25**: A user can persist a named GraphSnapshot to a chosen External Graph Target.
- **FR-26**: A persistence operation runs as an asynchronous job whose status the user can monitor and cancel.
- **FR-27**: Persistence is non-destructive by default: existing data in the target DB is not deleted unless the user explicitly opts in to a "replace" mode.
- **FR-28**: The schema written to the target DB is documented and stable (see [datamodel.md](datamodel.md)).

### Grounded Chat (Chat with the Knowledge Graph)

- **FR-35**: A user can open a **chat session** scoped to a workspace and ask natural-language questions about their atomic notes, entities, and documents.
- **FR-36**: Each user message triggers **hybrid retrieval** over the working graph (semantic + keyword + graph traversal) to assemble a relevant context set of notes, entities, and relationships.
- **FR-37**: The system passes the retrieved context to Cohere Chat using Cohere's document-grounding mechanism and returns an answer with **structured citations** that map every cited span in the answer to the underlying atomic notes, entities, relationships, or document pages.
- **FR-38**: Every citation in the rendered answer is clickable and resolves to the originating atomic note (preferred) and, when applicable, to the source document and page range.
- **FR-39**: Chat responses **stream token-by-token** to the UI; the user can stop generation at any time.
- **FR-40**: A user can **scope a chat session** by filter (one or more documents, tags, entity types, edge types, time range) or by pinning it to a specific **GraphSnapshot** for reproducible answers.
- **FR-41**: A user can **see what was retrieved** for any assistant message (the exact notes, entities, and edges fed to the LLM) and report bad answers from that view.
- **FR-42**: Chat sessions and messages are **persistent per workspace**; a user can list, rename, delete, and resume sessions. Editors can edit a session's title; messages are append-only except for regeneration of the last assistant turn.
- **FR-43**: A user can **regenerate** the last assistant message (re-runs retrieval and generation) without restarting the session.
- **FR-44**: Other surfaces (graph view, note view, entity detail) expose an **"Ask about this"** action that starts (or continues) a chat session pre-scoped to the selected note/entity/subgraph.
- **FR-45**: When retrieval produces no useful context, the assistant must say so explicitly rather than answer from parametric knowledge. Cohere Chat's grounded mode is configured to refuse ungrounded answers; the UI labels the response accordingly. "No useful context" means no grounding documents *at all* — the synthesized graph-context document (per-type counts + named exemplars from the workspace's typed taxonomy) is sufficient context for typed-aggregation questions ("how many", "list all", "count by") even when hybrid vector retrieval surfaces zero fact-level hits. See [techstack.md](techstack.md) "Grounded Chat" → "Graph-context grounding document" and **TD-015**.

### Configuration and Settings

- **FR-29**: A user can configure which LLM provider and models to use for note generation, extraction, embeddings, and reranking. **P0 supports Cohere only** (Command for chat — repo defaults `command-a-plus-05-2026` (large) and `command-r7b-12-2024` (small) — `embed-v4.0` for embeddings, `rerank-v4.0-fast` for the cross-encoder). P1 adds OpenAI, Gemini, Anthropic, Ollama, and a generic OpenAI-compatible provider option.
- **FR-30**: A user can supply their own API keys for LLM providers; keys are encrypted at rest and never returned in API responses. The single required credential in P0 is a Cohere production API key.
- **FR-31**: A user can configure pipeline parameters (chunk size, max atomic notes per document, language).

### Workspaces and Access Control

- **FR-32**: Content is organized into **workspaces**. A user's documents, notes, graph, and external targets belong to exactly one workspace.
- **FR-33**: In single-user self-hosted mode, a default workspace is auto-created and auth is bypassed.
- **FR-34**: In multi-user mode, a workspace can have multiple members with roles (Owner, Editor, Viewer).

## Non-Functional Requirements

- **NFR-1 — Self-hostability**: The full stack must run on a developer's laptop with one `docker compose up` command and no external dependencies other than a single Cohere production API key (in P0).
- **NFR-2 — Data ownership**: All user data (PDFs, notes, graph, snapshots) must be stored in components the operator controls. No telemetry is required for the product to function, and telemetry must be opt-out and disabled by default in self-hosted mode.
- **NFR-3 — Privacy of credentials**: API keys and external-target credentials must be encrypted at rest with a per-deployment key and never logged or returned in API responses.
- **NFR-4 — Performance (interactive)**: Graph view interactions (pan, zoom, select, filter) must remain at 60fps for graphs of up to 5,000 nodes / 15,000 edges on a 2020-era laptop.
- **NFR-5 — Performance (ingestion)**: A typical 30-page research PDF should complete the full ingestion pipeline (parse -> notes -> graph) in under 5 minutes on a typical hosted LLM.
- **NFR-6 — Reliability**: A failed LLM call or extraction step on one chunk must not fail the entire document; the system must retry with backoff and record partial progress.
- **NFR-7 — Observability**: All pipeline stages must emit OpenTelemetry traces and structured logs so operators can diagnose failures.
- **NFR-8 — Portability of output**: The schema persisted to an external graph DB must be expressible identically in Cypher (Neo4j) and openCypher-on-AGE (Postgres+AGE).
- **NFR-9 — Accessibility**: The web UI must meet WCAG 2.1 AA.
- **NFR-10 — Internationalization**: All UI strings must be externalized for future translation. P0 ships English only.
- **NFR-11 — Security**: All write endpoints require authentication outside single-user bypass mode. Uploaded PDFs are stored with restricted access scoped to the workspace.

## Phased Scope

### Phase 0 — Self-hosted, single-user (MVP)

- Single default workspace, auth bypassed.
- PDF ingestion, atomic-note generation, working graph in app-managed working store.
- Graph review and editing UI.
- Persistence to Neo4j and Postgres+AGE.
- Cohere as the sole supported LLM provider (Command for chat, `embed-v4.0` for embeddings, `rerank-v4.0-fast` for reranking). LangExtract co-extraction (source-grounded char-offset spans, also Cohere-backed) ships in P0 alongside Graphiti's typed extraction.
- **Grounded chat** with the knowledge graph: streaming responses, inline citations to atomic notes and document pages, per-session scoping, "Ask about this" entry points from graph/note views.
- Docker Compose deployment.

### Phase 1 — Self-hosted, multi-user

- User accounts, workspaces with multiple members, roles (Owner / Editor / Viewer).
- Per-user encrypted API key storage.
- Audit log of pipeline runs and persistence jobs.
- Additional LLM providers: OpenAI, Gemini, Anthropic, Ollama, and generic OpenAI-compatible endpoints. The LangExtract co-extractor (shipped in P0 on Cohere) can swap to Gemini natively for higher-fidelity span alignment on long PDFs once a Gemini provider is configured.
- Chat enhancements: saved/pinned answers, exportable chat transcripts (markdown with citations), session sharing (read-only) inside a workspace, and per-session retrieval profiles (e.g., "broad" vs "precise").
- Custom entity/edge type definitions per workspace.

### Phase 2 — Multi-tenant SaaS

- Hosted deployment on Vercel + managed Postgres + managed FastAPI service.
- Supabase Auth with social providers.
- Per-tenant resource quotas, rate limits.
- Optional managed external-target provisioning (e.g., one-click Neo4j AuraDB) — still user-owned.
- Pricing and billing (out of scope for this PRD beyond noting it exists).

## Success Metrics

- **SM-1 — Activation**: ≥ 70% of users who upload their first PDF reach the "review graph" view within 10 minutes.
- **SM-2 — Completion**: ≥ 50% of users who reach the review view persist at least one snapshot to an external graph DB.
- **SM-3 — Note quality**: ≥ 80% of generated atomic notes are kept (not deleted) by users after review, sampled across a calibration set.
- **SM-4 — Ingestion reliability**: < 2% of ingestion runs end in unrecoverable failure on the calibration PDF corpus.
- **SM-5 — Self-host adoption**: ≥ 100 GitHub stars and ≥ 10 confirmed self-hosted deployments within the first quarter post-launch (P0/P1 success indicator).
- **SM-6 — Chat engagement**: Median weekly active user asks ≥ 5 chat questions per week, and ≥ 80% of those answers receive at least one citation (i.e., are grounded, not refused).
- **SM-7 — Citation quality**: In a calibration set, ≥ 90% of citations resolve to a note/document that a human reviewer agrees actually supports the cited span.

## Constraints

- **C-1**: The atomic-note and extraction stages depend on third-party LLM APIs; behavior is bounded by their availability, rate limits, and structured-output support.
- **C-2**: The persistence layer must support both Neo4j 5.26+ and Postgres 16 with Apache AGE; the abstract graph contract cannot use features absent from either.
- **C-3**: For P0, the working graph engine is `graphiti-core`; the product inherits its Python runtime and supported backend matrix.
- **C-4**: All long-running operations must be cancellable and observable. No *non-streaming* HTTP request may hold a connection longer than 60 seconds — long work runs as an arq job with an SSE progress channel (`text/event-stream`) and a cancel endpoint. SSE streams (ingestion log, chat tokens, persistence progress) are the explicit exception to the 60-second ceiling and are kept alive with 15-second `: keepalive` comment lines so reverse proxies don't drop idle connections.

## Assumptions

- **A-1**: Users are willing to supply their own LLM API key in self-hosted mode. In P0 that key is specifically a Cohere production API key; P1 broadens this to any supported provider's key.
- **A-2**: Users who choose to persist a graph already operate (or are willing to operate) a Neo4j or Postgres+AGE instance.
- **A-3**: Most PDFs in the target corpus contain extractable text. Image-only PDFs are an edge case explicitly out of P0 scope.
- **A-4**: Average workspace size is in the low thousands of notes / tens of thousands of edges, not millions.

## Out of Scope

- Real-time collaborative editing of notes or graphs.
- Native mobile applications.
- OCR for handwritten or image-only PDFs.
- Agentic / tool-using chat behaviors (web browsing, code execution, calling external APIs). The grounded chat in P0 retrieves only from the workspace's own working graph.
- Hosting a managed graph database for the user.
- Importing from non-PDF sources (web pages, EPUB, DOCX) in P0; tracked for later phases.

## Related Specifications

- [personas.md](personas.md) — Who uses zkast and what they need.
- [userstories.md](userstories.md) — Stories that satisfy the requirements above, with acceptance criteria.
- [datamodel.md](datamodel.md) — Working-store entities and the abstract external-graph contract.
- [techstack.md](techstack.md) — Chosen technologies and rationale.
- [apis.md](apis.md) — API behavior contracts.
- [uiux.md](uiux.md) — UI and interaction requirements.
