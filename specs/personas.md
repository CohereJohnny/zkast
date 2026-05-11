# zkast — Personas

This document defines the people zkast is designed for. Each persona lists goals, frustrations, success criteria, primary flows, and which deployment phase they map to (P0 self-hosted single-user, P1 self-hosted multi-user, P2 SaaS).

## Persona Index

| ID  | Name (archetype)         | Primary phase | Role                                                            |
| --- | ------------------------ | ------------- | --------------------------------------------------------------- |
| P-1 | Maya the Researcher      | P0            | Primary user — independent researcher / knowledge worker        |
| P-2 | Dev the PhD Student      | P0 / P1       | Primary user — academic researcher with a thesis corpus         |
| P-3 | Otto the Operator        | P0 / P1       | Self-hosting power user / homelab operator                      |
| P-4 | Priya the PM             | P2            | SaaS subscriber — product/strategy lead with internal documents |
| P-5 | Ada the Admin            | P1            | Workspace admin in a self-hosted team deployment                |

## P-1 — Maya the Researcher (Primary)

**Archetype**: Independent researcher / consultant / writer. Reads 5–20 long-form PDFs per week.

**Context**:

- Works on a personal laptop. Pays for ChatGPT and Claude personally, and has signed up for a Cohere account to experiment with embedding and rerank quality.
- Comfortable with Markdown, Obsidian, and basic Docker, but is not a software engineer.
- Uses Obsidian today and is frustrated by how manual graph construction is.

**Goals**:

- Turn the stack of PDFs she has read this month into a navigable map of ideas.
- Own her notes and graph forever, independent of any vendor.
- Spend less time copy-pasting quotes and more time thinking about connections.

**Frustrations with current tools**:

- AI summarizers give her a single paragraph and nothing she can build on.
- Manually creating Zettel in Obsidian is slow and feels like data entry.
- Graph-RAG demos look great but give her no editable artifact.
- She does not want her documents uploaded to a third-party SaaS she cannot inspect.

**Success criteria**:

- Within one evening she can upload 5 PDFs and see a connected graph of the key ideas across all of them.
- She can correct LLM mistakes (rename an entity, merge duplicates) without writing code.
- She can persist the result to her own Neo4j instance and query it from another tool.

**Primary flows**:

- Upload PDFs -> review atomic notes -> review graph -> persist snapshot to her Neo4j.
- Configure her Cohere API key the first time she opens the app (the only LLM credential needed in P0).
- Re-ingest an updated paper and see the graph evolve.
- **Ask her knowledge graph questions in natural language** ("What did Smith 2024 say about X compared to Lee 2022?") and get answers with citations linking back to the exact notes and PDF pages she ingested.

**Maps to phase**: P0 self-hosted single-user.

## P-2 — Dev the PhD Student

**Archetype**: Third-year PhD student in a research-heavy field (e.g., cognitive science, ML, history).

**Context**:

- Has a thesis corpus of ~200 PDFs spanning years of reading.
- Comfortable with the command line, Python, and Neo4j Desktop.
- Works on a university-issued laptop with constrained budgets for API spend.

**Goals**:

- Build a structured map of the citations and concepts across his thesis corpus.
- Discover non-obvious connections between papers from different sub-fields.
- Generate a graph he can include in his dissertation appendix and reference in publications.

**Frustrations**:

- Existing reference managers (Zotero, Mendeley) handle metadata but not ideas.
- He cannot afford a heavy LLM bill. In P0 he will use his Cohere trial credits and production key; he wants to mix Ollama locally with cloud LLMs strategically once multi-provider support lands in P1.
- He needs reproducibility — running the same pipeline twice should give a stable enough graph to cite.

**Success criteria**:

- He can ingest his entire corpus over a weekend by walking away while the pipeline runs.
- He can configure per-document overrides (e.g., "extract aggressively from this paper").
- He can produce a named, dated graph snapshot for inclusion in his dissertation.

**Primary flows**:

- Bulk upload of an entire folder of PDFs.
- Switch LLM provider per ingestion run once P1 lands (Ollama for cheap papers, GPT-4 or Claude for important ones). In P0 he tunes Cohere model size (Command R vs. Command R+) per run instead.
- Export a named snapshot to Postgres+AGE for use in his university's research infrastructure.
- **Use grounded chat to find cross-paper connections** he could not spot by eye, e.g. "Which authors connect topic A and topic B in my corpus?" — and trust the answer because every claim cites the underlying papers and pages.
- **Pin a chat session to a specific GraphSnapshot** so he can rerun the same questions for his dissertation review without the answer drifting as he edits the working graph.

**Maps to phase**: P0 -> P1 once he starts sharing a workspace with his advisor.

## P-3 — Otto the Operator (Self-hosting Power User)

**Archetype**: Homelab enthusiast / privacy-conscious engineer running a personal "second brain" stack.

**Context**:

- Runs Nextcloud, Immich, Paperless-ngx, and Neo4j on a home server already.
- Will only adopt tools that run fully on his own hardware.
- Wants integration points (webhooks, API access) so he can wire zkast into his existing pipelines.

**Goals**:

