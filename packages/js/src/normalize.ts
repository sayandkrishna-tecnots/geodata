/**
 * The deterministic fold shared by every geodata artifact.
 *
 * This is a port of `scripts/lib/normalize.py`, and "port" is doing real work:
 * `normalized_name` is half of the stable-key strategy, so if this file and the
 * Python one disagree by a single character, JS and Python resolve the same
 * query to different rows. `test/normalize.test.ts` runs the shared fixture at
 * `tests/fixtures/normalize.json`, and `tests/test_conformance.py` re-folds
 * every one of the 158,528 names in the dataset through both implementations
 * and diffs them.
 *
 * Algorithm, in order:
 *   1. NFKD decompose
 *   2. drop combining marks -- except over a Cyrillic base -- then NFC
 *   3. casefold
 *   4. connectors and punctuation -> a single space
 *   5. drop remaining non-alphanumerics, in any script
 *   6. collapse whitespace, trim
 *
 * Step 5 is script-preserving, not transliterating: `Октябрьский` folds to
 * `октябрьский`, not `oktyabrskiy`. The key's job is to match a name to itself
 * across dataset versions, and a name is stable in its own script.
 *
 * Step 2 is script-aware for the same reason. In Latin a diacritic decorates a
 * letter, so stripping it is the right fold. In Cyrillic it *is* the letter:
 * NFKD splits `й` into `и` + breve, and blindly stripping would collide
 * `Октябрьский` with a hypothetical `Октябрьскии`.
 */

import { CASEFOLD_DELTA, COMBINING, MARK_BEARING } from "./generated/unicode.js";

/** "start:len" hex pairs -> a sorted array of [start, endExclusive). */
function unpack(packed: string): number[] {
  const out: number[] = [];
  for (const pair of packed.split(" ")) {
    const colon = pair.indexOf(":");
    const start = parseInt(pair.slice(0, colon), 16);
    out.push(start, start + parseInt(pair.slice(colon + 1), 16) + 1);
  }
  return out;
}

const COMBINING_RANGES = /* @__PURE__ */ unpack(COMBINING);
const MARK_BEARING_RANGES = /* @__PURE__ */ unpack(MARK_BEARING);

/** Binary search over the flattened [start, end) pairs. */
function inRanges(ranges: number[], cp: number): boolean {
  let lo = 0;
  let hi = ranges.length / 2;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (cp < ranges[mid * 2]) hi = mid;
    else if (cp >= ranges[mid * 2 + 1]) lo = mid + 1;
    else return true;
  }
  return false;
}

const FOLD = /* @__PURE__ */ (() => {
  const map = new Map<string, string>();
  for (const entry of CASEFOLD_DELTA.split(" ")) {
    const gt = entry.indexOf(">");
    const from = String.fromCodePoint(parseInt(entry.slice(0, gt), 16));
    const to = entry
      .slice(gt + 1)
      .split("-")
      .map((h) => String.fromCodePoint(parseInt(h, 16)))
      .join("");
    map.set(from, to);
  }
  return map;
})();

/**
 * Python's `str.casefold()`.
 *
 * `toLowerCase()` alone is not it: casefold maps `ß` to `ss` and `ﬁ` to `fi`,
 * lowercase leaves both alone. The 297 codepoints where the two disagree are
 * generated into CASEFOLD_DELTA; everywhere else JS lowercasing and CPython
 * `str.lower()` already agree, so applying the delta and then lowercasing
 * reproduces `casefold()` exactly.
 */
function casefold(value: string): string {
  let out = "";
  for (const ch of value) out += FOLD.get(ch) ?? ch;
  return out.toLowerCase();
}

/** NFKD, drop decorative combining marks, NFC. */
function stripDecorativeMarks(value: string): string {
  let out = "";
  let base = 0;
  for (const ch of value.normalize("NFKD")) {
    const cp = ch.codePointAt(0)!;
    if (inRanges(COMBINING_RANGES, cp)) {
      if (inRanges(MARK_BEARING_RANGES, base)) out += ch;
      continue;
    }
    base = cp;
    out += ch;
  }
  return out.normalize("NFC");
}

// Whitespace, dashes (incl. U+2010..U+2015), underscore, slashes, and the
// punctuation that separates words in place names. Kept character-for-character
// identical to _SEPARATORS in scripts/lib/normalize.py.
const SEPARATORS = /[\s\-‐-―_/\\.,;:()[\]{}'‘’"“”`]+/gu;
// Python's `[^\w]` under re.UNICODE: letters and digits of every script, plus
// the underscore, which the line below then turns into a space.
const NON_ALNUM = /[^\p{L}\p{N}_]+/gu;
const NON_ALNUM_ASCII = /[^0-9a-z]+/g;
const WS = /\s+/gu;

/**
 * Fold a place name to its comparison key.
 *
 * ```ts
 * normalizeName("Saint-Étienne"); // "saint etienne"
 * normalizeName("  N'Djamena ");  // "n djamena"
 * normalizeName("São Paulo");     // "sao paulo"
 * ```
 */
export function normalizeName(value: unknown): string {
  if (value === null || value === undefined) return "";
  let text = typeof value === "string" ? value : String(value);
  text = stripDecorativeMarks(text);
  text = casefold(text);
  text = text.replace(SEPARATORS, " ");
  text = text.replace(NON_ALNUM, " ").replace(/_/g, " ");
  return text.replace(WS, " ").trim();
}

/**
 * Fold a code (`iso2`, `iso3166_2`, `state_code`) to its comparison key.
 * ASCII-only, because these codes are ASCII by definition.
 */
export function normalizeKey(value: unknown): string {
  if (value === null || value === undefined) return "";
  return casefold(String(value)).replace(NON_ALNUM_ASCII, "");
}

/** URL-safe form of a place name: `slugify("São Paulo") === "sao-paulo"`. */
export function slugify(value: unknown): string {
  return normalizeName(value).replace(/ /g, "-");
}

/**
 * Normalize a human-readable string for storage: NFC, trimmed, single spaces.
 * Preserves accents and case -- this is the display form, not the key form.
 */
export function cleanText(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  let text = typeof value === "string" ? value : String(value);
  text = text.normalize("NFC").replace(/ /g, " ").replace(/​/g, "");
  return text.replace(WS, " ").trim() || null;
}
