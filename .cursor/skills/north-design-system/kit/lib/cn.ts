// Vendored from North @cohere-ai/ui — sync via scripts/sync-from-north.sh

import { type ClassValue, clsx } from 'clsx';
import { extendTailwindMerge } from 'tailwind-merge';

const customTwMerge = extendTailwindMerge({
  extend: {
    // @see: https://github.com/dcastil/tailwind-merge/blob/v2.5.2/docs/configuration.md#class-groups
    classGroups: {
      'font-size': [
        {
          text: [
            'caption',
            'label-sm',
            'label',
            'overline',
            'p-xs',
            'p-sm',
            'p',
            'p-lg',
            'code',
            'code-sm',
            'logo',
            'h5',
            'h5-m',
            'h4',
            'h4-m',
            'h3',
            'h3-m',
            'h2',
            'h2-m',
            'h1',
            'h1-m'
          ]
        }
      ],
      'min-w': [
        {
          'min-w': ['menu', 'left-panel-collapsed', 'left-panel-expanded']
        }
      ],
      'max-w': [
        {
          'max-w': [
            'message',
            'left-panel-collapsed',
            'left-panel-expanded',
            'share_content',
            'modal'
          ]
        }
      ],
      // Register every custom z-index utility name (any class derived from a
      // `--z-index-*` token) here so `cn(...)` correctly deduplicates them.
      // When a base `className` and an override are merged, only the LATER
      // class survives — without this group, both would remain and the higher
      // numeric z-index would win regardless of caller intent.
      // When adding a new `--z-index-foo` token, also add `'foo'` here.
      z: [
        {
          z: [
            'navigation',
            'dropdown',
            'tag-suggestions',
            'drag-drop-input-overlay',
            'read-only-conversation-footer',
            'menu',
            'guide-tooltip',
            'tooltip',
            'backdrop',
            'modal',
            'nested-modal',
            'popover',
            'composer',
            'side-nav-panel',
            'side-nav-panel-backdrop',
            'builder-canvas-overlay'
          ]
        }
      ],
      w: [
        {
          w: ['modal', 'ep-icon-sm', 'ep-icon-md', 'ep-icon-lg', 'ep-icon-xl']
        }
      ],
      h: [{ h: ['ep-icon-sm', 'ep-icon-md', 'ep-icon-lg', 'ep-icon-xl'] }],
      'max-h': [{ 'max-h': ['cell-xs', 'cell-sm', 'cell-md', 'cell-lg', 'cell-xl', 'modal'] }],
      'min-h': [{ 'min-h': ['cell-xs', 'cell-sm', 'cell-md', 'cell-lg', 'cell-xl'] }],
      shadow: [
        {
          shadow: ['menu', 'top']
        }
      ]
    }
  }
});

/**
 * Combines classnames with tailwind-merge
 */
export function cn(...inputs: ClassValue[]) {
  return customTwMerge(clsx(inputs));
}
