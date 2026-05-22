# Bootstrap North UI in a new Next.js app

Step-by-step for App Router + Tailwind v4. See [DEPENDENCIES.md](DEPENDENCIES.md) for versions.

## 1. Install dependencies

```bash
npm install tailwindcss@4.1.18 @tailwindcss/postcss@4.1.18 postcss tw-animate-css@1.4.0 \
  class-variance-authority@0.7.1 clsx tailwind-merge radix-ui@1.4.3 lucide-react@0.546.0 next-themes@0.4.6
```

## 2. Copy kit files

From this skill’s `kit/` directory:

```
kit/styles/theme.css          → src/styles/theme.css
kit/styles/tailwind-tokens.css → src/styles/tailwind-tokens.css
kit/styles/global-snippet.css  → merge into src/app/globals.css
kit/lib/*                     → src/lib/north-ui/   (or src/lib/)
kit/components/*              → src/components/ui/
```

## 3. PostCSS

`postcss.config.mjs`:

```js
export default {
  plugins: {
    '@tailwindcss/postcss': {}
  }
};
```

## 4. Global CSS

`src/app/globals.css` (start from `kit/styles/global-snippet.css`):

```css
@import 'tailwindcss';
@custom-variant dark (&:where(.dark, .dark *));
@import 'tw-animate-css';
@import '../styles/tailwind-tokens.css';
@import '../styles/theme.css';
```

Adjust paths if you use `src/styles/` at project root.

## 5. Fonts

Follow [kit/fonts/FONTS.md](kit/fonts/FONTS.md). Set `--font-family-regular` and `--font-mono-regular` on `<html>`.

## 6. Root layout

```tsx
import { ThemeProvider } from 'next-themes';
import './globals.css';

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="font-regular antialiased">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
```

## 7. TypeScript paths (optional)

`tsconfig.json`:

```json
{
  "compilerOptions": {
    "paths": {
      "@/*": ["./src/*"]
    }
  }
}
```

Update vendored imports from `../lib/cn` to `@/lib/north-ui/cn` if you relocate files.

## 8. shadcn init (optional)

```bash
npx shadcn@latest init
```

Point `components.json` at `kit/shadcn/components.json` values: new-york, cssVariables, neutral.

## 9. Verify page

```tsx
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Text } from '@/components/ui/text';

export default function Home() {
  return (
    <main className="bg-background text-foreground min-h-screen p-8">
      <Text styleAs="h2" className="mb-4">
        North UI
      </Text>
      <Card className="max-w-md">
        <CardHeader>
          <CardTitle>Card</CardTitle>
        </CardHeader>
        <CardContent className="flex gap-2">
          <Button>Primary</Button>
          <Button variant="outline">Outline</Button>
        </CardContent>
      </Card>
    </main>
  );
}
```

Toggle dark mode: `<html className="dark">` or `next-themes` toggle.

## Checklist

- [ ] Page background `bg-background`, text `text-foreground`
- [ ] Primary button dark-on-light / light-on-dark in both themes
- [ ] Card border and radius match North (`rounded-xl`)
- [ ] Focus ring visible on Tab through buttons
- [ ] Typography: `text-p` body, `Text styleAs="h2"` for headings

## Syncing updates from North

When working in the North monorepo:

```bash
bash .cursor/skills/north-design-system/scripts/sync-from-north.sh
```

Re-copy changed files into your external app as needed.
