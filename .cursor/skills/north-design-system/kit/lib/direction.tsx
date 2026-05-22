'use client';

import { Direction as DirectionPrimitive } from 'radix-ui';
import type React from 'react';

type DirectionProviderProps = React.ComponentProps<typeof DirectionPrimitive.Provider>;

export function DirectionProvider({ dir, ...props }: DirectionProviderProps) {
  return <DirectionPrimitive.Provider dir={dir} {...props} />;
}

export function useDirection(
  props?: Parameters<typeof DirectionPrimitive.useDirection>[0]
) {
  return DirectionPrimitive.useDirection(props);
}
