/// <reference types="vitest/config" />
import { cpSync, createReadStream, existsSync, statSync } from "node:fs";
import { join, normalize, sep } from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const PDFJS_ROOT = fileURLToPath(new URL("./node_modules/pdfjs-dist", import.meta.url));
// Runtime data PDF.js fetches on demand: CJK CMaps, standard fonts, JBIG2/JPX decoders, ICC profiles.
const PDFJS_ASSET_DIRS = ["cmaps", "standard_fonts", "wasm", "iccs"];

/** Serve PDF.js runtime assets under /pdfjs/ in dev and copy them into the build. */
function pdfjsAssets(): Plugin {
  let outDir = "dist";
  return {
    name: "pdfjs-assets",
    configResolved(config) {
      outDir = join(config.root, config.build.outDir);
    },
    configureServer(server) {
      server.middlewares.use("/pdfjs", (req, res, next) => {
        const rel = normalize(decodeURIComponent((req.url ?? "").split("?")[0])).replace(/^[/\\]+/, "");
        const file = join(PDFJS_ROOT, rel);
        const allowed = PDFJS_ASSET_DIRS.includes(rel.split(sep)[0]) && file.startsWith(PDFJS_ROOT + sep);
        if (!allowed || !existsSync(file) || !statSync(file).isFile()) return next();
        if (file.endsWith(".wasm")) res.setHeader("Content-Type", "application/wasm");
        createReadStream(file).pipe(res);
      });
    },
    closeBundle() {
      for (const dir of PDFJS_ASSET_DIRS) {
        cpSync(join(PDFJS_ROOT, dir), join(outDir, "pdfjs", dir), { recursive: true });
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), pdfjsAssets()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    // Start the backend with PDF_REDACT_TOKEN=dev; the UI uses that token in dev mode.
    proxy: { "/api": { target: "http://127.0.0.1:8765", changeOrigin: true } },
  },
  build: { chunkSizeWarningLimit: 1500 },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
