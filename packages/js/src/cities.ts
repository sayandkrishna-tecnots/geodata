/**
 * All 152,970 cities, synchronously -- `geodata-js/cities`. **Server only.**
 *
 * ```ts
 * import { citiesOf, searchCities } from "geodata-js/cities";
 * ```
 *
 * Roughly 4.7 MB gzipped. Nothing in the root entry or `geodata-js/states` can
 * reach it, and that is structural rather than advisory: the cities table is
 * imported here and in the per-country chunks and nowhere else, so no
 * tree-shaking failure elsewhere can drag it into a client bundle.
 *
 * The package's `browser` export condition redirects this subpath to a stub, so
 * bundling it for a browser fails with an explanation instead of silently
 * shipping 4.7 MB. From client code use one of:
 *
 * ```ts
 * import { citiesOf } from "geodata-js";               // one country, lazily
 * import { cities } from "geodata-js/country/NG";      // one country, statically
 * import { createGeoHandler } from "geodata-js/next";  // a server endpoint
 * ```
 *
 * ### Next.js
 *
 * Keep it out of every serverless function trace:
 *
 * ```js
 * // next.config.js
 * module.exports = { serverExternalPackages: ["geodata-js"] };
 * ```
 */

import { cities as ROWS } from "./data/cities.all.js";
import { states as STATE_ROWS } from "./data/states.all.js";
import type { City, State } from "./generated/types.js";
import { resolveCountry, type CountryRef } from "./internal/countries.js";
import {
  citiesInCountry,
  citiesInState,
  indexOf,
  lookupCity,
  searchIn,
} from "./internal/cityOps.js";
import { lookupState, type StateQuery } from "./internal/stateOps.js";

export type { City } from "./generated/types.js";
export type { StateQuery } from "./internal/stateOps.js";

/** Every city, in dataset order. */
export const cities: City[] = ROWS;

/** How a subdivision may be named when asking for its cities. */
export type StateRef = State | string | number | StateQuery;

// Sliced per country on first use rather than indexed globally: `lookupState`
// scans a country's rows, and the largest country has 221 of them.
let statesByCountry: Map<string, State[]> | undefined;
function statesOfCountry(iso2: string): State[] {
  if (!statesByCountry) {
    statesByCountry = new Map();
    for (const s of STATE_ROWS) {
      const bucket = statesByCountry.get(s.country_iso2);
      if (bucket) bucket.push(s);
      else statesByCountry.set(s.country_iso2, [s]);
    }
  }
  return statesByCountry.get(iso2) ?? [];
}

/**
 * Cities of a country, or of one subdivision within it. Sorted by name.
 *
 * ```ts
 * citiesOf("NG");                       // all 491
 * citiesOf("NG", { state: "NG-LA" });   // Lagos State
 * ```
 *
 * Cities attach to whichever subdivision upstream put them under, which in a
 * nested country is usually a leaf rather than the top level. Asking a
 * `depth: 1` state for its cities can therefore return few or none -- to
 * collect a whole branch, walk `stateTree` from `geodata-js/states` and union
 * the results.
 */
export function citiesOf(
  country: CountryRef,
  options: { state?: StateRef; limit?: number } = {},
): City[] {
  const c = resolveCountry(country);
  if (options.state === undefined) return citiesInCountry(ROWS, c.iso2, options.limit);
  const state = lookupState(c, statesOfCountry(c.iso2), options.state);
  return citiesInState(ROWS, state, options.limit);
}

/** Exact city lookup within a subdivision. Throws `Ambiguous` on a repeat. */
export function getCity(country: CountryRef, state: StateRef, name: string): City {
  return lookupCity(citiesOf(country, { state }), name);
}

/** Like {@link getCity} but returns `undefined` instead of throwing. */
export function findCity(
  country: CountryRef,
  state: StateRef,
  name: string,
): City | undefined {
  try {
    return getCity(country, state, name);
  } catch {
    return undefined;
  }
}

/**
 * Prefix search over city names, exact matches first.
 *
 * Accent- and case-insensitive through the shared fold, so `"sao paulo"` finds
 * `"São Paulo"`. Scope it to a country where you can -- an unscoped search
 * scans until it has `limit` exact hits, which for a rare name means the whole
 * table.
 *
 * ```ts
 * searchCities("lagos", { country: "NG", limit: 10 });
 * ```
 */
export function searchCities(
  query: string,
  options: { country?: CountryRef; limit?: number } = {},
): City[] {
  const pool =
    options.country === undefined
      ? ROWS
      : (indexOf(ROWS).country.get(resolveCountry(options.country).iso2) ?? []);
  return searchIn(pool, query, options.limit ?? 25);
}

/**
 * Look a city up by its upstream id.
 *
 * Provided for interoperability with data that already holds one. Do not
 * persist these -- 6,321 city ids changed meaning between two consecutive
 * upstream releases. Store `stable_key` instead.
 */
export function getCityById(id: number): City | undefined {
  return indexOf(ROWS).id.get(id);
}
