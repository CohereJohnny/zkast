#!/usr/bin/env bash
# Sync vendored North design-system files from canonical monorepo paths.
# Run from repository root: bash .cursor/skills/north-design-system/scripts/sync-from-north.sh

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SKILL_DIR="${REPO_ROOT}/.cursor/skills/north-design-system"
KIT="${SKILL_DIR}/kit"

UI="${REPO_ROOT}/js/packages/ui"
APP="${REPO_ROOT}/js/apps/assistants_web"

mkdir -p "${KIT}/styles" "${KIT}/lib" "${KIT}/components" "${KIT}/shadcn" "${KIT}/fonts"

echo "Syncing North design tokens and config into ${KIT}..."

cp "${UI}/src/styles/theme.css" "${KIT}/styles/theme.css"
cp "${APP}/src/styles/tailwind.config.css" "${KIT}/styles/tailwind-tokens.css"
cp "${UI}/components.json" "${KIT}/shadcn/components.json"
cp "${UI}/src/helpers/utils.ts" "${KIT}/lib/cn.ts"

COMPONENTS=(
  button
  card
  input
  label
  badge
  separator
)

for name in "${COMPONENTS[@]}"; do
  cp "${UI}/src/components/${name}.tsx" "${KIT}/components/${name}.tsx"
done

cp "${UI}/src/components/dialog.tsx" "${KIT}/components/dialog.tsx"
cp "${UI}/src/components/tooltip.tsx" "${KIT}/components/tooltip.tsx"
cp "${APP}/src/components/UI/Text.tsx" "${KIT}/components/text.tsx"

echo "Applying import-path adaptations..."

# cn utility header
cat > "${KIT}/lib/cn.ts" << 'HEADER'
// Vendored from North @cohere-ai/ui — sync via scripts/sync-from-north.sh

HEADER
tail -n +1 "${UI}/src/helpers/utils.ts" >> "${KIT}/lib/cn.ts"

# Adapt @/ imports in synced components to kit-relative paths
if [[ "$(uname)" == "Darwin" ]]; then
  SED_INPLACE=(-i '')
else
  SED_INPLACE=(-i)
fi

for f in "${KIT}/components/"*.tsx; do
  sed "${SED_INPLACE[@]}" \
    -e "s|from '@/helpers/utils'|from '../lib/cn'|g" \
    -e "s|from '@/constants/slot'|from '../lib/slot'|g" \
    -e "s|from '@/components/icon'|from 'lucide-react'|g" \
    -e "s|from '@/components/direction-provider'|from '../lib/direction'|g" \
    -e "s|from '@/hooks/use-as-ref'|from '../lib/use-as-ref'|g" \
    -e "s|from '@/hooks/use-modal-context'|from '../lib/modal-context'|g" \
    -e "s|from '@/utils'|from '../lib/cn'|g" \
    "$f"
done

# text.tsx uses @/utils -> ../lib/cn (handled above)

# dialog: North Icon component -> Lucide X for portable kit
sed "${SED_INPLACE[@]}" \
  -e 's|import { Icon } from '\''lucide-react'\'';|import { X } from '\''lucide-react'\'';|g' \
  -e 's|<Icon name="close" />|<X className="size-4" aria-hidden />|g' \
  "${KIT}/components/dialog.tsx"

echo ""
echo "Synced:"
echo "  kit/styles/theme.css"
echo "  kit/styles/tailwind-tokens.css"
echo "  kit/shadcn/components.json"
echo "  kit/lib/cn.ts"
echo "  kit/components/{button,card,input,label,badge,separator,dialog,tooltip,text}.tsx"
echo ""
echo "Next: review kit/components/dialog.tsx (Icon -> X) and kit/components/tooltip.tsx."
echo "Hand-maintained: kit/lib/slot.ts, global-snippet.css, fonts/FONTS.md, docs/*.md"
