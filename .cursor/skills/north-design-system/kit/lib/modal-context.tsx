'use client';

import React from 'react';

export const ModalContext = React.createContext(false);

export function useModalContext() {
  return React.useContext(ModalContext);
}
