/**
 * ISO 639 lookup, shared by the root entry and `geodata-js/translations`.
 *
 * Kept out of `index.ts` so the translations subpath can resolve a locale tag
 * without importing the country table through the root entry -- and so the two
 * modules cannot form an import cycle.
 */

import { languages as ROWS } from "../data/languages.js";
import { LanguageNotFound } from "../errors.js";
import type { Language } from "../generated/types.js";
import { normalizeName } from "../normalize.js";

export const ALL: Language[] = ROWS;

/** A language code (`pt`), a BCP-47 tag (`pt-BR`), an English name, or a row. */
export type LanguageRef = Language | string;

let index: { code: Map<string, Language>; name: Map<string, Language> } | undefined;

function build() {
  const code = new Map<string, Language>();
  const name = new Map<string, Language>();
  for (const lang of ROWS) {
    code.set(lang.code, lang);
    // Two-letter codes win a name collision: "Greek" is both `el` and `grc`
    // (Ancient Greek) in some vintages of this list, and a caller asking by
    // name means the living language.
    const existing = name.get(lang.normalized_name);
    if (!existing || (lang.standard === "iso639_1" && existing.standard !== "iso639_1")) {
      name.set(lang.normalized_name, lang);
    }
  }
  return { code, name };
}

/**
 * Resolve a language reference, or `undefined`.
 *
 * Only the primary subtag is matched: this table describes languages, not
 * regional variants, so `pt-BR`, `pt_BR` and `zh-Hans-CN` resolve to `pt` and
 * `zh` respectively. Callers that care about the region should keep the
 * original tag -- `translationsOf` is keyed on the full tag.
 */
export function findLanguageRef(key: LanguageRef | null | undefined): Language | undefined {
  if (key === null || key === undefined) return undefined;
  if (typeof key === "object") return key;
  const text = key.trim();
  if (!text) return undefined;
  index ??= build();
  const primary = text.split(/[-_]/)[0].toLowerCase();
  return index.code.get(primary) ?? index.name.get(normalizeName(text));
}

export function resolveLanguage(key: LanguageRef): Language {
  const lang = findLanguageRef(key);
  if (!lang) throw new LanguageNotFound(`no language matches ${JSON.stringify(key)}`);
  return lang;
}
