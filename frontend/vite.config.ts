import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

// Версия сборки: одна и та же в коде страницы (__APP_BUILD__) и в dist/sw.js (VERSION).
// Новый sw.js на каждую сборку — браузер ставит новый service worker, старые кэши удаляются (без пустой страницы).
const BUILD_ID = process.env.VITE_BUILD_ID || new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 14);

function swBuildVersion(): Plugin {
  let outDir = "dist";
  return {
    name: "sw-build-version",
    apply: "build",
    configResolved(c) { outDir = resolve(c.root, c.build.outDir); },
    writeBundle() {
      const file = resolve(outDir, "sw.js");
      const src = readFileSync(file, "utf8");
      if (!src.includes("__BUILD_ID__")) throw new Error("sw.js: нет метки __BUILD_ID__");
      writeFileSync(file, src.split("__BUILD_ID__").join(BUILD_ID));
    },
  };
}

// В разработке /api проксируется на локальный backend (uvicorn :8000).
export default defineConfig({
  plugins: [react(), swBuildVersion()],
  define: { __APP_BUILD__: JSON.stringify(BUILD_ID) },
  server: {
    port: 5173,
    proxy: { "/api": process.env.VITE_API_PROXY ?? "http://localhost:8000" },
  },
});
