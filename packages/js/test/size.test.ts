/**
 * The size budget, and -- more important than any number here -- the structural
 * guarantee that nothing reachable from the root entry pulls in the 4.7 MB
 * cities table.
 *
 * Sizes are measured over the *static* import closure of the built ESM output,
 * because that is what a bundler must include. Dynamic `import()` is
 * deliberately not followed: it is exactly the mechanism the root entry uses to
 * keep per-country data out of the initial chunk, so counting it would measure
 * the opposite of what the design intends.
 */

import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";

const DIST = fileURLToPath(new URL("../dist/esm", import.meta.url));
const STATIC_IMPORT = /(?:^|[\s;}])(?:import|export)[\s\S]*?from\s*["']([^"']+)["']/g;

function closure(entry: string): string[] {
  const seen = new Set<string>();
  const stack = [resolve(DIST, entry)];
  while (stack.length) {
    const file = stack.pop()!;
    if (seen.has(file) || !existsSync(file)) continue;
    seen.add(file);
    for (const [, spec] of readFileSync(file, "utf8").matchAll(STATIC_IMPORT)) {
      if (spec.startsWith(".")) stack.push(resolve(dirname(file), spec));
    }
  }
  return [...seen].sort();
}

function kbGz(files: string[]): number {
  const raw = files.map((f) => readFileSync(f, "utf8")).join("");
  return gzipSync(Buffer.from(raw), { level: 9 }).length / 1024;
}

/**
 * Ceilings, not measurements: each is roughly 10% above what the build
 * currently produces. A breach means the data grew a table, or an entry point
 * grew an import it should not have -- both worth a human look before publish.
 */
const BUDGET_KB_GZ: Record<string, number> = {
  "index.js": 60,
  // Code only -- the city chunks it reaches are all dynamic.
  "lazy.js": 60,
  "states.js": 400,
  "translations.js": 780,
  "normalize.js": 5,
  "cities.js": 5200,
  "country/NG.js": 25,
  "country/US.js": 550,
};

describe("bundle budget", () => {
  it.each(Object.entries(BUDGET_KB_GZ))("%s stays under %d KB gz", (entry, ceiling) => {
    expect(kbGz(closure(entry))).toBeLessThanOrEqual(ceiling);
  });
});

describe("the cities table is unreachable from the client-safe entries", () => {
  const forbidden = ["data/cities.all.js", "data/states.all.js"];

  it.each(["index.js", "normalize.js"])("%s pulls in neither whole table", (entry) => {
    const files = closure(entry).map((f) => f.slice(DIST.length + 1));
    for (const table of forbidden) expect(files).not.toContain(table);
  });

  it("index.js reaches no per-country chunk statically", () => {
    // Every chunk must arrive through `import()` in generated/lazy.js. If one
    // leaked into the static graph, a bundler would inline that country.
    const files = closure("index.js").map((f) => f.slice(DIST.length + 1));
    expect(files.filter((f) => f.startsWith("data/c/") || f.startsWith("country/"))).toEqual([]);
  });

  it("states.js does reach the states table, as its contract promises", () => {
    const files = closure("states.js").map((f) => f.slice(DIST.length + 1));
    expect(files).toContain("data/states.all.js");
    expect(files).not.toContain("data/cities.all.js");
  });
});
