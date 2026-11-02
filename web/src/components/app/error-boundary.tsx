import { Component, type ReactNode } from "react";

interface State {
  error: Error | null;
}

/** Catches render/runtime errors and shows them on screen instead of a blank page. */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: unknown) {
    console.error("Storeel UI crashed:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="mx-auto max-w-2xl p-6">
          <div className="rounded-2xl border border-danger/40 bg-danger/10 p-5">
            <h2 className="mb-2 text-lg font-semibold text-danger">Something went wrong</h2>
            <pre className="whitespace-pre-wrap break-words font-mono text-xs text-foreground">
              {this.state.error.message}
              {"\n\n"}
              {this.state.error.stack}
            </pre>
            <button
              onClick={() => this.setState({ error: null })}
              className="mt-4 rounded-lg border border-border-strong px-3 py-1.5 text-sm font-semibold"
            >
              Dismiss
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
