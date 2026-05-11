"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };

type State = { error: Error | null };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("UI error boundary", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div
          role="alert"
          className="rounded-lg border border-border-strong bg-surface p-6 text-body text-primary"
        >
          <p className="font-semibold text-title-3">Something went wrong</p>
          <p className="mt-2 text-secondary">{this.state.error.message}</p>
          <button
            type="button"
            className="mt-4 cursor-pointer rounded-md bg-accent-primary px-4 py-2 text-body font-medium text-canvas transition hover:bg-accent-primary-hover"
            onClick={() => this.setState({ error: null })}
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
