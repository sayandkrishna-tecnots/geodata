/**
 * geodata -- countries, subdivisions and cities as a queryable dataset.
 *
 * Two things to know before using this:
 *
 * 1. **Do not persist `id`.** Upstream ids are not stable across dataset
 *    versions: 351 state ids and 6,321 city ids changed meaning between two
 *    consecutive upstream releases. Persist `stable_key`, or `iso2` /
 *    `iso3166_2`. Every lookup here accepts those.
 *
 * 2. **Subdivisions nest.** The UK has 221 subdivisions across two levels.
 *    `statesOf("GB")` gives all of them; `{ depth: 1 }` gives the four you
 *    actually want in a dropdown.
 *
 * ## What this entry point costs
 *
 * Countries and languages only -- around 46 KB gzipped, safe in a client
 * component, an Edge function or a React Server Component. `statesOf` and
 * `citiesOf` here are **async**: each dynamically imports one country's table,
 * and only the table it needs. Nigeria's subdivisions cost 3 KB rather than
 * the 336 KB whole states table, and no city data is fetched to answer a
 * subdivision query -- which matters most for the United States, where the two
 * differ by 471 KB. On a server, import the synchronous versions instead:
 *
 * ```ts
 * import { statesOf } from "geodata-js/states";   // sync, all 5,308
 * import { citiesOf } from "geodata-js/cities";   // sync, server only
 * ```
 *
 * That async/sync split is the one place this package's shape differs from the
 * Python API, which is synchronous throughout. Results are identical; only the
 * call style differs.
 */

import { countries as ALL_COUNTRIES } from "./data/countries.js";
import { languages as ALL_LANGUAGES } from "./data/languages.js";
import { regions as ALL_REGIONS } from "./data/regions.js";
import { subregions as ALL_SUBREGIONS } from "./data/subregions.js";
import type { StateChunk } from "./generated/lazy.js";
import { STATES } from "./generated/lazy.states.js";
import { chunkFor } from "./internal/chunks.js";
import type { City, Country, Language, Region, State, Subregion } from "./generated/types.js";
import {
  byName,
  findCountryRef,
  resolveCountry,
  type CountryRef,
} from "./internal/countries.js";
import { findLanguageRef, resolveLanguage, type LanguageRef } from "./internal/languages.js";
import {
  filterStates,
  lookupState,
  type StateFilter,
  type StateQuery,
  type StateRef,
} from "./internal/stateOps.js";

export * from "./errors.js";
export type {
  City,
  Country,
  Language,
  Region,
  State,
  StateNode,
  Subregion,
  SubdivisionLink,
  Timezone,
  Translations,
} from "./generated/types.js";
export { COUNTRY_CODES, COUNTS_BY_COUNTRY, type CountryCode } from "./generated/manifest.js";
export { COUNTS, DATASET_VERSION, SOURCE_REPO, SOURCE_TAG, VERSION } from "./generated/version.js";
export { normalizeKey, normalizeName, slugify } from "./normalize.js";
export type { CountryRef } from "./internal/countries.js";
export type { StateFilter, StateQuery, StateRef } from "./internal/stateOps.js";
export type { LanguageRef } from "./internal/languages.js";
export type { CityChunk, CountryChunk, StateChunk } from "./generated/lazy.js";

// ---------------------------------------------------------------- countries

/** Filters accepted by {@link countries}. */
export interface CountryFilter {
  region?: string;
  subregion?: string;
  hasStates?: boolean;
}

/** All countries, optionally filtered. Sorted by name. */
export function countries(filter: CountryFilter = {}): Country[] {
  let rows = ALL_COUNTRIES;
  if (filter.region !== undefined) rows = rows.filter((c) => c.region === filter.region);
  if (filter.subregion !== undefined) rows = rows.filter((c) => c.subregion === filter.subregion);
  if (filter.hasStates !== undefined) rows = rows.filter((c) => c.has_states === filter.hasStates);
  return rows.slice().sort(byName);
}

/**
 * Look a country up by iso2, iso3, numeric code, id, or name. Throws
 * `CountryNotFound` if nothing matches.
 *
 * Names match the English name first and the native name second, both accent-
 * and case-insensitively, so `getCountry("Cote d'Ivoire")` resolves even
 * though the English name upstream is "Ivory Coast".
 *
 * ```ts
 * getCountry("NG").name;                    // "Nigeria"
 * getCountry("NGA") === getCountry("566");  // true
 * ```
 */
export function getCountry(key: CountryRef): Country {
  return resolveCountry(key);
}

/** Like {@link getCountry} but returns `undefined` instead of throwing. */
export function findCountry(key: CountryRef | null | undefined): Country | undefined {
  return findCountryRef(key);
}

/** The six top-level regions. */
export function regions(): Region[] {
  return ALL_REGIONS.slice().sort(byName);
}

/** The 22 subregions, optionally within one region. */
export function subregions(regionId?: number): Subregion[] {
  const rows =
    regionId === undefined ? ALL_SUBREGIONS : ALL_SUBREGIONS.filter((s) => s.region_id === regionId);
  return rows.slice().sort(byName);
}

// ------------------------------------------------------------ lazy per-country

/**
 * Subdivisions of one country, loaded on demand. Sorted by name.
 *
 * `{ depth: 1 }` is almost always what a dropdown wants:
 *
 * ```ts
 * await statesOf("GB");             // all 221
 * await statesOf("GB", { depth: 1 }); // England, Northern Ireland, Scotland, Wales
 * ```
 */
export async function statesOf(key: CountryRef, filter: StateFilter = {}): Promise<State[]> {
  const c = resolveCountry(key);
  // Subdivisions only. The country row is in the static table already, and the
  // cities are the expensive part -- a dropdown must not pay for them.
  const { states } = await chunkFor<StateChunk>(STATES, c.iso2, "states");
  return filterStates(c, states, filter);
}

/** The top-level subdivisions of one country, loaded on demand. */
export async function rootStates(key: CountryRef): Promise<State[]> {
  return statesOf(key, { depth: 1 });
}

// ---------------------------------------------------------------- languages

/**
 * The ISO 639 table, sorted by name.
 *
 * `"iso639_1"` gives the 184 two-letter codes -- the ones translation keys
 * actually use; `"iso639_2"` gives the 236 three-letter codes.
 */
export function languages(standard?: Language["standard"]): Language[] {
  const rows =
    standard === undefined ? ALL_LANGUAGES : ALL_LANGUAGES.filter((l) => l.standard === standard);
  return rows.slice().sort(byName);
}

/**
 * Look a language up by code or English name. Throws if nothing matches.
 *
 * Accepts a bare code (`pt`), a BCP-47 tag (`pt-BR`, `zh-Hans-CN`) or a name.
 * Only the primary subtag is matched -- this table describes languages, not
 * regional variants, so `pt-BR` and `pt` resolve to the same row.
 *
 * Unlike every other table here, a language `code` **is** the identity, so it
 * is the one value in this package that is safe to store in a foreign key.
 */
export function getLanguage(key: LanguageRef): Language {
  return resolveLanguage(key);
}

/** Like {@link getLanguage} but returns `undefined` instead of throwing. */
export function findLanguage(key: LanguageRef | null | undefined): Language | undefined {
  return findLanguageRef(key);
}
