"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode; fallback: ReactNode; onError?: (err: Error) => void };

type State = { err: Error | null };

export class GraphCanvasErrorBoundary extends Component<Props, State> {
  state: State = { err: null };

  static getDerivedStateFromError(err: Error): State {
    return { err: err };
  }

  componentDidCatch(err: Error, info: ErrorInfo): void {
    console.error("Graph canvas error", err, info.componentStack);
    this.props.onError?.(err);
  }

  render(): ReactNode {
    if (this.state.err) return this.props.fallback;
    return this.props.children;
  }
}
