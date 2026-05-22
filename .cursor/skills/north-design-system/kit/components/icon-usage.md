# Icons in North UI

North’s full `icon.tsx` (~700 lines) maps semantic names (`close`, `caret-down`, …) to Lucide icons. The vendored kit does **not** include that file.

## External apps

Use **lucide-react** directly:

```tsx
import { ChevronDown, X } from 'lucide-react';

<X className="size-4" />
<ChevronDown className="size-4 text-muted-foreground" />
```

Match North sizing: `size-4` (16px) in buttons/dialogs; `size-3` in badges.

## Dialog close

The kit `dialog.tsx` uses `<X className="size-4" />` instead of `<Icon name="close" />`.

## Porting the full Icon component

If you need North’s alias map, copy `js/packages/ui/src/components/icon.tsx` into your app and fix imports. Prefer Lucide direct imports for greenfield apps.
