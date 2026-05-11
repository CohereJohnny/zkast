# zkast — Backlog (P2 and beyond)

Items deferred from P0/P1. Pull into a sprint when prioritized. Reference specs where relevant.

## P2 — SaaS and multi-tenant

- Hosted deployment (Vercel + managed Postgres + Fly.io/Render pipeline) per [techstack.md](../specs/techstack.md).
- Supabase Auth + SSO (Google, GitHub) ([prd.md](../specs/prd.md) P2).
- Per-tenant quotas, rate limits, billing ([userstories.md](../specs/userstories.md) Epic 9).
- Share read-only graph snapshot links without account ([userstories.md](../specs/userstories.md) US-9.2).
- Managed external-target provisioning (still user-owned credentials).

## Features (nice-to-have)

- OCR for image-only / scanned PDFs ([prd.md](../specs/prd.md) NG-4).
- Non-PDF ingestion (EPUB, DOCX, HTML).
- Real-time collaborative editing ([prd.md](../specs/prd.md) NG-5).
- Native mobile apps ([prd.md](../specs/prd.md) NG-6).
- Agentic chat (tools, web browse, code execution) — explicitly out of P0 grounded chat ([prd.md](../specs/prd.md) NG-2 nuance).

## Integrations

- Amazon Neptune / Kuzu as optional Graphiti backends ([techstack.md](../specs/techstack.md)).
- Webhooks for job completion ([apis.md](../specs/apis.md) P2).

## Parking lot

- Community i18n beyond English ([prd.md](../specs/prd.md) NFR-10).
- Plugin API for custom extractors.
