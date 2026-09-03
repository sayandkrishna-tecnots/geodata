# geodata — one dataset, every stack

**Goal:** turn this repo into a versioned, multi-language distribution of the country/state/city dataset, consumable from Node, TypeScript, Next.js (server + client + edge), Python/Django, and any other stack — without copy-pasting 35 MB of JSON into each app.

## Core principle

**One canonical dataset → many generated artifacts → one shared version number.**

Nothing is hand-written per language except the thin idiomatic API surface. The data, the schema, and the types are *generated* from a single source by a single build, so a Node app and a Django app can never disagree about what "NG" means.

```
data/canonical/*.ndjson  ──┐
schema/*.schema.json     ──┼─► scripts/build/  ─┬─► packages/js      → npm  @yourorg/geodata
                           │                    ├─► packages/python  → PyPI  yourorg-geodata
                           │                    ├─► artifacts/geodata.sqlite   (any language)
                           │                    └─► artifacts/*.json.gz + CDN  (any language)
                           └─► VERSION (dataset), shared by all artifacts
```

## Distribution tiers

Not every stack needs a hand-written SDK. Three tiers, in order of effort:

| Tier | What ships | Serves |
|---|---|---|
| **1. First-class SDKs** | npm package (TS), PyPI package | Node, TS, Next.js, React Native, Django, FastAPI, Flask, scripts |
| **2. Universal artifacts** | `geodata.sqlite` (single file, indexed) + `countries/states/cities.json.gz` published to CDN + a JSON Schema | Go, Ruby, PHP, Java, Rust, Elixir, mobile, data pipelines, DB seeding in *any* ORM |
| **3. Optional service** | Docker image exposing a read-only REST/JSON API over the SQLite artifact | Stacks where you'd rather not embed 3 MB; browser autocomplete at scale |

Tier 2 is what actually makes this "all stacks" — a 5 MB indexed SQLite file plus a documented schema means a Go service does `SELECT * FROM cities WHERE state_id = ?` with no SDK at all. Tier 3 is a thin wrapper you can add later, built from the same artifact.

## Repo layout (monorepo)

```
country-json/                        → renamed conceptually to "geodata"
├── VERSION                          dataset version, e.g. 2026.09.1
├── data/canonical/
│   ├── countries.ndjson             250     + phone_code, timezones, nationality, population,
│   │                                        area_sq_km, postal format/regex, region_id,
│   │                                        subregion_id, emoji_unicode, wikidata_id,
│   │                                        stable_key, also_subdivision_of
│   ├── states.ndjson                5,308   {id, country_id, country_iso2, iso3166_2, fips_code,
│   │                                        type, level, parent_id, depth, timezone, native,
│   │                                        wikidata_id, stable_key}
│   ├── cities.ndjson                152,970 {id, state_id, country_id, country_iso2, timezone,
│   │                                        stable_key}
│   ├── regions.ndjson               6
│   └── subregions.ndjson            22
├── data/canonical/translations.*.ndjson    separate artifact — never in the base payload
├── data/SOURCE.lock                 upstream repo + tag + per-file sha256
├── data/RELEASE.json                last released counts, the churn baseline
├── data/overrides/*.patch.ndjson    reviewed local corrections (_reason/_source/_review)
├── data/curated/                    relationships upstream documents in prose, not data
├── data/snapshots/<version>/        gzipped previous releases, so churn has a diff base
├── data/remap/<from>-<to>.ndjson    id remap table for already-seeded consumers
├── schema/
│   ├── country.schema.json          JSON Schema — the contract
│   ├── state.schema.json
│   └── city.schema.json
├── scripts/
│   ├── refresh.py                   CDN/source → normalize → canonical ndjson
│   ├── validate.py                  schema + referential integrity + counts (CI gate)
│   └── build/
│       ├── build_sqlite.py          canonical → artifacts/geodata.sqlite (+ FTS5 on names)
│       ├── build_json.py            canonical → artifacts/*.json.gz (+ per-country splits)
│       ├── build_js.ts              canonical → packages/js/data + generated types
│       └── build_python.py          canonical → packages/python/.../data + generated types
├── packages/
│   ├── js/                          @yourorg/geodata          (see below)
│   └── python/                      yourorg-geodata           (see below)
├── artifacts/                       build output, gitignored, uploaded on release
└── .github/workflows/release.yml    one tag → npm + PyPI + SQLite/JSON release assets
```

