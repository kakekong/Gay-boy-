import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";
import "./store/theme";  // applies the persisted dark/light class at boot

// After a deploy, an open tab may lazy-load a chunk that no longer exists
// (the server answers with HTML → "not a valid JavaScript MIME type").
// Vite surfaces this as vite:preloadError — reload once to pick up the new
// build instead of crashing into the error card. A timestamp guard stops
// reload loops if reloading doesn't cure it.
window.addEventListener("vite:preloadError", (e) => {
  const last = Number(sessionStorage.getItem("stale-build-reload") || 0);
  if (Date.now() - last > 60_000) {
    e.preventDefault();
    sessionStorage.setItem("stale-build-reload", String(Date.now()));
    window.location.reload();
  }
});

const qc = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
