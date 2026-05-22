# North typography — fonts for external apps

## Production North fonts

North uses **Unica77 Cohere** (regular, medium, bold) via `next/font/local` in `js/apps/assistants_web/src/app/fonts.ts`. Font files live under `js/apps/assistants_web/public/fonts/` and are **proprietary** — do not redistribute binaries in the skill or external repos without a license.

Locale fallbacks in North:

- Korean: Noto Sans KR
- Japanese: Noto Sans JP
- Arabic: Noto Sans Arabic

## Recommended open-source stack (external apps)

Use this stack to approximate North’s neutral, modern look:

| Role | Font | npm / Google |
|------|------|----------------|
| UI sans | **Inter** or **Geist Sans** | `next/font/google` |
| Mono (labels, captions) | **IBM Plex Mono** | `next/font/google` |

### Example (`app/layout.tsx`)

```tsx
import { IBM_Plex_Mono, Inter } from 'next/font/google';

const fontSans = Inter({
  subsets: ['latin'],
  variable: '--font-family-regular',
  display: 'swap'
});

const fontMono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500'],
  variable: '--font-mono-regular',
  display: 'swap'
});

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${fontSans.variable} ${fontMono.variable}`}>
      <body className="font-regular antialiased">{children}</body>
    </html>
  );
}
```

Wire tokens in `tailwind-tokens.css` (already vendored):

```css
@theme inline {
  --font-regular: var(--font-family-regular), system-ui, sans-serif;
  --font-mono: var(--font-mono-regular), ui-monospace, monospace;
}
```

Apply utilities: `font-regular` on `body`, `font-mono` on `text-label` / `text-caption` variants via the `Text` component.

## Bold headings

North maps semibold headings to the brand variable font. With Inter/Geist, `font-semibold` on `text-h1` … `text-h5` is sufficient for external parity.
