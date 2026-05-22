# North UI — component catalog

## Vendored kit (`kit/components/`)

Portable primitives synced from `@cohere-ai/ui`. Copy into `src/components/ui/` in external apps.

| File | Exports | Variants / notes |
|------|---------|------------------|
| `button.tsx` | `Button`, `buttonVariants` | default, destructive, outline, secondary, ghost, link; sizes sm–xl, icon |
| `card.tsx` | `Card`, `CardHeader`, `CardTitle`, … | Surface layout |
| `input.tsx` | `Input` | h-9, ring focus, `aria-invalid` styles |
| `label.tsx` | `Label` | Radix Label |
| `badge.tsx` | `Badge`, `badgeVariants` | default, success, caution, secondary, destructive, outline, info |
| `separator.tsx` | `Separator` | horizontal / vertical |
| `dialog.tsx` | `Dialog`, `DialogContent`, … | Close uses Lucide `X`; `ModalContext` for nesting |
| `tooltip.tsx` | `Tooltip`, `LazyTooltip`, … | default, outline, primary; prefer **LazyTooltip** in grids |
| `text.tsx` | `Text`, `textVariants` | Typography scale |

Supporting libs: `kit/lib/cn.ts`, `slot.ts`, `use-as-ref.ts`, `modal-context.tsx`, `direction.tsx`.

Icons: see `icon-usage.md` (use `lucide-react` directly).

## Monorepo-only (reference paths)

Do not vendor — product-specific or heavy deps.

| Component | Path | Why skipped |
|-----------|------|-------------|
| `hierarchical-suggester` | `js/packages/ui/src/components/hierarchical-suggester.tsx` | Domain-specific |
| `pdf-preview` | `js/packages/ui/src/components/pdf-preview.tsx` | PDF.js bundle |
| `events-tree` | `js/packages/ui/src/components/events-tree.tsx` | Chat tooling |
| `connection-chip` | `js/packages/ui/src/components/connection-chip.tsx` | Integrations |
| `sidebar` | `js/packages/ui/src/components/sidebar.tsx` | Large, app-coupled |
| `icon` | `js/packages/ui/src/components/icon.tsx` | 700-line alias map |
| `command`, `combobox` | `js/packages/ui/src/components/` | Add via shadcn + North tokens |
| `data-table` | assistants_web | App layer |

## shadcn alignment

`kit/shadcn/components.json`:

- **style**: `new-york`
- **cssVariables**: true
- **baseColor**: neutral
- **css**: `src/styles/theme.css`

Add more primitives with `npx shadcn add <component>` after tokens are wired.

## Selection guide

| Need | Use |
|------|-----|
| Primary action | `Button variant="default"` |
| Cancel / secondary | `Button variant="outline"` or `ghost` |
| Destructive confirm | `Button variant="destructive"` |
| Form field | `Label` + `Input` |
| Status chip | `Badge variant="success|caution|destructive"` |
| Section surface | `Card` |
| Modal | `Dialog` + `DialogContent` |
| Hint on icon | `LazyTooltip` |
| Page title | `Text styleAs="h2"` |
| Divider | `Separator` |

## App-layer patterns (assistants_web)

| Component | Path |
|-----------|------|
| `Text` (canonical) | `js/apps/assistants_web/src/components/UI/Text.tsx` |
| `LinkButton` | `js/apps/assistants_web/src/components/UI/` |
| Composer, Automations UI | `js/apps/assistants_web/src/components/` |

Rebuild these in external apps using kit primitives + semantic tokens.
