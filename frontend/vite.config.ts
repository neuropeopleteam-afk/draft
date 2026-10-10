import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { brotliCompressSync, constants as zlib, gzipSync } from "node:zlib";
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

// Я16: сжатие на сборке — рядом с файлом кладутся .gz (gzip -9) и .br (brotli), nginx отдаёт их как есть
// (gzip_static / brotli_static, frontend/nginx.conf, infra/nginx/BOOT_APPLY.md): ответ с Content-Length — оборванную
// передачу браузер распознаёт как ошибку загрузки, а не ждёт; сжатие сильнее, чем «на лету» (уровень 1), и без
// расхода процессора на каждый запрос. Сжимаются только файлы, для которых это даёт выигрыш (> 1 КБ и −5 % и больше).
// Большой wasm модели камеры (/vendor/) — только gzip и brotli среднего качества: качество 11 на 13 МБ — минуты.
const COMPRESSIBLE = /\.(js|mjs|css|html|svg|json|webmanifest|wasm|txt)$/;

function precompress(): Plugin {
  let outDir = "dist";
  const walk = (dir: string): string[] => readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
  return {
    name: "precompress",
    apply: "build",
    configResolved(c) { outDir = resolve(c.root, c.build.outDir); },
    // closeBundle — после writeBundle всех плагинов: sw.js уже с версией сборки
    closeBundle(error?: Error) {
      if (error || !existsSync(outDir)) return;  // сборка упала — не заслоняем её ошибку своей
      let n = 0;
      for (const file of walk(outDir)) {
        if (!COMPRESSIBLE.test(file)) continue;
        const raw = readFileSync(file);
        if (raw.length <= 1024) continue;
        const big = raw.length > 2 * 1024 * 1024;
        const gz = gzipSync(raw, { level: 9 });
        const br = brotliCompressSync(raw, {
          params: {
            [zlib.BROTLI_PARAM_QUALITY]: big ? 6 : 11,
            [zlib.BROTLI_PARAM_SIZE_HINT]: raw.length,
            [zlib.BROTLI_PARAM_MODE]: /\.(wasm)$/.test(file) ? zlib.BROTLI_MODE_GENERIC : zlib.BROTLI_MODE_TEXT,
          },
        });
        if (gz.length < raw.length * 0.95) { writeFileSync(`${file}.gz`, gz); n++; }
        if (br.length < raw.length * 0.95) { writeFileSync(`${file}.br`, br); n++; }
      }
      console.log(`precompress: ${n} файлов .gz/.br`);
    },
  };
}

// Я16: таблица стилей сборки — из <head> в <body> сразу после #root. В <head> она блокирует первую отрисовку: если
// файл завис (обрыв соединения), не видно ни «Загружаем…», ни сообщения сторожа — белый экран. Из <body> она не
// мешает отрисовать то, что выше (экран загрузки со своими встроенными стилями), а код приложения (type=module) всё равно
// выполняется только после загрузки стилей — без «голого» кадра.
function cssAfterSplash(): Plugin {
  return {
    name: "css-after-splash",
    apply: "build",
    transformIndexHtml: {
      order: "post",
      handler(html) {
        const re = /[ \t]*<link rel="stylesheet"[^>]*href="\/assets\/[^"]+\.css"[^>]*>\n?/g;
        const links = html.match(re) ?? [];
        const root = /<div id="root">[\s\S]*?<\/main><\/div>\n?/;
        if (!links.length || !root.test(html)) return html;
        return html.replace(re, "").replace(root, (m) => `${m}    ${links.map((l) => l.trim()).join("\n    ")}\n`);
      },
    },
  };
}

// Я16: стартовый JS — только общий код и главная; экраны ролей и тяжёлые экраны — ленивыми маршрутами (App.tsx),
// React и маршрутизатор — отдельным файлом vendor (меняется редко, остаётся в кэше браузера между выкладками).
const VENDOR = /[\\/]node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom|@remix-run[\\/]router)[\\/]/;

// В разработке /api проксируется на локальный backend (uvicorn :8000).
export default defineConfig({
  plugins: [react(), swBuildVersion(), cssAfterSplash(), precompress()],
  define: { __APP_BUILD__: JSON.stringify(BUILD_ID) },
  build: {
    // предупреждение о крупном файле — по стартовому бюджету, а не по умолчанию Vite (500 КБ)
    chunkSizeWarningLimit: 400,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (VENDOR.test(id)) return "vendor";
          return undefined;
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: { "/api": process.env.VITE_API_PROXY ?? "http://localhost:8000" },
  },
});
