import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The app calls the API under /api. In dev, Vite forwards /api/* to the FastAPI backend
// (no CORS needed); in Docker, nginx does the same (see nginx.conf).
const backend = process.env.VITE_BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") },
    },
  },
});
