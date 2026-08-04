import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Vite + Vitest config for the PR Review Assistant SPA.
export default defineConfig({
  plugins: [react()],
  server: {
    // Dev-time proxy: all /api calls go to the FastAPI backend.
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    // Explicit default: built SPA lands in dist/.
    outDir: "dist",
  },
  test: {
    environment: "jsdom",
  },
});
