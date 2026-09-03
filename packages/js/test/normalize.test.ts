/**
 * The fold, against the shared fixture and against the dataset itself.
 *
 * `normalizeName` is half of every stable key, so if this file and
 * `scripts/lib/normalize.py` disagree by one character, JS and Python resolve
 * the same query to different rows. The fixture at
 * `tests/fixtures/normalize.json` is the contract both implementations sign.
 *
 * The second suite is the stronger one: it re-folds every name in
 * `data/canonical` and compares against the `normalized_name` CPython computed
 * at build time. That is 158,976 assertions across Latin, Cyrillic, Greek,
 * Arabic and CJK -- a fixture can be tuned to pass, a whole dataset cannot.
 */

import { createReadStream, readFileSync } from "node:fs";
import { createInterface } from "node:readline";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { cleanText, normalizeKey, normalizeName, slugify } from "../src/normalize.js";

const REPO = join(dirname(dirname(fileURLToPath(import.meta.url))), "..", "..");

const fixture = JSON.parse(
  readFileSync(join(REPO, "tests", "fixtures", "normalize.json"), "utf8"),
) as {
  normalize_name: Array<{ in: string; out: string }>;
  normalize_key?: Array<{ in: string; out: string }>;
};

describe("the shared fixture", () => {
  it("is not empty", () => {
    expect(fixture.normalize_name.length).toBeGreaterThan(20);
  });

  describe("normalizeName", () => {
    it.each(fixture.normalize_name.map((c) => [JSON.stringify(c.in), c] as const))(
      "%s",
      (_id, c) => {
        expect(normalizeName(c.in)).toBe(c.out);
      },
    );
  });

  describe("normalizeKey", () => {
    it.each((fixture.normalize_key ?? []).map((c) => [JSON.stringify(c.in), c] as const))(
      "%s",
      (_id, c) => {
        expect(normalizeKey(c.in)).toBe(c.out);
      },
    );
  });
});

describe("the fold's documented behaviour", () => {
  it("strips Latin diacritics, because there they decorate a letter", () => {
    expect(normalizeName("Saint-Étienne")).toBe("saint etienne");
    expect(normalizeName("São Paulo")).toBe("sao paulo");
    expect(normalizeName("Köln")).toBe("koln");
  });

  it("keeps Cyrillic marks, because there they are the letter", () => {
    // NFKD splits `й` into `и` + breve. Stripping it would collide
    // `Октябрьский` with a hypothetical `Октябрьскии`.
    expect(normalizeName("Октябрьский")).toBe("октябрьский");
    expect(normalizeName("Ёлкино")).toBe("ёлкино");
    expect(normalizeName("Октябрьский")).not.toBe(normalizeName("Октябрьскии"));
  });

  it("preserves script rather than transliterating", () => {
    expect(normalizeName("北京")).toBe("北京");
    expect(normalizeName("Αθήνα")).toBe("αθηνα");
    expect(normalizeName("القاهرة")).toBe("القاهرة");
  });

  it("never folds a non-empty name to an empty string", () => {
    // An earlier draft of the Python normalizer folded Cyrillic and Arabic
    // names to "", which silently collapsed their stable keys together.
    for (const name of ["Москва", "القاهرة", "北京", "서울", "Αθήνα", "ทดสอบ"]) {
      expect(normalizeName(name), name).not.toBe("");
    }
  });

  it("casefolds where lowercasing is not enough", () => {
    // `toLowerCase()` leaves both of these alone; `casefold()` does not.
    expect(normalizeName("Gießen")).toBe("giessen");
    expect(normalizeName("ﬁnd")).toBe("find");
  });

  it("treats connectors and punctuation as word separators", () => {
    expect(normalizeName("N'Djamena")).toBe("n djamena");
    expect(normalizeName("Washington, D.C.")).toBe("washington d c");
    expect(normalizeName("Sainte‐Anne")).toBe("sainte anne");
  });

  it("collapses and trims whitespace", () => {
    expect(normalizeName("  Lagos  ")).toBe("lagos");
    expect(normalizeName("New York")).toBe("new york");
  });

  it("handles nullish and non-string input without throwing", () => {
    expect(normalizeName(null)).toBe("");
    expect(normalizeName(undefined)).toBe("");
    expect(normalizeName(123)).toBe("123");
    expect(normalizeKey(null)).toBe("");
  });

  it("slugifies to a URL-safe form", () => {
    expect(slugify("São Paulo")).toBe("sao-paulo");
    expect(slugify("Washington, D.C.")).toBe("washington-d-c");
  });

  it("normalizeKey is ASCII-only, since codes are ASCII by definition", () => {
    expect(normalizeKey("GB-BIR")).toBe("gbbir");
    expect(normalizeKey("  us-ca ")).toBe("usca");
  });

  it("cleanText preserves the display form", () => {
    expect(cleanText("  São   Paulo ")).toBe("São Paulo");
    expect(cleanText("   ")).toBeNull();
    expect(cleanText(null)).toBeNull();
  });
});

describe("against the whole dataset", () => {
  it("reproduces every normalized_name CPython computed", async () => {
    let checked = 0;
    const mismatches: string[] = [];

    for (const table of ["countries", "states", "cities", "languages", "regions", "subregions"]) {
      const stream = createReadStream(join(REPO, "data", "canonical", `${table}.ndjson`));
      const lines = createInterface({ input: stream, crlfDelay: Infinity });
      for await (const line of lines) {
        if (!line.trim()) continue;
        const row = JSON.parse(line) as { name: string; normalized_name: string };
        checked++;
        const got = normalizeName(row.name);
        if (got !== row.normalized_name && mismatches.length < 10) {
          mismatches.push(
            `${table} ${JSON.stringify(row.name)}: js=${JSON.stringify(got)} py=${JSON.stringify(row.normalized_name)}`,
          );
        }
      }
    }

    expect(mismatches, mismatches.join("\n")).toEqual([]);
    // Guards against the loop silently reading nothing and passing.
    expect(checked).toBeGreaterThan(150_000);
  });
});
