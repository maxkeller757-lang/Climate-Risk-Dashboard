#!/usr/bin/env node
// Copies the pipeline's data/layers/*.geojson into frontend/public/layers/,
// which Vite serves at the site root (dev) and copies verbatim into the
// build output (prod) -- so the exact same static-file code path (see
// src/api.ts::layerGeoJsonUrl) works locally and on Vercel, rather than
// dev and prod fetching layer data two different ways.
//
// Deliberately copies the *plain* .geojson, not the pipeline's pre-gzipped
// .geojson.gz sibling: a static host's own transport compression (Vercel's
// CDN does this automatically) is the simpler thing to rely on here than
// hand-rolling a Content-Encoding header across two different static
// servers (Vite's dev server and Vercel's), and localhost has no bandwidth
// ceiling for this to matter locally anyway.
//
// Run via `npm run predev` / `npm run prebuild` (wired into package.json),
// not directly -- see there for when this fires.
import { existsSync, mkdirSync, readdirSync, copyFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC_DIR = join(__dirname, "..", "..", "data", "layers");
const DEST_DIR = join(__dirname, "..", "public", "layers");

if (!existsSync(SRC_DIR)) {
  console.warn(
    `copy-layers: ${SRC_DIR} doesn't exist -- run the pipeline first ` +
      "(pixi run python pipeline/refresh_all.py). Skipping for now; the " +
      "map will show \"hasn't been generated yet\" for every layer until it does.",
  );
  process.exit(0);
}

mkdirSync(DEST_DIR, { recursive: true });

const files = readdirSync(SRC_DIR).filter((f) => f.endsWith(".geojson"));
if (files.length === 0) {
  console.warn(`copy-layers: no .geojson files found in ${SRC_DIR}`);
  process.exit(0);
}

for (const file of files) {
  copyFileSync(join(SRC_DIR, file), join(DEST_DIR, file));
}
console.log(`copy-layers: copied ${files.length} layer file(s) to public/layers/`);
