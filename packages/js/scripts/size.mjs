/**
 * Measure what each subpath actually costs a consumer, and fail if a budget is
 * exceeded.
 *
 * The number that matters is not the file on disk but the bytes a browser
 * downloads *before anything runs*. So each entry is bundled with code
 * splitting on -- exactly as an application bundler would -- and only the entry
 * chunk is measured. Modules reached solely through a dynamic import land in
 * separate chunks and are reported separately, because they are a separate
 * download that most users never make.
 *
 * This is also what turns the exports map's central claim into a fact rather
 * than an intention: a root entry that gzips to 53 KB cannot be concealing the
 * 4.7 MB cities table.
 *
 * Run: `node scripts/size.mjs [--json]`
 */

import { rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import * as esbuild from "esbuild";

const PKG = dirname(dirname(fileURLToPath(import.meta.url)));
const ESM = join(PKG, "dist", "esm");
const SCRATCH = join(PKG, "node_modules", ".cache", "geodata-size");

/**
 * Budgets in gzipped bytes, for the eager entry chunk only.
 *
 * The root entry's budget is the load-bearing one: it is what a client
 * component pays. The rest exist to catch a data-shape change that
 * unexpectedly doubles a table.
 */
const BUDGETS = [
  { name: ".", file: "index.js", limit: 60 * 1024 },
  { name: "./normalize", file: "normalize.js", limit: 8 * 1024 },
  { name: "./states", file: "states.js", limit: 400 * 1024 },
  // 704 KB measured: the two translation tables are ~667 KB of it, plus the
  // ISO 639 table, which this subpath needs to resolve a locale tag to a
  // language before it can fall back from `pt-BR` to `pt`.
  { name: "./translations", file: "translations.js", limit: 760 * 1024 },
  { name: "./country/NG", file: "country/NG.js", limit: 40 * 1024 },
  { name: "./country/US", file: "country/US.js", limit: 550 * 1024 },
  { name: "./cities", file: "cities.js", limit: 5 * 1024 * 1024 },
];

function human(n) {
  return n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1024 / 1024).toFixed(2)} MB`;
}

/** Bundle one entry and split its output into eager and lazily-loaded bytes. */
async function measure(file) {
  const result = await esbuild.build({
    entryPoints: [join(ESM, file)],
    bundle: true,
    write: false,
    metafile: true,
    format: "esm",
    platform: "browser",
    target: "es2022",
    minify: true,
    // Without this, esbuild inlines dynamic imports into the entry and every
    // per-country chunk counts against the root entry's budget -- the opposite
    // of what a real bundler does.
    splitting: true,
    outdir: SCRATCH,
    logLevel: "silent",
  });

  let eagerRaw = 0;
  let eagerGz = 0;
  let lazyRaw = 0;
  let lazyChunks = 0;

  for (const out of result.outputFiles) {
    const meta = result.metafile.outputs[Object.keys(result.metafile.outputs).find((k) => out.path.endsWith(k.split("/").pop()))] ?? {};
    // Every split chunk carries an `entryPoint`, including ones esbuild made
    // for dynamic imports, so match the file we asked for.
    const isEntry = typeof meta.entryPoint === "string" && meta.entryPoint.endsWith(file);
    if (isEntry) {
      eagerRaw += out.contents.length;
      eagerGz += gzipSync(out.contents, { level: 9 }).length;
    } else {
      lazyRaw += out.contents.length;
      lazyChunks++;
    }
  }
  return { eagerRaw, eagerGz, lazyRaw, lazyChunks };
}

const results = [];
for (const budget of BUDGETS) {
  const m = await measure(budget.file);
  results.push({ ...budget, ...m, ok: m.eagerGz <= budget.limit });
}
rmSync(SCRATCH, { recursive: true, force: true, maxRetries: 5 });

if (process.argv.includes("--json")) {
  console.log(JSON.stringify(results, null, 2));
} else {
  console.log("subpath             eager min    eager gz     budget          lazy");
  console.log("-".repeat(74));
  for (const r of results) {
    const lazy = r.lazyChunks ? `${human(r.lazyRaw)} in ${r.lazyChunks} chunks` : "-";
    console.log(
      `${r.name.padEnd(18)} ${human(r.eagerRaw).padStart(10)}  ${human(r.eagerGz).padStart(10)}  ` +
        `${human(r.limit).padStart(9)}  ${(r.ok ? "ok" : "OVER").padEnd(5)} ${lazy}`,
    );
  }
}

const over = results.filter((r) => !r.ok);
if (over.length) {
  console.error(
    `\n${over.length} subpath(s) over budget:\n` +
      over.map((r) => `  ${r.name}: ${human(r.eagerGz)} > ${human(r.limit)}`).join("\n"),
  );
  process.exit(1);
}
