/**
 * Structural guarantees about the package, as opposed to its answers.
 *
 * The important one is reachability. The whole exports design rests on a claim
 * that cannot be checked by calling functions: *nothing reachable from the root
 * entry can pull in the 152,970-row cities table*. If that ever stops being
 * true, no test of behaviour fails -- a client bundle just silently grows by
 * 4.7 MB. So it is checked the only way it can be: by bundling each entry point
 * and inspecting the module graph esbuild actually produced.
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import * as esbuild from "esbuild";
import { describe, expect, it } from "vitest";

import { COUNTRY_CODES, COUNTS, COUNTS_BY_COUNTRY, DATASET_VERSION, VERSION } from "../src/index.js";
import { countries } from "../src/index.js";
import { CHUNKS } from "../src/generated/lazy.countries.js";
import { STATES } from "../src/generated/lazy.states.js";
import { CITIES } from "../src/generated/lazy.cities.js";

const PKG = dirname(dirname(fileURLToPath(import.meta.url)));
const REPO = join(PKG, "..", "..");

/**
 * The modules a bundle of `entry` pulls in, split by when they load.
 *
 * `eager` is what lands in the entry chunk -- the bytes a browser downloads
 * before anything runs. `lazy` is everything reached only through a dynamic
 * import, which a bundler emits as separate chunks fetched on demand.
 *
 * Code splitting is switched on deliberately. Without it esbuild inlines
 * dynamic imports into the entry, so every per-country chunk would appear
 * eager and the assertions below would be measuring the wrong thing -- the
 * opposite of what a real application bundler does.
 */
async function graphOf(entry: string): Promise<{ eager: string[]; lazy: string[] }> {
  const result = await esbuild.build({
    entryPoints: [join(PKG, "src", entry)],
    bundle: true,
    write: false,
    metafile: true,
    format: "esm",
    platform: "browser",
    target: "es2022",
    splitting: true,
    outdir: join(PKG, "node_modules", ".cache", "geodata-graph"),
    logLevel: "silent",
  });

  // esbuild reports inputs relative to the process cwd, which differs between
  // a local run and CI. Normalising on the last `src/` segment keeps these
  // assertions dependent on the module graph and nothing else -- otherwise a
  // path that never matches also never trips a "must not contain" filter, and
  // the test passes vacuously.
  const clean = (p: string) => {
    const normalized = p.replace(/\\/g, "/");
    const at = normalized.lastIndexOf("src/");
    return at === -1 ? normalized : normalized.slice(at + 4);
  };

  // Every split chunk carries an `entryPoint`, including the ones esbuild
  // created for dynamic imports, so its presence does not identify the real
  // entry. Match the path we asked for instead.
  const outputs = result.metafile.outputs;
  const eager: string[] = [];
  const lazy: string[] = [];
  for (const output of Object.values(outputs)) {
    const isEntry = typeof output.entryPoint === "string" && output.entryPoint.endsWith(entry);
    (isEntry ? eager : lazy).push(...Object.keys(output.inputs).map(clean));
  }
  return { eager, lazy };
}

