import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="flex flex-col items-center justify-center h-full gap-3 p-6">
          <p className="text-sm font-medium" style={{ color: "var(--color-error)" }}>
            Something went wrong
          </p>
          <p className="text-xs max-w-md text-center" style={{ color: "var(--color-text-muted)" }}>
            {this.state.error?.message}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="px-3 py-1.5 rounded-lg text-xs font-medium"
            style={{ backgroundColor: "var(--color-surface-hover)", color: "var(--color-accent)" }}
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
