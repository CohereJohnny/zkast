# Sprint A report

**Status**: Complete on branch `sprints/sprint-a`.
**Build**: web `tsc --noEmit` and `pnpm run build` green; pipeline North tests **29 passed** (`test_north_client_auth.py`, `test_north_transcript_episodes.py`).
**Spec**: [north-agents-amem.md](../../specs/openspecs/north-agents-amem.md) — FR-1 through FR-5 (source foundation).

## Goal

Establish **North as a first-class ingestion source** alongside PDFs: encrypted connectivity, agent registration/sync, conversation cache, transcript import into the existing document → episode → notes → graph pipeline, and **agent_id provenance** on all North-derived artifacts.

## Shipped

| Area | Summary |
| ---- | ------- |
| **Connectivity** | Per-workspace `north_base_url` + encrypted `north_bearer`; Settings **Test North** with isolated busy state; server-only credential use. |
| **Agents** | `north_agents` CRUD/sync; uniqueness per workspace+provider; sync cursor persistence; list/detail UI at `/agents`. |
| **Conversation cache** | `north_conversation_cache`; list/refresh/import; normalized payload roots for replay. |
| **Import spine** | `north_conversation` documents require `agent_id`; `transcript_episodes` segmentation; **422 `north_empty_transcript`** dry-run before insert; dedupe by checksum; `parse_document` → existing worker stages. |
| **User surface** | `/conversations` library route; `DocumentsPanel` `library="conversations"`; import registers `registerActiveJob`; graph **source** filter (`source_kind` / `SourcePicker`). |
| **Workspace UX** | Documents panel only on `/documents`; pipeline log docked under **Documents** and **Conversations**; README transparency section. |
| **Tests** | North client auth/normalization; episode builder + empty-transcript guard; agent_id on episode rows. |

## Definition of done

- [x] Configure North credentials and verify connectivity.
- [x] Sync/register North agents.
- [x] Import conversation → agent-scoped documents/episodes → notes/graph pipeline.
- [x] PDF ingestion regression path unchanged.
- [x] Automated Sprint A tests pass; web build green.
- [ ] **Manual smoke** — live North tenant (operator).

## Next

Sprint B — A-MEM enrichment, agent-scoped note embeddings, mixed workspace views ([sprint_b_tasks.md](../sprint-b/sprint_b_tasks.md)).
