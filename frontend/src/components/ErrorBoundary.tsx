import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertCircle, RefreshCw } from "lucide-react";

interface Props {
  children: ReactNode;
  /** Optional reset key — change it to force the boundary to re-render its children. */
  resetKey?: unknown;
}
interface State {
  error: Error | null;
}

// Match only genuine stale-build / chunk-load signatures. Deliberately does
// NOT include bare "import" or "failed to fetch" — those match unrelated
// errors ("important", ordinary network blips) and would reload spuriously.
const STALE_BUILD_RE =
  /dynamically imported module|valid JavaScript MIME type|importing a module script failed|ChunkLoadError|Loading chunk [\w-]+ failed/i;

function autoReloadForStaleBuild(): boolean {
  // One automatic reload per minute: enough to silently recover from a
  // fresh deploy, without loops when the failure is something else.
  const last = Number(sessionStorage.getItem("stale-build-reload") || 0);
  if (Date.now() - last > 60_000) {
    sessionStorage.setItem("stale-build-reload", String(Date.now()));
    window.location.reload();
    return true;
  }
  return false;
}

/**
 * Catches both render errors and lazy-chunk-load failures. Without this,
 * a network blip during a React.lazy fetch leaves you with a blank page
 * until you hard-refresh.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidUpdate(prev: Props) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error("[ErrorBoundary]", error, info.componentStack);
    if (STALE_BUILD_RE.test(error.message)) autoReloadForStaleBuild();
  }

  render() {
    if (!this.state.error) return this.props.children;
    const isChunk = STALE_BUILD_RE.test(this.state.error.message);
    // A reload is already in flight — show a quiet updating note, not an
    // alarming error card, for the split second before the page refreshes.
    const reloadedAt = Number(sessionStorage.getItem("stale-build-reload") || 0);
    if (isChunk && Date.now() - reloadedAt < 5_000) {
      return (
        <div className="min-h-[40vh] grid place-items-center p-6">
          <div className="flex items-center gap-2 text-sm text-ink-500">
            <RefreshCw size={14} className="animate-spin" /> Updating to the latest version…
          </div>
        </div>
      );
    }
    return (
      <div className="min-h-[40vh] grid place-items-center p-6">
        <div className="card max-w-md p-6 text-center space-y-3">
          <div className="mx-auto h-11 w-11 rounded-full bg-amber-100 text-amber-700 grid place-items-center">
            <AlertCircle size={20} />
          </div>
          <div className="font-semibold">
            {isChunk ? "Couldn't load this page" : "Something went wrong"}
          </div>
          <p className="text-sm text-ink-600">
            {isChunk
              ? "The app couldn't fetch one of its files — your connection blinked, or a fresh deploy hadn't finished propagating yet."
              : this.state.error.message}
          </p>
          <div className="flex gap-2 justify-center pt-1">
            <button
              className="btn-primary"
              onClick={() => window.location.reload()}
            >
              <RefreshCw size={14} /> Refresh page
            </button>
            <button
              className="btn-ghost"
              onClick={() => this.setState({ error: null })}
            >
              Try again
            </button>
          </div>
        </div>
      </div>
    );
  }
}
