/**
 * Locale resolution against a translation table.
 *
 * Split out of `translations.ts` because the fallback chain is the only part
 * with real behaviour in it, and it is worth testing on its own.
 */

import type { Translations } from "../generated/types.js";
import { findLanguageRef, type LanguageRef } from "./languages.js";

/**
 * The best available translation for `language`, else `fallback`.
 *
 * Three tiers, in order:
 *
 *   1. the exact tag -- `pt-BR` when the table has `pt-BR`
 *   2. the base language -- `pt-BR` falls back to `pt`
 *   3. any regional variant of the base -- `zh` finds `zh-CN`
 *
 * Tier 3 matters because upstream ships Chinese only as `zh-CN`: without it,
 * asking for `zh` would return nothing despite a perfectly good name being
 * present. Sorting the keys keeps the choice deterministic when a language has
 * several regional variants.
 */
export function pickTranslation(
  table: Translations,
  language: LanguageRef | null | undefined,
  fallback?: unknown,
): unknown {
  const tag = (typeof language === "object" && language !== null ? language.code : language ?? "")
    .toString()
    .trim();
  if (!tag) return fallback;
  if (tag in table) return table[tag];

  const lang = findLanguageRef(tag);
  if (!lang) return fallback;
  if (lang.code in table) return table[lang.code];

  for (const key of Object.keys(table).sort()) {
    if (key.split("-")[0].toLowerCase() === lang.code) return table[key];
  }
  return fallback;
}
