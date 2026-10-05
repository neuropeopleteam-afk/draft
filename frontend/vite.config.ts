import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// В разработке /api проксируется на локальный backend (uvicorn :8000).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": process.env.VITE_API_PROXY ?? "http://localhost:8000" },
  },
});
