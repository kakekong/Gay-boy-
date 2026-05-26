import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Inject a build timestamp so we can see at a glance whether a deployed
// device is running an old cached bundle.
const BUILD_STAMP = new Date()
  .toISOString()
  .replace("T", " ")
  .slice(0, 16);

export default defineConfig({
  define: {
    __BUILD_STAMP__: JSON.stringify(BUILD_STAMP),
  },
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_URL || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
