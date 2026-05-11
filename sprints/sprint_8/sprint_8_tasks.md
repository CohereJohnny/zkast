# Sprint 8 — Polish, Observability, Accessibility, Release

**Duration**: 2 weeks  
**Goal**: Production-harden P0: **job cancel** everywhere (**US-7.2**), retry partial ingestion (**US-7.1**), **command palette** + keyboard shortcuts (**uiux.md**), exhaustive **states** on all primary views, **WCAG 2.1 AA** verification against [uiux.md](../../specs/uiux.md) Accessibility + **UI Implementation Acceptance Checklist**, performance budgets (**NFR-4**, chat TTFT **uiux.md**), Docker Compose hardening, **sample PDF** onboarding (**uiux.md** Empty/Sample-Data Mode), README polish, **`v0.1.0`** tag. **US-7.1–US-7.3**, polish items from **FR/NFR** gaps.

## Inputs

- Feature-complete P0 from Sprint 7.

## Outputs

- Release candidate suitable for self-hosted early adopters.
- Tagged **`v0.1.0`**.

## Dependencies

- **Sprint 7** complete.

---

## Web tier

- [ ] Command palette (`Cmd/Ctrl+K`) — navigation + actions (**uiux.md**).
- [ ] Full keyboard shortcut map (`?`) (**uiux.md** Keyboard Shortcuts).
- [ ] Ensure focus rings, skip link, landmarks on all routes (**Accessibility**).
- [ ] Light theme parity OR explicit defer documented with contrast audit on dark-only (**uiux.md**).
- [ ] High contrast + Atkinson Hyperlegible toggles (**uiux.md** Operator-Facing Accessibility Settings).
- [ ] Z-index band audit for drawer/modals/toasts (**uiux.md** Stacking Context).
- [ ] Toast/banner/modal patterns finalized (**uiux.md** Notification System).

## Pipeline service

- [ ] Cancel: ingestion runs + persistence jobs + chat turns — unified cancel semantics (**apis.md**).
- [ ] Retry from last successful stage (**US-7.1** AC-2).
- [ ] Rate-limit handling with visible UX messaging (**NFR-6**).
- [ ] OTEL traces linked from Document Detail / failed jobs (**US-7.1** AC-3 self-hosted).

## Data + migrations

- [ ] Audit indexes for hot paths; vacuum/analyze notes in README.

## Infra + Docker

- [ ] Non-root containers where feasible; resource limits documented.
- [ ] Healthchecks for all services.
- [ ] `.env.example` final pass — no optional vars undocumented.

## Design + UX

- [ ] Run full **UI Implementation Acceptance Checklist** ([uiux.md](../../specs/uiux.md)); file gaps in [tech_debt.md](../tech_debt.md) if any remain consciously open.

## Docs

- [ ] README: architecture diagram, troubleshooting, FAQ.
- [ ] Sample PDF bundled with open license + attribution file.
- [ ] CHANGELOG.md initial **v0.1.0** entry.

## Release engineering

- [ ] Version bump web + pipeline (`/version` endpoints).
- [ ] Git tag `v0.1.0` + release notes (GitHub Release optional).

---

## Definition of Done

- [ ] `pnpm run build` passes; pipeline tests green.
- [ ] Manual smoke script documented: upload → notes → graph → chat → persist.
- [ ] Lighthouse/accessibility spot-check on Chat + Graph routes OR axe-ci stub.
- [ ] Telemetry defaults verified OFF self-hosted (**US-7.3**).

## Risks and mitigations

| Risk | Mitigation |
| ---- | ---------- |
| Perf regressions | Profile graph render + chat TTFT before tagging |
| Scope creep | Move non-blockers to [backlog.md](../backlog.md) |

## Out of scope

- P1 auth/multi-user (**sprintplan.md** Sprint 9+).

---

## Sprint review (fill at end)

### Demo readiness

### Gaps / issues

### Next steps (P1)
