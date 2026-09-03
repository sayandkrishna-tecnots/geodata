/**
 * Country resolution, shared by every entry point.
 *
 * Lives in `internal/` rather than `index.ts` so that `geodata-js/states` and
 * `geodata-js/cities` can resolve a country without importing the root entry
 * (and, through it, the language table).
 */

import { countries as ROWS } from "../data/countries.js";
import { CountryNotFound } from "../errors.js";
import type { Country } from "../generated/types.js";
import { normalizeName } from "../normalize.js";

export const ALL: Country[] = ROWS;

interface CountryIndex {
  iso2: Map<string, Country>;
  iso3: Map<string, Country>;
  numeric: Map<string, Country>;
  id: Map<number, Country>;
  name: Map<string, Country>;
  native: Map<string, Country>;
}

let index: CountryIndex | undefined;

function build(): CountryIndex {
  const idx: CountryIndex = {
    iso2: new Map(), iso3: new Map(), numeric: new Map(),
    id: new Map(), name: new Map(), native: new Map(),
  };
  for (const c of ALL) {
    idx.iso2.set(c.iso2, c);
    idx.id.set(c.id, c);
    if (!idx.name.has(c.normalized_name)) idx.name.set(c.normalized_name, c);
    // Native names are a lower-priority tier: people do type "Deutschland" and
    // "Cote d'Ivoire", but a native name occasionally collides with another
    // country's English name, so it must never win.
    if (c.native) {
      const key = normalizeName(c.native);
      if (!idx.native.has(key)) idx.native.set(key, c);
    }
    if (c.iso3) idx.iso3.set(c.iso3, c);
    if (c.numeric_code) idx.numeric.set(c.numeric_code.replace(/^0+(?=.)/, ""), c);
  }
  return idx;
}

export function countryIndex(): CountryIndex {
  return (index ??= build());
}

/** Country reference: an iso2/iso3/numeric code, a name, an id, or the row. */
export type CountryRef = Country | string | number;

/** Like {@link resolveCountry} but returns `undefined` instead of throwing. */
export function findCountryRef(key: CountryRef | null | undefined): Country | undefined {
  if (key === null || key === undefined) return undefined;
  if (typeof key === "object") return key;
  const idx = countryIndex();
  if (typeof key === "number") return idx.id.get(key);

  const text = key.trim();
  if (!text) return undefined;
  const upper = text.toUpperCase();
  if (upper.length === 2) return idx.iso2.get(upper);
  if (upper.length === 3 && /^[A-Z]+$/.test(upper)) return idx.iso3.get(upper);
  if (/^\d+$/.test(text)) {
    return idx.numeric.get(text.replace(/^0+(?=.)/, "")) ?? idx.id.get(Number(text));
  }
  const normalized = normalizeName(text);
  return idx.name.get(normalized) ?? idx.native.get(normalized);
}

export function resolveCountry(key: CountryRef): Country {
  const country = findCountryRef(key);
  if (!country) throw new CountryNotFound(`no country matches ${JSON.stringify(key)}`);
  return country;
}

export { byName } from "./sort.js";
