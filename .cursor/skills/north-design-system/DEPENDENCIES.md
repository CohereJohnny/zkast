# North design system — dependencies

Pin these versions to stay aligned with the North monorepo (`js/pnpm-workspace.yaml` catalog).

## Required

| Package | Version | Purpose |
|---------|---------|---------|
| `tailwindcss` | 4.1.18 | CSS-first Tailwind v4 |
| `@tailwindcss/postcss` | 4.1.18 | PostCSS plugin |
| `postcss` | ^8 | PostCSS |
| `tw-animate-css` | 1.4.0 | Accordion/dialog animations (imported in theme.css) |
| `class-variance-authority` | 0.7.1 | Component variants |
| `clsx` | ^2 | Class lists |
| `tailwind-merge` | ^2 | `cn()` deduplication |
| `radix-ui` | 1.4.3 | Primitives (Dialog, Tooltip, Label, Separator, Slot) |
| `lucide-react` | 0.546.0 | Icons |
| `next-themes` | 0.4.6 | Dark mode (`attribute="class"`) |

## Peer (Next.js app)

| Package | Version |
|---------|---------|
| `next` | 15.x or 16.x (App Router) |
| `react` | 19.2.4 |
| `react-dom` | 19.2.4 |

## Optional

| Package | Purpose |
|---------|---------|
| `@tailwindcss/typography` | Prose/markdown styling |
| `sonner` | Toasts (dialog click-outside checks reference sonner attrs) |

## Install (external app)

```bash
npm install tailwindcss@4.1.18 @tailwindcss/postcss@4.1.18 postcss tw-animate-css@1.4.0 \
  class-variance-authority@0.7.1 clsx tailwind-merge radix-ui@1.4.3 lucide-react@0.546.0 next-themes@0.4.6
```

## shadcn CLI

Initialize with the vendored config:

```bash
npx shadcn@latest init -c ./path-to-kit/shadcn/components.json
```

Style: **new-york**, `cssVariables: true`, base color **neutral**.
