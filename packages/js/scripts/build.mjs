/**
 * Build `dist/` from `src/`.
 *
 * Layout, and why:
 *
 *     dist/esm/**.js      + package.json {"type":"module"}
 *     dist/cjs/**.js      + package.json {"type":"commonjs"}
 *     dist/types/**.d.ts
 *
 * Two parallel trees with the *same* `.js` filenames in both. That is the
 * detail that makes this work without a bundler: every import specifier in the
 * source says `"./data/countries.js"`, and that resolves correctly inside
 * either tree, so nothing ever has to rewrite an extension. The usual
 * alternative -- one tree emitting `.mjs` and `.cjs` -- means every relative
 * specifier has to be rewritten per format, which is where dual-format
 * packages typically break.
 *
 * The build does not bundle. esbuild runs in transform mode, one output file
 * per input file, so the module graph survives into `dist/` intact. That is
 * what preserves the guarantee the exports map depends on: the cities table is
 * reachable only from `cities.js` and the per-country chunks, so no consumer
 * bundling the root entry can pull it in. Bundling here would inline the
 * shared data modules into every entry point that touches them and duplicate
 * 41 MB several times over.
 */

import { execFileSync } from "node:child_process";
import {
  cpSync,
  renameSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import * as esbuild from "esbuild";

const HERE = dirname(fileURLToPath(import.meta.url));
const PKG = dirname(HERE);
const SRC = join(PKG, "src");
const DIST = join(PKG, "dist");

/** Every file under `dir` matching `test`, recursively. */
function walk(dir, test, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) walk(full, test, out);
    else if (test(entry.name)) out.push(full);
  }
  return out;
}

function humanBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function treeSize(dir) {
  return walk(dir, () => true).reduce((sum, f) => sum + statSync(f).size, 0);
}

const t0 = Date.now();
// Rename-then-delete rather than a plain recursive remove.
//
// On macOS a concurrent reader -- `npm pack`, an editor indexer, a Next.js
// build resolving the linked package -- can hold a directory open just long
// enough for rmdir to fail ENOTEMPTY, which leaves `dist/` half-deleted and
// makes whatever was reading it fail in a way that looks like a package bug.
// Renaming is atomic, so the build gets a clean slate immediately and the old
// tree is disposed of afterwards, retrying if it is still busy.
const stale = `${DIST}.stale-${process.pid}-${Date.now()}`;
try {
  renameSync(DIST, stale);
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}
rmSync(stale, { recursive: true, force: true, maxRetries: 20, retryDelay: 100 });
// Any tree left behind by an earlier interrupted build.
for (const entry of readdirSync(PKG)) {
  if (entry.startsWith("dist.stale-")) {
    rmSync(join(PKG, entry), { recursive: true, force: true, maxRetries: 5 });
  }
}

// `.d.ts` files are inputs, not sources to transform: the generated data
// modules are plain `.js` with a hand-written sibling declaration.
const entryPoints = walk(SRC, (name) => {
  if (name.endsWith(".d.ts")) return false;
  return name.endsWith(".ts") || name.endsWith(".js");
});

if (entryPoints.length === 0) {
  throw new Error(
    "src/ has no entry points. Run `python3 ../../scripts/build_js.py` first -- the data\n" +
      "modules and generated types are not committed, they are produced from data/canonical.",
  );
}

console.log(`geodata-js build: ${entryPoints.length} modules`);

for (const [format, outdir] of [
  ["esm", join(DIST, "esm")],
  ["cjs", join(DIST, "cjs")],
]) {
  await esbuild.build({
    entryPoints,
    outdir,
    outbase: SRC,
    format,
    // Transform mode. See the header: bundling would inline and duplicate the
    // data modules and break the reachability guarantee the exports map rests
    // on.
    bundle: false,
    platform: "neutral",
    target: ["node18", "es2022"],
    sourcemap: false,
    // The data modules are one enormous string literal each; minifying only
    // whitespace outside them saves nothing and costs build time. Identifier
    // mangling would also make a stack trace from a consumer useless.
    minify: false,
    logLevel: "warning",
  });

  writeFileSync(
    join(outdir, "package.json"),
    // Pins the module system for this subtree regardless of the root
    // package.json, which is what lets one `.js` extension mean ESM under
    // dist/esm and CommonJS under dist/cjs.
    //
    // `sideEffects` has to be repeated here. A bundler looks up the *nearest*
    // package.json to decide whether a module may be dropped, and for anything
    // under dist/ that is this file, not the published one -- so omitting it
    // silently disables tree-shaking for the whole package. The cost is not
    // subtle: with it missing, an app that imports only `getCountry` still
    // emits all 250 per-country lazy chunks, 46 MB of build output it can
    // never load.
    `${JSON.stringify(
      { type: format === "esm" ? "module" : "commonjs", sideEffects: false },
      null,
      2,
    )}\n`,
  );
  console.log(`  dist/${format}  ${humanBytes(treeSize(outdir))}`);
}

// Declarations. tsc only sees `.ts`; the generated data modules' declarations
// are written by build_js.py and copied in below.
execFileSync("npx", ["tsc", "--project", join(PKG, "tsconfig.json")], {
  cwd: PKG,
  stdio: "inherit",
});

let copied = 0;
for (const file of walk(SRC, (name) => name.endsWith(".d.ts"))) {
  const target = join(DIST, "types", relative(SRC, file));
  mkdirSync(dirname(target), { recursive: true });
  cpSync(file, target);
  copied++;
}

// A second declaration tree with `.d.cts` extensions, for the `require`
// condition.
//
// TypeScript decides whether a declaration describes ESM or CommonJS from the
// file extension, not from the code. One `.d.ts` tree serving both conditions
// means `require("geodata-js")` gets types that claim to be ESM, and the import
// only type-checks when dynamically imported -- the failure publint reports.
//
// Relative specifiers are rewritten `.js` -> `.cjs` on the way in. TypeScript
// substitutes extensions by pair -- `./x.js` looks for `./x.d.ts`, and only
// `./x.cjs` looks for `./x.d.cts` -- so a `.d.cts` file importing `"./x.js"`
// searches for a `.d.ts` that does not exist in this tree. That is an internal
// resolution failure attw catches and a consumer sees as "has no exported
// member".
const TYPES = join(DIST, "types");
const TYPES_CJS = join(DIST, "types-cjs");
const RELATIVE_JS = /(["'])(\.{1,2}\/[^"']*)\.js\1/g;
for (const file of walk(TYPES, (name) => name.endsWith(".d.ts"))) {
  const target = join(TYPES_CJS, relative(TYPES, file)).replace(/\.d\.ts$/, ".d.cts");
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, readFileSync(file, "utf8").replace(RELATIVE_JS, "$1$2.cjs$1"));
}
console.log(`  dist/types ${humanBytes(treeSize(join(DIST, "types")))} (${copied} generated .d.ts copied)`);
console.log(`  dist/types-cjs ${humanBytes(treeSize(TYPES_CJS))}`);
console.log(`  total      ${humanBytes(treeSize(DIST))} in ${((Date.now() - t0) / 1000).toFixed(1)}s`);
