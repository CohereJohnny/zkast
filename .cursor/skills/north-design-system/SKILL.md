---
name: north-design-system
description: >-
  Reproduces Cohere North UI in Next.js apps using semantic OKLCH tokens,
  Tailwind v4, shadcn new-york patterns, and vendored reference components.
  Use when building North-styled UIs, bootstrapping design tokens, matching
  @cohere-ai/ui look and feel, or reskinning apps to the North design language.
---

# North Design System

Recreate **Cohere North** look and feel in external Next.js apps using the vendored `kit/` in this skill.

## When to use

- Greenfield Next.js app that should match North / `@cohere-ai/ui`
- Reskinning an existing app to North tokens and components
- Auditing UI for semantic-token compliance
- After North token changes — re-run sync (below)

## Non-negotiables

1. **Semantic colors only** — `bg-primary`, `text-foreground`, `border-border`; never `bg-gray-900`, `text-blue-500`
2. **`cn()` from kit** — extended `tailwind-merge` for custom `text-h1`, `z-modal`, etc.
3. **CVA + Radix** — variants via `class-variance-authority`; composition via `asChild`
4. **Dark mode** — `next-themes` with `attribute="class"` on `<html>`
5. **Kit components first** — `Button`, `Card`, `Input` before raw HTML
6. **Default density** — `text-sm` on controls; buttons `h-9`

## Quick bootstrap

Follow [BOOTSTRAP.md](BOOTSTRAP.md) end-to-end. Summary:

1. Install deps → [DEPENDENCIES.md](DEPENDENCIES.md)
2. Copy `kit/styles/*`, `kit/lib/*`, `kit/components/*` into the target app
3. Wire `globals.css` using [kit/styles/global-snippet.css](kit/styles/global-snippet.css)
4. Add fonts per [kit/fonts/FONTS.md](kit/fonts/FONTS.md)
5. Wrap app in `ThemeProvider` (`attribute="class"`)
6. Verify with checklist in BOOTSTRAP.md

## Vendored kit layout

```
kit/
├── styles/theme.css           # OKLCH palette + semantic vars + @theme inline
├── styles/tailwind-tokens.css # Typography, spacing, z-index, shadows
├── styles/global-snippet.css  # Minimal globals merge target
├── lib/cn.ts                  # cn() + tailwind-merge extensions
├── lib/slot.ts                # data-slot constants
├── components/                # button, card, input, label, badge, separator, dialog, tooltip, text
├── shadcn/components.json     # new-york, cssVariables
└── fonts/FONTS.md             # Unica77 note + Inter/IBM Plex Mono fallbacks
```

## Token quick reference

### Semantic colors (light)

| Class | Role |
|-------|------|
| `bg-background` / `text-foreground` | Page |
| `bg-primary` / `text-primary-foreground` | Primary CTA |
| `bg-secondary` | Secondary surfaces |
| `text-muted-foreground` | Helper text |
| `bg-destructive` | Errors |
| `bg-success` / `bg-caution` | Status |
| `text-link` or `text-[var(--link)]` | Links |
| `border-border` | Borders |

Base radius: **0.6rem** (`--radius`). Cards: `rounded-xl`.

### Typography utilities

| Class | Use |
|-------|-----|
| `text-p` | Body (0.875rem) |
| `text-h1` … `text-h5` | Headings (desktop) |
| `text-h1-m` … `text-h5-m` | Headings (mobile) |
| `text-label` | Mono uppercase labels |
| `text-caption` | Mono meta |

Prefer `<Text styleAs="h2" />` from `kit/components/text.tsx`.

Full spec: [DESIGN-LANGUAGE.md](DESIGN-LANGUAGE.md).

## Component selection

| UI need | Kit component |
|---------|---------------|
| CTA | `Button` |
| Surface | `Card` |
| Form | `Label` + `Input` |
| Status | `Badge` |
| Modal | `Dialog` |
| Tooltip (many) | `LazyTooltip` |
| Title | `Text` |
| Divider | `Separator` |

Catalog and monorepo-only components: [COMPONENT-CATALOG.md](COMPONENT-CATALOG.md). Icons: [kit/components/icon-usage.md](kit/components/icon-usage.md).

## Sync from North monorepo

When tokens or primitives change in North:

```bash
bash .cursor/skills/north-design-system/scripts/sync-from-north.sh
```

Re-applies import paths and copies canonical files from `js/packages/ui` and `js/apps/assistants_web`. After sync, confirm `dialog.tsx` still uses Lucide `X` (not `Icon`).

## Use in other repositories

This skill lives under **North** `.cursor/skills/`. For other projects:

```bash
cp -R /path/to/north/.cursor/skills/north-design-system ~/.cursor/skills/
```

Or symlink the directory. Cursor discovers skills in `~/.cursor/skills/` globally.

## Limitations

- **Fonts**: Unica77 is proprietary; external apps use Inter/Geist + IBM Plex Mono ([FONTS.md](kit/fonts/FONTS.md))
- **~10 primitives** vendored, not full 80+ `@cohere-ai/ui` components
- **Whitelabel** customer overrides not included
- **Product UI** (Composer, Automations, chat) must be rebuilt from patterns
- **i18n**: North uses `UiLabels` in the UI package; external apps use `next-intl` or hardcoded strings

## Reference in North repo

| Resource | Path |
|----------|------|
| UI package | `js/packages/ui/` |
| App tokens | `js/apps/assistants_web/src/styles/tailwind.config.css` |
| Storybook tokens | `js/packages/ui/src/stories/tokens/` |
| Styling rules | `.cursor/rules/ui-and-styling.mdc` |
| Design Storybook | `pnpm storybook` (port 6007) |

## Additional resources

- [DESIGN-LANGUAGE.md](DESIGN-LANGUAGE.md) — colors, type, spacing, patterns
- [COMPONENT-CATALOG.md](COMPONENT-CATALOG.md) — kit vs monorepo components
- [BOOTSTRAP.md](BOOTSTRAP.md) — full setup steps
- [DEPENDENCIES.md](DEPENDENCIES.md) — pinned versions
