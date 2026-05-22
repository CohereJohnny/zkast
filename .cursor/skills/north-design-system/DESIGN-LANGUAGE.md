# Cohere North — design language

Distilled from `@cohere-ai/ui`, `assistants_web`, and `.cursor/rules/ui-and-styling.mdc`.

## Principles

1. **Semantic tokens only** — never `text-gray-500`, `bg-zinc-900`, or fixed hex in components.
2. **Whitelabel-safe** — colors flow through CSS variables (`--primary`, `--background`, …).
3. **Compact density** — default controls are `text-sm`, buttons `h-9`.
4. **shadcn new-york** — CVA variants, Radix primitives, `asChild` composition.
5. **Dark mode** — class-based (`.dark` on `<html>`), inverted gray ramp.

## Color system

### Raw palette (`theme.css`)

OKLCH gray scale `--ds-gray-5` (near black) through `--ds-gray-100` (white). Status colors:

- `--ds-danger` — destructive / errors
- `--ds-success` — success states
- `--ds-caution` — warnings
- `--ds-blue` — links

### Semantic mapping (light mode)

| Token | Typical use |
|-------|-------------|
| `--background` | Page canvas (`ds-gray-95`) |
| `--foreground` | Body text (`ds-gray-5`) |
| `--primary` | Primary buttons (`ds-gray-10`) |
| `--primary-foreground` | Text on primary |
| `--secondary` | Secondary surfaces |
| `--muted` / `--muted-foreground` | Subtle backgrounds / helper text |
| `--accent` | Hover states |
| `--destructive` | Errors |
| `--success` / `--caution` | Status badges |
| `--link` | Links |
| `--border` / `--input` / `--ring` | Borders and focus |
| `--sidebar-*` | Side navigation |
| `--radius` | **0.6rem** base radius |

Dark mode inverts: light text on `ds-gray-15` background, primary becomes light gray.

### Tailwind usage

```tsx
<div className="bg-background text-foreground border-border" />
<button className="bg-primary text-primary-foreground hover:bg-primary/90" />
<p className="text-muted-foreground" />
<span className="text-destructive" />
```

## Typography

Defined in `tailwind-tokens.css` as `--text-*` utilities.

| Utility | Size | Use |
|---------|------|-----|
| `text-p` | 0.875rem | Default body |
| `text-p-sm` / `text-p-xs` | smaller | Dense UI |
| `text-h1` … `text-h5` | large | Headings (desktop) |
| `text-h1-m` … `text-h5-m` | smaller | Headings (mobile) |
| `text-label` | 0.75rem | Form labels — **mono, uppercase** |
| `text-caption` | 0.75rem | Meta — **mono** |
| `text-overline` | 0.875rem | Section labels — **mono, uppercase** |

Use the vendored `Text` component with `styleAs` for responsive heading pairs (`text-h1-m lg:text-h1`).

## Spacing and layout

Semantic spacing from `tailwind-tokens.css`:

- `left-panel-collapsed` / `left-panel-expanded` — nav widths
- `icon-xs` … `icon-xl` — icon boxes
- `cell-xs` … `cell-xl` — table/list row heights
- `max-w-message` — chat content width (976px)
- `max-w-modal` / `w-modal` — dialogs

Z-index utilities: `z-modal`, `z-tooltip`, `z-backdrop`, etc. Register new tokens in `cn.ts` tailwind-merge config when adding `--z-index-*`.

## Elevation

- Cards: `rounded-xl border py-6 shadow-sm`
- Menus: `--shadow-menu`
- Modals: `shadow-lg`, `z-modal`, `max-h-modal`

## Components — visual signatures

### Button

Variants: `default`, `destructive`, `outline`, `secondary`, `ghost`, `link`. Sizes: `default` (h-9), `sm`, `lg`, `xl`, `icon`.

### Badge

Pill, `rounded-full`, variants include `success`, `caution`, `info` (highlight).

### Card

`rounded-xl`, `gap-6`, subcomponents: Header, Title, Description, Content, Footer, Action.

### Dialog

Centered modal, muted overlay (`bg-muted/50`), close button top-right, optional `max-w-modal` on large screens.

### Tooltip

Dark default (`bg-foreground text-background`), `text-xs`, optional arrow. Use `LazyTooltip` in lists (see COMPONENT-CATALOG).

## Accessibility

- Focus: `focus-visible:outline-[3px]`, `outline-ring/50`
- Invalid: `aria-invalid:border-destructive`
- Dialog close: `sr-only` label
- Prefer semantic HTML + Radix primitives

## Anti-patterns

- Hardcoded Tailwind grays/blues
- Raw `<button>` when `Button` exists
- Regular `Tooltip` in long lists (use `LazyTooltip`)
- Custom colors outside CSS variables
