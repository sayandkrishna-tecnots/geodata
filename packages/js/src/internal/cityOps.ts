/**
 * City queries, expressed over a plain `City[]`.
 *
 * Every function takes its rows as an argument rather than importing a table.
 * That is what lets the root entry (async, one country's chunk at a time) and
 * `geodata-js/cities` (sync, all 152,970) share one implementation. If the two
 * had separate lookup code they would drift, and a city that resolves in a
 * server component but not a client one is exactly the class of bug this
 * package exists to prevent.
 */

import { Ambiguous, CityNotFound } from "../errors.js";
import type { City, State } from "../generated/types.js";
import { normalizeName } from "../normalize.js";
import { byName } from "./sort.js";

export interface CityIndex {
  id: Map<number, City>;
  state: Map<number, City[]>;
  country: Map<string, City[]>;
}

// Keyed on the array itself, so the full table is indexed once and a
// per-country chunk is indexed once, without either knowing the other exists.
// Weak, so a chunk loaded for a single query does not pin 4.7 MB of derived
// maps for the life of the process.
const CACHE = new WeakMap<City[], CityIndex>();

/** Index `rows` by id, state and country. Memoized per array. */
export function indexOf(rows: City[]): CityIndex {
  let idx = CACHE.get(rows);
  if (idx) return idx;

  idx = { id: new Map(), state: new Map(), country: new Map() };
  for (const c of rows) {
    idx.id.set(c.id, c);
    const byState = idx.state.get(c.state_id);
    if (byState) byState.push(c);
    else idx.state.set(c.state_id, [c]);
    const inCountry = idx.country.get(c.country_iso2);
    if (inCountry) inCountry.push(c);
    else idx.country.set(c.country_iso2, [c]);
  }
  CACHE.set(rows, idx);
  return idx;
}

function sorted(rows: City[], limit?: number): City[] {
  const out = rows.slice().sort(byName);
  return limit === undefined ? out : out.slice(0, limit);
}

/** Every city of one country, sorted by name. */
export function citiesInCountry(rows: City[], iso2: string, limit?: number): City[] {
  return sorted(indexOf(rows).country.get(iso2) ?? [], limit);
}

/** Every city of one subdivision, sorted by name. */
export function citiesInState(rows: City[], state: State | number, limit?: number): City[] {
  const id = typeof state === "number" ? state : state.id;
  return sorted(indexOf(rows).state.get(id) ?? [], limit);
}

/**
 * Exact city lookup within an already-scoped set.
 *
 * Throws {@link Ambiguous} rather than returning the first hit: a state
 * genuinely can contain two places of the same name, and silently picking one
 * puts a wrong town on a shipping label.
 */
export function lookupCity(rows: City[], name: string): City {
  const needle = normalizeName(name);
  const matches = rows.filter((c) => c.normalized_name === needle);
  if (matches.length === 0) throw new CityNotFound(`no city ${JSON.stringify(name)} there`);
  if (matches.length > 1) {
    throw new Ambiguous(`${matches.length} cities match ${JSON.stringify(name)}`);
  }
  return matches[0];
}

/**
 * Prefix search: exact matches first, then prefix, then substring.
 *
 * Accent- and case-insensitive through the shared fold, so `"sao paulo"` finds
 * `"São Paulo"` and `"koln"` finds `"Köln"`.
 */
export function searchIn(pool: City[], query: string, limit = 25): City[] {
  const needle = normalizeName(query);
  if (!needle) return [];

  const exact: City[] = [];
  const prefix: City[] = [];
  const contains: City[] = [];
  for (const c of pool) {
    const n = c.normalized_name;
    if (n === needle) exact.push(c);
    else if (n.startsWith(needle)) prefix.push(c);
    else if (n.includes(needle)) contains.push(c);
    // Enough exact hits to fill the page: nothing ranked lower could displace
    // them, so there is no reason to keep scanning 152,970 rows.
    if (exact.length >= limit) break;
  }
  return exact.concat(prefix.sort(byName), contains.sort(byName)).slice(0, limit);
}
