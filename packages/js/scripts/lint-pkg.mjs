/**
 * Lint the *published shape* of the package: publint over package.json, then
 * arethetypeswrong over a real tarball.
 *
 * Two npm behaviours make this fiddlier than it looks, and both only bite
 * inside `prepublishOnly` -- which is exactly when this check matters most.
 *
 * 1. attw's `--pack .` mode shells out to `npm pack` itself, which fails when
 *    already inside an npm lifecycle hook. So we pack explicitly and hand attw
 *    the file. Packing to a temp directory also avoids leaving a stray .tgz in
 *    the package root for `files`/.npmignore to trip over later.
 * 2. npm passes its own flags to child npm invocations through the environment,
 *    so under `npm publish --dry-run` the nested `npm pack` inherits
 *    `npm_config_dry_run=true`: it prints the filename it *would* write and
 *    writes nothing. attw then reports a missing tarball, which reads like a
 *    packaging defect and is not one. Clearing the variable for the child is
 *    the fix -- a dry-run publish still must really pack in order to check it.
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const pkgDir = fileURLToPath(new URL("..", import.meta.url));
const run = (cmd, args, env) =>
  execFileSync(cmd, args, {
    cwd: pkgDir,
    stdio: "inherit",
    shell: process.platform === "win32",
    env: { ...process.env, ...env },
  });

run("npx", ["publint"]);

const out = mkdtempSync(join(tmpdir(), "geodata-attw-"));
try {
  run("npm", ["pack", "--silent", "--pack-destination", out], { npm_config_dry_run: "" });
  const tarball = readdirSync(out).find((f) => f.endsWith(".tgz"));
  if (!tarball) throw new Error(`npm pack produced no tarball in ${out}`);
  run("npx", ["attw", join(out, tarball), "--format", "table"]);
} finally {
  rmSync(out, { recursive: true, force: true });
}