Note the canonical format change: the current `states.json`/`cities.json` are **nested** (`[{id: country, states:[{id, cities:[...]}]}]`), which forces every consumer to walk the tree just to find one city. Canonical becomes **flat NDJSON with explicit foreign keys** — trivially streamable, diffable in git, and a 1:1 map to SQL tables. The nested shape is still *emitted* as a compatibility artifact for anything already consuming it.

## packages/js — `@yourorg/geodata`

```
packages/js/
├── package.json          exports map, sideEffects:false, files:[dist]
├── tsconfig.json         → ESM + CJS + .d.ts (tsup)
├── src/
│   ├── index.ts          countries + states (small, always safe to import)
│   ├── cities.ts         subpath: heavy, opt-in
│   ├── country/<iso2>.ts generated per-country entry points
│   ├── types.ts          GENERATED from schema/*.schema.json
│   └── search.ts         normalized/deburred name search
└── data/                 generated JSON, imported statically
```

Exports map — the single most important design decision for Next.js:

```jsonc
"exports": {
  ".":              "./dist/index.js",        // ~17 KB gz: countries + states
  "./cities":       "./dist/cities.js",       // ~2.9 MB gz: server-only
  "./country/*":    "./dist/country/*.js",    // per-country: NG alone is ~40 KB
  "./sqlite":       "./dist/sqlite-path.js",  // resolves the .sqlite for node
  "./package.json": "./package.json"
}
```

API:

```ts
import { getCountry, countries, statesOf } from '@yourorg/geodata'
import { citiesOf, searchCities } from '@yourorg/geodata/cities'   // server only
import { cities as ngCities } from '@yourorg/geodata/country/NG'   // client-safe subset

getCountry('NG')                       // by iso2 | iso3 | numeric | name
countries({ region: 'Africa' })
statesOf('NG')
citiesOf('NG', 'LA')
searchCities('lagos', { limit: 10 })
```

Everything is a pure function over frozen data — no classes, no init, fully tree-shakeable, zero runtime deps, works in Node, Bun, Deno, Vite, webpack, React Native (Metro honors `exports`).

**Next.js specifics** (this is where a naive package breaks):
- Importing all cities into a client component would ship 13 MB of JS. Prevented structurally by the subpath split, and by a `"use server"`-free but **server-only guard** on `/cities` (throws a clear error if bundled for the browser).
- A `withGeodata()` helper / documented recipe for `next.config.js` `serverExternalPackages` so the cities blob isn't traced into every lambda.
- A ready-made **Route Handler** (`createGeoHandler()`) you can drop at `app/api/geo/[[...path]]/route.ts` to expose search to client components — the correct pattern for city autocomplete.
- Works in **Edge runtime** for countries/states (no `fs`, plain JSON imports); cities on edge is documented as unsupported → use the route handler or Tier 3 service.
- RSC-first: countries/states can be read directly in a Server Component with no client JS at all.

## packages/python — `yourorg-geodata`

Unchanged in spirit from the previous plan, now fed by the shared build:

