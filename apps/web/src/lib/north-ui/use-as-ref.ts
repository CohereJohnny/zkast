import { useRef } from 'react';

import { useIsomorphicLayoutEffect } from './use-isomorphic-layout-effect';

export function useAsRef<T>(data: T) {
  const ref = useRef<T>(data);

  useIsomorphicLayoutEffect(() => {
    ref.current = data;
  });

  return ref;
}
