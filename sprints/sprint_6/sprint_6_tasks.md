# Sprint 6 — Grounded Chat (Core)

**Duration**: 2 weeks  
**Goal**: Backend-first **chat turn**: hybrid retrieval → **Cohere Rerank** → **Cohere Chat** with documents + grounded citations; persist **`ChatSession`**, **`ChatMessage`**, **`RetrievalRecord`**, **`ChatCitation`**; **SSE** streaming (`token`, `citation`, `retrieval_complete`, `message_complete`, failures); **stop** streaming; **refusal** when no context (**FR-35–FR-39**, **FR-41**, **FR-45**, **US-8.1**, **US-8.2**, **US-8.4**, **US-8.8**, **US-8.9**).

## Inputs

- Working graph + notes from Sprint 4–5.
- Cohere integration from Sprint 2.

## Outputs

- Minimal chat UI enough to verify: single session, send message, stream answer, see citations mapped to note/document (**can be developer panel** if full UX waits for Sprint 7 — prefer thin functional UI).

## Dependencies

- **Sprint 5** complete (graph data richness helps retrieval quality).

---

## Web tier

- [ ] API routes wrapping [apis.md](../../specs/apis.md): create session, post message, GET stream (`text/event-stream`), POST cancel.
- [ ] Client SSE parser with reconnect + `Last-Event-ID` (**apis.md** stream contract).
- [ ] Minimal transcript renderer + citation chips (full polish Sprint 7).

## Pipeline service

- [ ] `POST /internal/v1/chat/turns` implementation (**apis.md** Internal Contract).
- [ ] Retrieval: Graphiti search scoped by session filters / snapshot pin (**FR-40** groundwork).
- [ ] Assemble grounding documents with stable ids for Cohere document array (**techstack.md** Grounded Chat section).
- [ ] Map Cohere citation document refs → zkast `ChatCitation.sources` (**datamodel.md**).
- [ ] Persist `RetrievalRecord` before LLM call (**FR-41**).
- [ ] Refusal path without hallucination (**FR-45**).
- [ ] Cancel: cooperative cancellation of async generator (**US-8.8**).

## Data + migrations

- [ ] Tables: `chat_sessions`, `chat_messages`, `retrieval_records`, `chat_citations` per [datamodel.md](../../specs/datamodel.md).
- [ ] Regeneration fields: `parent_message_id`, `is_active_alternate` (prepare for Sprint 7).

## Infra + Docker

- [ ] SSE proxy timeouts: nginx/load balancer buffer disabled (`proxy_buffering off`) documented.

## Design + UX

- [ ] Live region throttling plan for streaming (**uiux.md** Accessibility).

## Docs

- [ ] Sequence diagram for chat turn (mirror **uiux.md** flow).

---

## Definition of Done

- [ ] Ask question → grounded answer cites at least one note when corpus relevant (**SM-6** directionally).
- [ ] Empty corpus → explicit refusal (**US-8.9**).
- [ ] Stop cancels within 1s (**US-8.8** AC-2).
- [ ] Retrieval inspector data identical when reopened (**US-8.4** AC-3).

## Risks and mitigations

| Risk | Mitigation |
| ---- | ---------- |
| Cohere citation schema changes | Version pin + adapter tests |
| Token budget blowups | Enforce per-turn doc token cap (**techstack.md**) |

## Out of scope

- Chat Home, Drawer, scope picker UX (**Sprint 7**).
- External Neo4j/AGE writer (**Sprint 7**).

---

## Sprint review (fill at end)

### Demo readiness

### Gaps / issues

### Next sprint prep
