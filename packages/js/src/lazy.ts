/**
 * Per-country city loading for the browser -- `geodata-js/lazy`.
 *
 * ## Why this is not in the root entry
 *
 * A bundler emits a chunk file for every `import()` it can see in the module
 * graph. It does this during scanning, before it knows whether the surrounding
 * code is reachable, so tree-shaking an unused `citiesOf` does *not* remove the
 * 250 chunk files its dynamic imports produced. Measured on the Next.js example
 * in this repo: a client component that used nothing but `statesOf` still
 * emitted 48 MB of city chunks into `.next/static`. First Load JS was unchanged
 * at 159 KB -- no user ever downloaded them -- but every deploy carried them,
 * and both webpack and esbuild behave this way.
 *
 * Splitting the chunk maps into separate modules did not fix it, because the
 * import sites are still reachable. The only thing that does is moving them out
 * of the root entry's graph entirely. So the cost is opt-in: importing this
 * module is the point at which you accept 40 MB of emitted city chunks, and a
 * consumer building a country/subdivision picker -- the common case -- never
 * pays it.
 *
 * ## What to use instead
 *
 * - Subdivisions: `statesOf` from the root entry is already lazy and costs
 *   2.6 MB of emitted chunks in total, 10 KB fetched per country.
 * - Cities on a server: `geodata-js/cities`, synchronous, no chunking.
 * - Cities in a browser, without the chunks: a route handler from
 *   `createGeoHandler()` in `geodata-js/next`, queried over the network. This
 *   is the right answer for most applications and what the example uses.
 * - Cities in a browser, offline or for one known country: this module, or the
 *   static `geodata-js/country/NG` subpath.
 *
 * ```ts
 * import { citiesOf, searchCities } from "geodata-js/lazy";
 *
 * await citiesOf("NG", { state: "NG-LA" });        // 17 KB fetched
 * await searchCities("lag", { country: "NG" });
 * ```
 */

import type { City, State } from "./generated/types.js";
import type { CityChunk, CountryChunk, StateChunk } from "./generated/lazy.js";
import { STATES } from "./generated/lazy.states.js";
import { resolveCountry, type CountryRef } from "./internal/countries.js";
import { chunkFor } from "./internal/chunks.js";
import { citiesInCountry, citiesInState, searchIn } from "./internal/cityOps.js";
import { lookupState, type StateRef } from "./internal/stateOps.js";

export type { City, CityChunk, CountryChunk, CountryRef, StateRef };

/**
 * Load one country's chunk: its row, its subdivisions and its cities.
 *
 * Prefer `statesOf` / `citiesOf`, which load only the table they need. This
 * loads all three, so for the United States it costs 481 KB gzipped where
 * `statesOf("US")` costs 10 KB. Use it when you genuinely want everything
 * about one country -- an offline form, a prefetch on country selection.
 *
 * ```ts
 * const { country, states, cities } = await loadCountry("NG");
 * ```
 */
export async function loadCountry(key: CountryRef): Promise<CountryChunk> {
  const c = resolveCountry(key);
  const { CHUNKS } = await import("./generated/lazy.countries.js");
  return chunkFor<CountryChunk>(CHUNKS, c.iso2, "country");
}

/**
 * Load one country's cities.
 *
 * The CITIES map is reached through a dynamic import rather than a static one,
 * and that is load-bearing rather than stylistic. A bundler emits a chunk file
 * for every `import()` it can see in the module graph, whether or not the code
 * around it is ever called. When all three chunk maps lived in one statically
 * imported module, a Next.js client component that only built a *state*
 * dropdown still emitted 43 MB of city chunks it would never fetch. Keeping the
 * map behind this boundary lets `sideEffects: false` tree-shaking drop it, and
 * its 250 chunks, from any build that never calls a cities function.
 */
async function loadCities(iso2: string): Promise<City[]> {
  const { CITIES } = await import("./generated/lazy.cities.js");
  const { cities } = await chunkFor<CityChunk>(CITIES, iso2, "cities");
  return cities;
}

/**
 * Cities of one country, or of one subdivision within it, loaded on demand.
 *
 * ```ts
 * await citiesOf("NG");                        // all 491
 * await citiesOf("NG", { state: "NG-LA" });    // Lagos State only
 * ```
 */
export async function citiesOf(
  key: CountryRef,
  options: { state?: StateRef; limit?: number } = {},
): Promise<City[]> {
  const c = resolveCountry(key);
  if (options.state === undefined) {
    return citiesInCountry(await loadCities(c.iso2), c.iso2, options.limit);
  }
  // The subdivisions come along only when one has to be resolved, and are
  // fetched alongside the cities rather than after them.
  const [cities, { states }] = await Promise.all([
    loadCities(c.iso2),
    chunkFor<StateChunk>(STATES, c.iso2, "states"),
  ]);
  return citiesInState(cities, lookupState(c, states, options.state), options.limit);
}

/**
 * Prefix search over one country's cities, loaded on demand.
 *
 * Same signature as `geodata-js/cities`'s `searchCities`, so a call written
 * against one surface works verbatim against the other -- except that
 * `country` is required here. Searching all 152,970 cities from a browser
 * would mean shipping 4.7 MB; if you need that, do it on a server behind
 * `createGeoHandler` from `geodata-js/next`.
 *
 * ```ts
 * await searchCities("lagos", { country: "NG", limit: 10 });
 * ```
 */
export async function searchCities(
  query: string,
  options: { country: CountryRef; limit?: number },
): Promise<City[]> {
  const c = resolveCountry(options.country);
  return searchIn(await loadCities(c.iso2), query, options.limit ?? 25);
}

