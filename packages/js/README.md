# geodata-js

250 countries, 5,308 subdivisions, 152,970 cities and 420 ISO 639 languages —
validated, versioned, and built from a pinned upstream release.

Zero runtime dependencies. Ships ESM, CJS and TypeScript declarations. Works in
Node, Next.js (RSC, route handlers, Edge), Vite, Bun, Deno and React Native.

```bash
npm install geodata-js
```

```ts
import { getCountry, countries, statesOf } from "geodata-js";

getCountry("NG").name;              // "Nigeria"
getCountry("NGA").capital;          // "Abuja"
countries({ region: "Africa" });    // 58 rows, sorted by name

await statesOf("GB", { depth: 1 }); // England, Northern Ireland, Scotland, Wales
```

## Two things to know first

**1. Never persist `id`.** Upstream renumbers between releases — 351 state ids
and 6,321 city ids changed meaning between two consecutive upstream versions.
Store `stable_key`, or `iso2` / `iso3166_2`. Every lookup here accepts those.

```ts
// ✗ breaks on the next dataset release
db.insert({ state_id: state.id });
// ✓ survives it
db.insert({ state_key: state.stable_key });   // or state.iso3166_2
```

**2. Subdivisions nest.** The UK has 221 subdivisions across two levels.
`statesOf("GB")` returns all 221; `rootStates("GB")` returns the four a dropdown
wants. `depth` is computed by the build and authoritative — upstream's `level`
is advisory and disagrees with the tree for 996 states.

## Entry points, and what each costs

The exports map is the design of this package. Cities are 4.7 MB gzipped, so
they are not reachable from the root entry at all — not "tree-shaken out", but
structurally absent.

| Import | Contents | gzipped |
|---|---|---|
| `geodata-js` | countries + languages; async `statesOf` | **55 KB** |
| `geodata-js/states` | all 5,308 subdivisions, sync | 380 KB |
| `geodata-js/lazy` | async per-country `citiesOf` / `searchCities` | code only |
| `geodata-js/cities` | all 152,970 cities, sync — **server only** | 4.7 MB |
| `geodata-js/translations` | country + state names in 28 locales | 700 KB |
| `geodata-js/country/NG` | one country: its row, states and cities | 17 KB |
| `geodata-js/normalize` | the name fold | 3 KB |
| `geodata-js/next` | `createGeoHandler()` route handler | — |

The root entry is safe in a client component, an Edge function or an RSC. Its
`statesOf` is **async**: it dynamically imports one country's subdivisions, so
Nigeria costs 2.4 KB fetched rather than the 336 KB table — and no city data,
which is what keeps its emitted-chunk total at 2.1 MB rather than 42 MB.

```ts
// client component — one country's subdivisions, lazily
import { statesOf } from "geodata-js";
const states = await statesOf("NG");

// server component — synchronous, whole table already in memory
import { statesOf } from "geodata-js/states";
const states = statesOf("NG");
```

To reach cities from a browser, prefer a route handler
(`createGeoHandler()` below) over `geodata-js/lazy` unless you need them
offline or for a single known country — the network round trip costs the user
nothing at build time and keeps the deploy small.

That async/sync split is the one place this package differs in shape from the
Python SDK, which is synchronous throughout. The rows are identical — a shared
conformance suite runs the same 258 cases against both.

## Next.js

Countries and states work anywhere. For city search from the client, keep the
table on the server:

```ts
// app/api/geo/route.ts
import { createGeoHandler } from "geodata-js/next";
export const GET = createGeoHandler();
```

```js
// next.config.js — keeps 4.7 MB out of every serverless function trace
module.exports = { serverExternalPackages: ["geodata-js"] };
```

Importing `geodata-js/cities` from a client component resolves to a stub that
throws with a pointer to the alternative, rather than silently shipping 4.7 MB.

## API

### Countries

```ts
getCountry("NG" | "NGA" | "566" | "Nigeria" | "Deutschland")  // throws if absent
findCountry(key)                                              // undefined if absent
countries({ region?, subregion?, hasStates? })
```

Rows carry the full upstream field set: `timezones`, `phone_code`, `currency`,
`emoji`, `population`, `postal_code_regex`, `latitude`/`longitude`, and
`also_subdivision_of` for territories ISO 3166 lists at two levels.

### Subdivisions

```ts
import { statesOf, rootStates, getState, stateTree, subdivisionTwin } from "geodata-js/states";

statesOf("GB", { depth: 1 });          // top level only
statesOf("GB", { parent: "GB-SCT" });  // the 32 Scottish council areas
statesOf("ES", { type: "autonomous community" });

getState("GB", "GB-BIR");              // full ISO 3166-2 code
getState("GB", "BIR");                 // qualified with the country
getState("GB", { name: "Birmingham" });

stateTree("GB");                       // forest of { state, children }
subdivisionTwin("MQ");                 // Martinique as French subdivision FR-972
```

Lookups throw `Ambiguous` rather than guessing when a name matches twice — a
silently wrong subdivision ends up on a shipping label.

### Cities

```ts
import { citiesOf, getCity, searchCities } from "geodata-js/cities";

citiesOf("NG", { state: "NG-LA" });
searchCities("sao paulo", { country: "BR", limit: 10 });   // finds "São Paulo"
```

Search is accent- and case-insensitive through the same fold that produced the
stable keys, so `"koln"` finds `"Köln"`.

Cities attach to whichever subdivision upstream put them under, which in a
nested country is usually a leaf rather than the top level. To collect a whole
branch, walk `stateTree` and union the results.

### Languages and translations

```ts
import { getLanguage, languages } from "geodata-js";
import { localizedName, translationsOf } from "geodata-js/translations";

getLanguage("pt-BR");                        // -> { code: "pt", name: "Portuguese" }
localizedName(getCountry("DE"), "fr");       // "Allemagne"
localizedName(getCountry("DE"), "xx", "—");  // your fallback, never a wrong name
```

A language `code` **is** its identity, so it is the one value in this package
that is safe to store in a foreign key.

## Errors

`CountryNotFound`, `StateNotFound`, `CityNotFound`, `LanguageNotFound` (all
extend `NotFound`) and `Ambiguous`, all extending `GeodataError`. The `find*`
variants return `undefined` instead.

## Provenance

Built from [`dr5hn/countries-states-cities-database`][upstream] pinned to tag
`v3.2-export.7`, verified by sha256, and put through a nine-check validation
gate — zero orphan foreign keys, no duplicate stable keys, no subdivision
cycles, every translation locale resolving to a real ISO 639 language. The
build is deterministic: CI rebuilds from the pinned tag and fails if the output
differs from what is committed.

`VERSION` (this package) and `DATASET_VERSION` (the data) are separate and both
exported. The Python SDK reports the same `DATASET_VERSION`.

## Licence

Code MIT. **Data ODbL-1.0**, inherited from upstream — redistributing it, or a
derived database, carries share-alike and attribution obligations. See
[`LICENSE`](./LICENSE) and [`LICENSE-DATA`](./LICENSE-DATA).

[upstream]: https://github.com/dr5hn/countries-states-cities-database