- Drop zkast into his Docker Compose stack and have it work in under 30 minutes.
- Point zkast at his existing Neo4j and his existing Postgres without any data being sent off his network.
- Use a local Ollama instance for inference whenever possible (P1+). In P0 he tolerates Cohere as the single cloud dependency while local-model support is in flight.

**Frustrations**:

- Self-hosted AI tools that secretly phone home or require a SaaS account to log in.
- Tools that hard-code a single LLM provider permanently and cannot evolve to use his local models. (He accepts a single-provider P0 only because the roadmap is explicit about adding Ollama in P1.)
- Tools that demand their own database and cannot integrate with the one he already runs.

**Success criteria**:

- The entire stack works offline once models are pulled, with telemetry off by default.
- He can configure zkast to use his existing Neo4j as the **external persistence target** without zkast standing up a competing instance.
- He can read and reason about every container running in his stack.

**Primary flows**:

- First-run Docker Compose with `COHERE_API_KEY` set in P0; swap to `OLLAMA_BASE_URL` in P1 once Ollama support ships.
- Configure his external Neo4j once, then forget about it.
- Inspect OpenTelemetry traces in his existing observability stack when something goes wrong.

**Maps to phase**: P0 single-user, often upgrading to P1 to share with family or collaborators.

## P-4 — Priya the PM (SaaS Subscriber)

**Archetype**: Senior product manager at a mid-size company. Reads industry analyst reports, internal strategy decks, and customer interview transcripts.

**Context**:

- Does not run Docker. Does not have an LLM API key personally.
- Pays for SaaS tools out of a team budget.
- Comfortable in Notion, Figma, Google Docs; not comfortable with self-hosting anything.

**Goals**:

- Drop in 50–100 PDFs (analyst reports, customer interview transcripts) and get a usable map of themes.
- Share interesting subgraphs with her team.
- Have the heavy lifting (database, infra, API keys) abstracted away.

**Frustrations**:

- Self-hosted tools are inaccessible to her.
- SaaS tools that don't make it obvious where her data lives and how to delete it.
- Per-seat pricing that punishes light users on her team.

**Success criteria**:

- Sign up with SSO and have a working ingestion pipeline within five minutes.
- Share a read-only view of a graph with a teammate via a link.
- Export a snapshot to her organization's Neo4j if asked by IT.

**Primary flows**:

- Sign up -> connect Google account -> upload first PDF -> see graph.
- Invite a colleague to view-only access on one workspace.
- Configure the team's external Neo4j AuraDB credentials so any approved member can persist to it.
- **Ask the chat questions about themes across her customer interviews** ("What did enterprise customers say about pricing?") and paste the answer — with its citations — into a strategy doc.

**Maps to phase**: P2 SaaS.

## P-5 — Ada the Admin (Workspace Admin)

**Archetype**: Tech lead or knowledge management lead at a small team running zkast self-hosted.

**Context**:

- Operates the team's self-hosted zkast instance on a shared server.
- Responsible for inviting users, managing access, rotating API keys, and reviewing the audit log.
- Not the primary content author; her job is to keep the platform healthy and trustworthy.

**Goals**:

- Onboard new team members with the correct role in under five minutes.
- Ensure shared API keys and external target credentials are rotated without breaking active jobs.
- Know who did what, when, especially around persistence to external graph databases.

**Frustrations**:

- Tools that treat admin as an afterthought (no role granularity, no audit trail, secrets in plain config files).
- Forced upgrades that change the auth model without warning.

**Success criteria**:

- She can invite a user, assign them a role, and remove them again without restarting anything.
- She can rotate an LLM API key while ingestion jobs are running and have them transparently pick up the new key on retry.
- She can answer "who pushed snapshot X to our production Neo4j on Tuesday?" from the audit log.

**Primary flows**:

- Invite / remove / re-role workspace members.
- Configure and rotate workspace-level API keys and external graph target credentials.
- Review audit log entries filtered by member, action type, and target.

**Maps to phase**: P1 self-hosted multi-user, carries forward into P2.

## Cross-Persona Themes

- **Data ownership is non-negotiable**. P-1, P-2, P-3, and P-5 will all reject zkast if it tries to own their graph data.
- **BYO LLM is the default mental model**. Even the SaaS persona (P-4) tolerates managed keys only because the underlying graph still lands in a database she controls.
- **Review before persistence** is a load-bearing UX promise across all personas; nobody wants the LLM to silently write to their production graph DB.
- **Grounded chat with citations** is the answer to "what do I do with all these atomic notes?" Every persona expects natural-language Q&A over their own corpus; every persona insists those answers cite source notes/PDFs so they can verify before quoting.
- **Custom entity / edge types** appear repeatedly (P-2's citation network, P-4's customer themes, P-5's domain ontology) — the system must support workspace-defined types from P1 onward.

## Related Specifications

- [prd.md](prd.md) — Goals, requirements, and phases that these personas validate.
- [userstories.md](userstories.md) — Concrete stories that satisfy each persona's primary flows.
- [uiux.md](uiux.md) — UI flows and accessibility commitments these personas rely on.
