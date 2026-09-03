/**
 * Translated country and state names -- `geodata-js/translations`.
 *
 * Its own subpath because the two tables are 667 KB gzipped, which is more than
 * the countries and states tables combined. Nothing in the root entry reaches
 * this file, so an app that does not localize place names never pays for it.
 *
 * Locale keys are BCP-47 tags: `pt` and `pt-BR` can both be present and mean
 * different strings. Every key's primary subtag resolves to a row in the ISO
 * 639 table -- that is validation check 9, enforced at build time.
 */

import { countryTranslations } from "./data/translations.countries.js";
import { stateTranslations } from "./data/translations.states.js";
import type { Country, State, Translations } from "./generated/types.js";
import type { LanguageRef } from "./internal/languages.js";
import { pickTranslation } from "./internal/translate.js";

export type { Translations };

/** A record that carries translations. Cities are not translated upstream. */
export type Translatable = Country | State;

function isState(record: Translatable): record is State {
  return "country_iso2" in record && "depth" in record;
}

/**
 * Translated names for a country or state, as `{locale: name}`.
 *
 * Returns an empty object -- not `undefined` -- for the records upstream has no
 * translations for (12 states, and every city).
 *
 * ```ts
 * translationsOf(getCountry("DE")).ja; // "ドイツ"
 * ```
 */
export function translationsOf(record: Translatable): Translations {
  const table = isState(record)
    ? stateTranslations[String(record.id)]
    : countryTranslations[record.iso2];
  return { ...(table ?? {}) };
}

/** Every locale tag present for `record`, sorted. */
export function localesOf(record: Translatable): string[] {
  return Object.keys(translationsOf(record)).sort();
}

/**
 * The record's name in `language`, falling back from a regional tag to its base
 * language, and finally to `fallback`.
 *
 * `fallback` defaults to `undefined` rather than the English name, so the caller
 * decides: pass `record.name` to get English, or leave it to detect the gap.
 *
 * ```ts
 * localizedName(getCountry("DE"), "fr");             // "Allemagne"
 * localizedName(getCountry("DE"), "xx", country.name); // "Germany"
 * ```
 */
export function localizedName(
  record: Translatable,
  language: LanguageRef | null | undefined,
): string | undefined;
export function localizedName<T>(
  record: Translatable,
  language: LanguageRef | null | undefined,
  fallback: T,
): string | T;
export function localizedName(
  record: Translatable,
  language: LanguageRef | null | undefined,
  fallback?: unknown,
): unknown {
  return pickTranslation(translationsOf(record), language, fallback);
}

export { countryTranslations, stateTranslations };