- `geodata/` — pure Python, zero Django: `get_country`, `countries`, `states_of`, `cities_of`, `search_cities`, frozen dataclasses, lazy memoized gzip load, `py.typed`.
- `geodata/contrib/django/` — abstract + concrete models, migrations, admin, optional DRF viewsets, and the rewritten `seed_geography` command.
- The current `seed_geography.py` is not reusable as-is and gets rewritten: hard-coded `geography.models` import → swappable models via app registry; `PRESERVED_COUNTRIES = {AE,IN,NG,US}` → `GEODATA` setting; CDN download at runtime → data in the wheel; per-country chunked transactions + `--resume` instead of one 150k-row atomic block; drop the full-table refetch after each `bulk_create`; DB-level unique constraints; stop silently truncating `state_code[:10]`; keep lat/lng, phone_code, emoji, currency, region (currently discarded).
- Consumers with existing `Country`/`State`/`City` tables subclass `AbstractCountry` and point `GEODATA["MODELS"]` at their own models — without this, adoption stalls in any app that already has geography tables.
- A second management command, **`geodata_migrate`**, ships alongside `seed_geography`. Because ids churn, a straight re-seed corrupts any app that already has these ids in FK columns. `geodata_migrate` resolves each local row through the remap table by stable key, and **never deletes a referenced row** — it marks it `is_active=False` with `superseded_by=<new_id>`, so historical records keep resolving. `--dry-run` is the default in the first release.
- Models therefore carry `stable_key`, `is_active` and `superseded_by` (indexed) in addition to the upstream `id`.
- Subdivisions are a **forest, not a list**: models expose `parent`/`depth`, and the API `states_of(country, depth=1)` vs `states_of(country)` — 4 vs 221 for the UK. A cascading selector wants the first.

## Cross-language guarantees (what makes this trustworthy)

1. **One version.** `VERSION` (dataset) is baked into every artifact; npm and PyPI releases carry the same `datasetVersion` / `DATASET_VERSION` and it's asserted in CI. Package code version and dataset version are both recorded in the CHANGELOG.
2. **One schema.** `schema/*.schema.json` is the contract; TS types and Python dataclasses are both generated from it, so field drift is impossible.
3. **One conformance suite.** `tests/conformance/cases.json` — a shared list of ~100 query/expected-result pairs. The JS suite and the Python suite both run it. If `getCountry('NG')` differs between languages, CI fails.
4. ~~**Stable ids.** `refresh.py` never renumbers; a removed entity leaves a hole. Downstream FKs stay valid across dataset upgrades.~~ **Struck — this was factually wrong.** Measured against upstream, 351 state ids and 6,321 city ids change meaning between two consecutive releases, and v3.2 re-parented 8,727 French cities. Replaced by **stable keys**: `iso2` for countries, `(country_iso2, iso3166_2)` for states, `(country, state, normalized_name)` + coordinates for cities. The upstream integer id is still carried and exposed — it is what existing FKs hold — but it is not the identity, and the README tells consumers not to persist it. Every refresh emits a remap table (`data/remap/<from>-<to>.ndjson`) and `geodata_migrate` applies it. See `plans/geodata-data-remediation.md`, Decision 2.
5. **Validation gate.** Eight checks, orphan foreign keys first: every state resolves to a country, every city to a state *and* to a state in the same country; schema conformance; `iso2`/`iso3`/`numeric_code`/`(country, iso3166_2)`/stable-key uniqueness; coordinate range, Null-Island rejection and country-bbox outlier reporting; `parent_id` resolves and is acyclic; counts within the churn budget; encoding hygiene; derived flags agree with the relations. Counts are **250 / 5,308 / 152,970** — not the 250 / 4,813 / 150,709 in the mirror snapshot this plan was originally written against.
6. **Churn budget.** No release removes more than 2% of an entity, or more than 10% of a single country, without a written sign-off recorded in `data/CHURN_ACCEPTED.json` and surfaced in `artifacts/CHURN.md`. This is what turns the US −3,104 dedup from a surprise into a reviewed decision.
7. **Reproducible ingest.** Upstream is pinned by release tag with per-file sha256 in `data/SOURCE.lock`; CI rebuilds from the pinned tag and fails if the result differs from what is committed.

## Size budget (gzipped)

| Artifact | Size |
|---|---|
| countries | 17 KB |
| states | 75 KB → ~230 KB (the restored field set: iso3166_2, type, level, parent_id, timezone, native) |
| cities | 2.9 MB → ~3.4 MB (restored `timezone`) |
| translations (separate artifact, never in the base payload) | ~600 KB |
| npm main entry (countries+states) | ~92 KB |
| npm `/country/NG` | ~40 KB |
| SQLite (indexed, +FTS) | ~12 MB raw / ~5 MB gz |

