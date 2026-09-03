/**
 * Browser stub for `geodata-js/cities`, resolved by the package's `browser`
 * export condition.
 *
 * The real module carries 4.7 MB gzipped. If a bundler pulled it into a client
 * bundle the failure mode would be a silently enormous download, which nobody
 * notices until production. Failing loudly at the call site is the far cheaper
 * mistake, and because the condition swaps the module out entirely, the table is
 * never in the graph -- this is not dead code a bundler has to shake out.
 *
 * The alternatives, in the order you should reach for them:
 *   - `await citiesOf(country, state)` from the root entry, which lazily imports
 *     just that country (Nigeria: 14 KB)
 *   - a route handler from `createGeoHandler()` in `geodata-js/next`, for
 *     autocomplete across all 152,970
 */

import type { City, State } from "./generated/types.js";

const MESSAGE =
  "geodata-js/cities is server-only (4.7 MB) and was resolved in a browser " +
  "build. Use `await citiesOf(...)` from the root entry, which loads one " +
  "country lazily, or query a route handler built with createGeoHandler() " +
  "from geodata-js/next.";

function unavailable(): never {
  throw new Error(MESSAGE);
}

/** Empty here. The real export is the full 152,970-row table. */
export const cities: City[] = [];

export const citiesOf: (...args: never[]) => City[] = unavailable;
export const getCity: (...args: never[]) => City = unavailable;
export const searchCities: (...args: never[]) => City[] = unavailable;
export const getCityById: (...args: never[]) => City | undefined = unavailable;
export const citiesInSubdivision: (state: State, limit?: number) => City[] = unavailable;

export type { City };
export { byName } from "./internal/countries.js";