describe("reachability", () => {
  it("the root entry cannot reach the cities table", async () => {
    const { eager } = await graphOf("index.ts");
    const cityModules = eager.filter((p) => p.startsWith("data/c/") || p.includes("cities.all"));
    expect(
      cityModules,
      "the root entry must stay client-safe; a static import of city data breaks that",
    ).toEqual([]);
  });

  it("the root entry cannot reach the full states table either", async () => {
    const { eager } = await graphOf("index.ts");
    expect(eager.filter((p) => p.includes("states.all"))).toEqual([]);
  });

  it("the root entry cannot reach the translation tables", async () => {
    const { eager } = await graphOf("index.ts");
    expect(eager.filter((p) => p.includes("translations."))).toEqual([]);
  });

  it("geodata-js/states cannot reach the cities table", async () => {
    // Not just eager: `geodata-js/states` must not reach city data at all, by
    // any route, or the "states are safe on a server, cities are the heavy one"
    // distinction stops being real.
    const { eager, lazy } = await graphOf("states.ts");
    const all = [...eager, ...lazy];
    expect(all.filter((p) => p.startsWith("data/c/") || p.includes("cities.all"))).toEqual([]);
  });

  it("a per-country chunk holds exactly one country's data", async () => {
    const { eager, lazy } = await graphOf("country/NG.ts");
    const perCountry = [...eager, ...lazy].filter((p) => /^data\/(c|s|co)\//.test(p));
    expect(perCountry.sort()).toEqual(["data/c/NG.js", "data/co/NG.js", "data/s/NG.js"]);
  });

  it("city data is reachable from geodata-js/lazy, but only lazily", async () => {
    // The mirror of the first assertion: proving cities are absent from the
    // eager chunk would be worthless if they were absent altogether, because
    // then `await citiesOf("NG")` could not work. They live behind the `lazy`
    // subpath, which is the module that opts into the emitted chunks.
    const { eager, lazy } = await graphOf("lazy.ts");
    expect(lazy.filter((p) => p.startsWith("data/c/")).length).toBe(250);
    expect(eager.filter((p) => p.startsWith("data/c/"))).toEqual([]);
  });

  it("the root entry reaches no city chunk at all, by any route", async () => {
    // This is the assertion the 46 MB regression turned on. Reachability --
    // not eagerness -- is what decides whether a bundler emits the chunks, so
    // `citiesOf` had to leave the root entry's graph entirely rather than
    // merely be tree-shakeable.
    const { eager, lazy } = await graphOf("index.ts");
    expect([...eager, ...lazy].filter((p) => p.startsWith("data/c/"))).toEqual([]);
  });

  it("the root entry still reaches every state chunk lazily", async () => {
    // The counterweight: `statesOf` has to stay lazy-but-reachable, and its
    // 250 chunks total ~2.6 MB rather than the cities' 46 MB.
    const { lazy } = await graphOf("index.ts");
    expect(lazy.filter((p) => p.startsWith("data/s/")).length).toBe(250);
  });

  it("a consumer that only uses statesOf gets no city chunks emitted", async () => {
    // The regression this guards is invisible to every behavioural test. A
    // bundler emits a chunk file for every `import()` it can see, used or not,
    // so when all three chunk maps shared one statically-imported module, a
    // Next.js client component building a state dropdown emitted 43 MB of city
    // chunks it would never fetch. First Load JS looked fine; the deployed
    // asset bundle did not.
    const result = await esbuild.build({
      stdin: {
        contents: `import { statesOf } from ${JSON.stringify(join(PKG, "src", "index.ts"))};
                   export const run = (iso2) => statesOf(iso2);`,
        resolveDir: PKG,
        loader: "ts",
      },
      bundle: true,
      write: false,
      metafile: true,
      format: "esm",
      platform: "browser",
      target: "es2022",
      splitting: true,
      treeShaking: true,
      outdir: join(PKG, "node_modules", ".cache", "geodata-graph-states"),
      logLevel: "silent",
    });
    const inputs = Object.values(result.metafile.outputs).flatMap((o) => Object.keys(o.inputs));
    const cityModules = inputs.filter((p) => p.replace(/\\/g, "/").includes("/data/c/"));
    expect(cityModules, "unused city chunks must not be emitted").toEqual([]);
    // The states chunks must still be there -- proving the assertion above is
    // not passing simply because nothing was emitted at all.
    expect(inputs.filter((p) => p.replace(/\\/g, "/").includes("/data/s/")).length).toBe(250);
  });

  it("geodata-js/normalize pulls in no data at all", async () => {
    const { eager, lazy } = await graphOf("normalize.ts");
    expect([...eager, ...lazy].filter((p) => p.startsWith("data/"))).toEqual([]);
  });
});

describe("the generated manifest matches the data", () => {
  it("lists exactly the countries in the table", () => {
    expect([...COUNTRY_CODES].sort()).toEqual(countries().map((c) => c.iso2).sort());
  });

  it("has one lazy chunk per country in all three maps", () => {
    // `chunkFor` throws a deliberately clear error when an entry is missing;
    // this is what keeps that branch unreachable. All three matter: `statesOf`
    // dispatches through STATES and `citiesOf` through CITIES, so a gap in
    // either would surface only for one unlucky country.
    const expected = [...COUNTRY_CODES].sort();
    expect(Object.keys(CHUNKS).sort()).toEqual(expected);
    expect(Object.keys(STATES).sort()).toEqual(expected);
    expect(Object.keys(CITIES).sort()).toEqual(expected);
  });

  it("agrees with data/RELEASE.json", () => {
    const release = JSON.parse(readFileSync(join(REPO, "data", "RELEASE.json"), "utf8"));
    expect(COUNTS).toEqual(release.counts);
    expect(DATASET_VERSION).toBe(release.version);
    expect(COUNTRY_CODES.length).toBe(release.counts.countries);
  });

  it("per-country counts sum to the totals", () => {
    const totals = Object.values(COUNTS_BY_COUNTRY).reduce(
      (acc, c) => ({ states: acc.states + c.states, cities: acc.cities + c.cities }),
      { states: 0, cities: 0 },
    );
    expect(totals.states).toBe(COUNTS.states);
    expect(totals.cities).toBe(COUNTS.cities);
  });
});

describe("versioning", () => {
  it("the package version matches package.json", () => {
    const pkg = JSON.parse(readFileSync(join(PKG, "package.json"), "utf8"));
    expect(VERSION).toBe(pkg.version);
  });

  it("keeps the code version and the dataset version distinct", () => {
    // They are allowed to differ -- a code-only fix bumps one and not the
    // other -- but the dataset version must stay the calendar string, not get
    // silently overwritten with a semver.
    expect(DATASET_VERSION).toMatch(/^\d{4}\.\d{2}$/);
    expect(VERSION).toMatch(/^\d+\.\d+\.\d+/);
  });
});

describe("the package manifest", () => {
  const pkg = JSON.parse(readFileSync(join(PKG, "package.json"), "utf8"));

  it("declares no runtime dependencies", () => {
    // A reference dataset that drags in a dependency tree is a liability; this
    // is a promise made in the README.
    expect(pkg.dependencies ?? {}).toEqual({});
  });

  it("marks itself side-effect free so bundlers can drop unused subpaths", () => {
    expect(pkg.sideEffects).toBe(false);
  });

  it("routes the cities subpath away from browser builds", () => {
    expect(pkg.exports["./cities"].browser).toBe("./dist/esm/cities.browser.js");
  });

  it("gives every subpath both types conditions", () => {
    for (const [name, entry] of Object.entries<any>(pkg.exports)) {
      if (typeof entry === "string") continue;
      expect(entry.import?.types, `${name} import.types`).toBeTruthy();
      expect(entry.require?.types, `${name} require.types`).toBeTruthy();
      // `.d.cts` for the require condition is what makes `require()` see CJS
      // types rather than ESM ones.
      expect(entry.require.types.endsWith(".d.cts"), `${name} require.types ext`).toBe(true);
    }
  });
});
