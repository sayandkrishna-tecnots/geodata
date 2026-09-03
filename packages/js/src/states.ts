/**
 * All 5,308 subdivisions, synchronously -- `geodata-js/states`.
 *
 * 336 KB gzipped. Fine on a server, in a React Server Component, or in a build
 * step. In a *client* bundle prefer the root entry's `await statesOf("NG")`,
 * which dynamically imports one country's chunk (Nigeria: 14 KB) instead.
 *
 * Both surfaces return identical rows -- they share `internal/stateOps.ts`, so
 * the sync and async paths cannot drift.
 *
 * Subdivisions nest: the UK has 221 of them across two levels. `statesOf("GB")`
 * returns all 221; `rootStates("GB")` returns the four a dropdown wants.
 * `depth` is computed by the build and authoritative -- upstream's `level` is
 * advisory and disagrees with the tree for 996 states.
 */

import { states as ALL } from "./data/states.all.js";
import type { State, StateNode } from "./generated/types.js";
import { resolveCountry, type CountryRef } from "./internal/countries.js";
import {
  buildTree,
  childrenOf,
  filterStates,
  lookupState,
  walk,
  type StateFilter,
  type StateQuery,
  type StateRef,
} from "./internal/stateOps.js";

export type { State, StateNode, StateFilter, StateQuery, StateRef, CountryRef };
export { walk };

/** Every subdivision, in dataset order. */
export const states: State[] = ALL;

// Sliced per country on first use rather than indexed globally: the lookups
// below scan one country's rows, and the largest country has 221 of them.
let byCountry: Map<string, State[]> | undefined;
let byId: Map<number, State> | undefined;

function slice(iso2: string): State[] {
  if (!byCountry || !byId) {
    byCountry = new Map();
    byId = new Map();
    for (const s of ALL) {
      byId.set(s.id, s);
      const bucket = byCountry.get(s.country_iso2);
      if (bucket) bucket.push(s);
      else byCountry.set(s.country_iso2, [s]);
    }
  }
  return byCountry.get(iso2) ?? [];
}

/**
 * Subdivisions of a country, sorted by name.
 *
 * ```ts
 * statesOf("GB", { depth: 1 });           // England, N. Ireland, Scotland, Wales
 * statesOf("GB", { parent: "GB-SCT" });   // the 32 Scottish council areas
 * statesOf("ES", { type: "autonomous community" });
 * ```
 */
export function statesOf(country: CountryRef, filter: StateFilter = {}): State[] {
  const c = resolveCountry(country);
  return filterStates(c, slice(c.iso2), filter);
}

/** The top-level subdivisions -- what a first-tier dropdown should show. */
export function rootStates(country: CountryRef): State[] {
  return statesOf(country, { depth: 1 });
}

/** The direct children of a state. */
export function subStatesOf(state: State | number): State[] {
  const row = typeof state === "number" ? getStateById(state) : state;
  if (!row) return [];
  return childrenOf(slice(row.country_iso2), row);
}

/**
 * Look a state up within a country.
 *
 * ```ts
 * getState("GB", "GB-BIR");
 * getState("GB", "BIR");                   // qualified with the country
 * getState("GB", { name: "Birmingham" });
 * ```
 *
 * Throws `Ambiguous` rather than guessing when a name matches twice -- a
 * silently wrong subdivision ends up on a shipping label.
 */
export function getState(country: CountryRef, key: StateRef): State {
  const c = resolveCountry(country);
  return lookupState(c, slice(c.iso2), key);
}

/** Like {@link getState} but returns `undefined` instead of throwing. */
export function findState(country: CountryRef, key: StateRef): State | undefined {
  try {
    return getState(country, key);
  } catch {
    return undefined;
  }
}

/**
 * Subdivisions as a forest, roots first.
 *
 * ```ts
 * stateTree("GB").map((n) => n.state.name);
 * // ["England", "Northern Ireland", "Scotland", "Wales"]
 * ```
 */
export function stateTree(country: CountryRef): StateNode[] {
  const c = resolveCountry(country);
  return buildTree(c, slice(c.iso2));
}

/**
 * For a multi-level territory, the state row it also exists as.
 *
 * Martinique is both country `MQ` and French subdivision `FR-MQ`; ISO 3166
 * lists it at both levels and neither is canonical, so both are reachable.
 * Returns `undefined` for the countries that are only countries.
 */
export function subdivisionTwin(country: CountryRef): State | undefined {
  const link = resolveCountry(country).also_subdivision_of;
  return link ? getStateById(link.state_id) : undefined;
}

/**
 * Look a state up by its upstream id.
 *
 * Provided for interoperability with data that already holds one. Do not
 * persist these -- 351 state ids changed meaning between two consecutive
 * upstream releases. Store `stable_key` or `iso3166_2` instead.
 */
export function getStateById(id: number): State | undefined {
  slice("");
  return byId!.get(id);
}