Small enough to ship inside the wheel and the tarball — no CDN dependency at install or runtime, reproducible builds, no outage risk.

## Ordered implementation plan

**Phase 1 — canonical data + contract**
1. `schema/*.schema.json`; `VERSION`.
2. `scripts/fetch.py` + `scripts/build_canonical.py`: **dr5hn pinned by release tag** (never the react-country-state-city mirror, never `master`) → flat canonical NDJSON with explicit FKs, plus `data/overrides/` for reviewed local corrections. **Done** — see the remediation plan, Phases A–B.
3. `scripts/validate.py`: the eight-check gate above. **Done.**
4. Commit canonical NDJSON; retire the three root JSON files (kept as generated compat artifacts).

**Phase 2 — universal artifacts (Tier 2)**
5. `build_sqlite.py` → indexed `geodata.sqlite` with FTS5 on names.
6. `build_json.py` → `*.json.gz`, per-country splits, and the legacy nested shape.
7. `docs/artifacts.md` — how any language consumes these (Go/Ruby/PHP examples).

**Phase 3 — npm package**
8. Scaffold `packages/js` (tsup, ESM+CJS+d.ts, exports map, `sideEffects:false`).
9. `build_js.ts`: generate `data/`, `types.ts`, per-country entry points.
10. Implement `index.ts`, `cities.ts`, `search.ts`; server-only guard on cities.
11. Tests + bundle-size assertion (main entry must stay under budget).

**Phase 4 — Next.js integration**
12. `createGeoHandler()` route handler + `withGeodata()` config helper.
13. `examples/nextjs` — a country/state/city cascading selector using RSC for countries/states and the route handler for city search. This doubles as the integration test.
14. Verify: App Router, Pages Router, Edge runtime, RSC, client component.

**Phase 5 — Python package**
15. `packages/python` skeleton, `pyproject.toml` (extras `django` / `drf` / `dev`), `py.typed`.
16. `build_python.py` → data + generated dataclasses.
17. Pure-Python core (`loader`, `api`, `types`, `exceptions`) + lazy-cities test.
18. Django layer: abstract/concrete models, migrations, admin, managers.
19. Rewrite `seed_geography` with the 8 fixes + `--dry-run/--only/--skip-cities/--resume/--update-existing`; idempotency test.
20. Optional DRF serializers/viewsets/urls, import-guarded.

**Phase 6 — conformance + CI**
21. `tests/conformance/cases.json`; runners in both languages.
22. `release.yml`: one tag → validate → build all → run both suites + conformance → publish npm + PyPI → attach SQLite/JSON to the GitHub Release.
23. Matrix: Node 18/20/22 × Python 3.9–3.13 × Django 4.2/5.x.

**Phase 7 — adopt**
24. Django app that owns today's `seed_geography.py`: install, configure `GEODATA`, point `MODELS` at existing tables, `--dry-run`, diff row counts, cut over, delete 35 MB of vendored JSON.
25. Next.js app: replace any bundled country list with the npm package; verify client bundle shrinks.
26. README with a recipe per stack.

**Phase 8 — optional service (Tier 3)**
27. Dockerized read-only REST API over `geodata.sqlite` (FastAPI or Hono — pick to match your ops), same JSON shapes as the SDKs.

## Open questions

1. **Publishing target** — public npm/PyPI, or private (GitHub Packages / CodeArtifact / Gemfury)? GitHub Packages handles both registries with one token and is the low-friction choice if these are internal.
2. **Scope name** — `@yourorg/geodata`; the PyPI name `geodata` is taken, so `<yourorg>-geodata`. Tell me the org and I'll fix the names throughout.
3. **Existing tables** — do the Django apps already have populated `Country`/`State`/`City`? If yes, Phase 7 needs a per-app field-mapping step.
4. **Do you need Tier 3 now** or is embedding enough? Affects Phase 8 only.
5. **Any non-Node/non-Python stacks in play right now** (Go, Ruby, PHP, mobile-native)? If yes I'll add a worked example for it in Phase 2 step 7 rather than leaving it to docs.
