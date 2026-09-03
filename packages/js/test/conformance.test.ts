/**
 * The JS half of the cross-language conformance suite.
 *
 * `tests/test_conformance.py` runs this exact file. A case that passes there and
 * fails here means the two SDKs disagree about the same dataset -- the failure
 * mode the multi-stack design exists to prevent, and the reason expectations
 * come from `data/canonical` rather than from either implementation.
 *
 * Each case is also run through the *async* root-entry surface where one
 * exists, because that surface is JS-only: Python has no equivalent, so nothing
 * else in this repo would catch it drifting from the sync path.
 */

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import * as geo from "../src/index.js";
// City loading lives on its own subpath so the root entry stays free of the
// 250 city chunks a bundler would otherwise emit -- see src/lazy.ts.
import * as lazy from "../src/lazy.js";
import * as citiesApi from "../src/cities.js";
import * as statesApi from "../src/states.js";
import { localizedName } from "../src/translations.js";
import { normalizeName } from "../src/normalize.js";

interface Case {
  fn: string;
  args: (string | number)[];
  expect: Record<string, unknown> | null;
}

const payload = JSON.parse(
  readFileSync(new URL("../../../tests/conformance/cases.json", import.meta.url), "utf8"),
) as { dataset_version: string; cases: Case[] };

const CASES = payload.cases;

/** Evaluate one case synchronously, returning the comparable projection. */
function run({ fn, args }: Case): Record<string, unknown> | null {
  const [a, b, c] = args as [string, string, number];
  switch (fn) {
    case "getCountry": {
      const row = geo.getCountry(a);
      return { iso2: row.iso2, name: row.name };
    }
    case "statesOf":
      return { count: statesApi.statesOf(a).length };
    case "rootStates": {
      const rows = statesApi.rootStates(a);
      return { count: rows.length, names: rows.map((s) => s.name).slice(0, 8) };
    }
    case "getState": {
      const row = statesApi.getState(a, b);
      return { iso3166_2: row.iso3166_2, name: row.name };
    }
    case "getStateByName":
      return { iso3166_2: statesApi.getState(a, { name: b }).iso3166_2 };
    case "citiesOf": {
      const rows = citiesApi.citiesOf(a, { state: b });
      return { count: rows.length, first: rows.length ? rows[0].name : null };
    }
    case "searchCities": {
      const rows = citiesApi.searchCities(a, { country: b, limit: c });
      return { first: rows.length ? rows[0].name : null };
    }
    case "localizedName":
      return { name: localizedName(geo.getCountry(a), b) ?? null };
    case "subdivisionTwin": {
      const twin = statesApi.subdivisionTwin(a);
      return twin ? { country_iso2: twin.country_iso2, iso3166_2: twin.iso3166_2 } : null;
    }
    case "getLanguage": {
      const lang = geo.getLanguage(a);
      return { code: lang.code, name: lang.name };
    }
    case "languageCounts":
      return {
        total: geo.languages().length,
        iso639_1: geo.languages("iso639_1").length,
        iso639_2: geo.languages("iso639_2").length,
      };
    case "normalizeName":
      return { out: normalizeName(a) };
    default:
      throw new Error(`unknown conformance fn: ${fn}`);
  }
}

/** Compare only the keys the case pins, exactly as the Python runner does. */
function check(actual: Record<string, unknown> | null, expected: Case["expect"]) {
  if (expected === null) {
    expect(actual).toBeNull();
    return;
  }
  expect(actual).not.toBeNull();
  const projected = Object.fromEntries(
    Object.keys(expected).map((k) => [k, (actual as Record<string, unknown>)[k]]),
  );
  expect(projected).toEqual(expected);
}

describe("conformance corpus", () => {
  it("is current with the dataset", () => {
    expect(payload.dataset_version).toBe(geo.DATASET_VERSION);
    expect(CASES.length).toBeGreaterThan(200);
  });

  it("covers every function the runner implements", () => {
    const seen = new Set(CASES.map((c) => c.fn));
    expect(seen.size).toBeGreaterThanOrEqual(11);
  });
});

describe("shared cases", () => {
  it.each(CASES.map((c) => [`${c.fn}(${c.args.join(",")})`, c] as const))("%s", (_id, c) => {
    check(run(c), c.expect);
  });
});

describe("the async surface agrees with the sync one", () => {
  // JS-only: Python is synchronous throughout, so the shared corpus cannot
  // exercise this. Restricted to the cases the root entry actually exposes.
  const async = CASES.filter((c) =>
    ["statesOf", "rootStates", "citiesOf", "searchCities"].includes(c.fn),
  );

  it("has async cases to run", () => {
    expect(async.length).toBeGreaterThan(20);
  });

  it.each(async.map((c) => [`${c.fn}(${c.args.join(",")})`, c] as const))("%s", async (_id, c) => {
    const [a, b, limit] = c.args as [string, string, number];
    let actual: Record<string, unknown> | null;
    switch (c.fn) {
      case "statesOf":
        actual = { count: (await geo.statesOf(a)).length };
        break;
      case "rootStates": {
        const rows = await geo.rootStates(a);
        actual = { count: rows.length, names: rows.map((s) => s.name).slice(0, 8) };
        break;
      }
      case "citiesOf": {
        const rows = await lazy.citiesOf(a, { state: b });
        actual = { count: rows.length, first: rows.length ? rows[0].name : null };
        break;
      }
      default: {
        // Both surfaces take (query, { country, limit }). They differ only in
        // that `country` is required here -- the root entry must know which
        // chunk to load -- while `geodata-js/cities` holds the whole table and
        // treats it as an optional narrowing. Corpus args are [query, country, limit].
        const rows = await lazy.searchCities(a, { country: b, limit });
        actual = { first: rows.length ? rows[0].name : null };
      }
    }
    check(actual, c.expect);
  });
});
