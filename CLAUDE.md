# geodata — working notes

## What this is

A versioned, validated geographic reference dataset (250 countries / 5,308
subdivisions / 152,970 cities / 420 ISO 639 languages) plus a Python query API
and an optional Django app. Built from `dr5hn/countries-states-cities-database`, pinned by release tag.

This repo used to be three raw JSON files copied from a CDN mirror. That data
had orphan foreign keys, was missing 846 subdivisions and 8,582 cities, and
carried facts that were years stale. See `plans/geodata-data-remediation.md`
for the audit and `CHANGELOG.md` for what changed.

## Two invariants — do not break these

1. **`id` is not stable.** Upstream renumbers between releases (351 state ids,
   6,321 city ids in one version bump). Identity is `stable_key` / `iso2` /
   `iso3166_2`. Never write code that persists or hard-codes a geodata `id`.
2. **A referenced row is never deleted.** During a consumer migration, rows
   upstream dropped are deactivated (`is_active=False`) with `superseded_by`
   set. Deleting them corrupts application history irreversibly.

## Pipeline

```bash
make refresh    # fetch pinned tag -> build canonical -> validate
make check      # validate + tests (what CI runs)
make release VERSION=YYYY.MM
```

| script | role |
|---|---|
| `scripts/fetch.py` | download the pinned upstream tag, verify sha256, write `data/SOURCE.lock` |
| `scripts/build_canonical.py` | upstream JSON → `data/canonical/*.ndjson`, applies overrides |
| `scripts/validate.py` | the nine-check gate; exit 1 blocks the build |
| `scripts/churn.py` | diff two versions by stable key → `artifacts/CHURN.md` + remap table |
| `scripts/release.py` | snapshot + baseline for the next diff |

The build is **deterministic** — CI rebuilds from the pinned tag and fails if
the output differs from what is committed. Don't hand-edit `data/canonical/`.

## Where things go

- **Upstream is wrong about a value** → `data/overrides/*.patch.ndjson`, with a
  `_reason`, a `_source` URL and a `_review` date. Enforced by the loader.
- **Upstream documents a relationship in prose but not in data** →
  `data/curated/`.
- **Input that is not part of the upstream export** (the ISO 639 language
  list) → `data/vendor/`, committed and reviewed, never fetched at build time.
- **A systematic ingest rule** (null sentinels, Null-Island coordinates) →
  `scripts/build_canonical.py`, counted and reported, never silent.

## Conventions

- Python 3.9-compatible (no `X | None` at runtime, `.format()` over f-strings
  in library code).
- NDJSON everywhere: one object per line, sorted keys, minified separators.
- Comments explain *why*, especially where the code contradicts an obvious
  assumption — e.g. `level` is advisory and `depth` is authoritative because
  upstream's `level` disagrees with the tree for ~1,000 states.
- `scripts/lib/normalize.py` and `src/geodata/normalize.py` must stay
  byte-identical; a test enforces it. The build computes stable keys with one
  and the API matches with the other. `packages/js/src/normalize.ts` is a third
  implementation that cannot be byte-identical, so it is pinned by fixture
  instead — see the npm section below.

## Testing

```bash
python3 -m pytest tests/ -q      # 430 tests
cd packages/js && npm test       # 437 tests
```

- `test_normalize.py` — the fold, plus the drift guard
- `test_dataset_integrity.py` — structural invariants
- `test_data_regressions.py` — one test per audit finding; several assert the
  *old* snapshot was wrong, so a pass proves the fix rather than restating
  upstream
- `test_api.py` — query surface, incl. that importing the package does not load
  the 41 MB cities table, and that every translation locale resolves to a
  language
- `test_migrate.py` — the planner, and a Django round-trip
- `test_conformance.py` — the Python half of the shared corpus in
  `tests/conformance/cases.json`, whose expectations are generated from
  `data/canonical` rather than from either SDK, so neither language is the
  oracle. `packages/js/test/conformance.test.ts` runs the identical file.

## The npm package

`packages/js` is `geodata-js`. Everything under `src/{data,country,generated}`
is **generated** by `scripts/build_js.py` from `data/canonical` and is
gitignored — never hand-edit it, and re-run the generator after a refresh.

```bash
make js            # generate -> typecheck -> build -> test -> lint -> smoke
make js-publish-dry
```

Three things about its shape are load-bearing, not stylistic:

1. **The exports map is the design.** The root entry is countries + languages
   (55 KB gz) and *cannot reach* the cities table — `test/exports.test.ts`
   asserts that against the real esbuild module graph, because no behavioural
   test would notice a client bundle silently growing by 4.7 MB.
2. **Reachability, not eagerness, decides what a bundler emits.** A bundler
   emits a chunk file for every `import()` it can see, used or not. When all
   three chunk maps lived in one statically imported module, a Next.js client
   component that only built a *state* dropdown still emitted 48 MB of city
   chunks. That is why city loading lives behind `geodata-js/lazy` rather than
   merely being tree-shakeable.
3. **`make js` is the real gate, not `npm test`.** It also runs publint,
   `arethetypeswrong` across all four consumer resolution modes, and
   `scripts/smoke.sh`, which installs the packed tarball into a clean directory
   and imports it. That last one is the only check that exercises the
   *published artifact* — the suite runs against `src/`, where the exports map,
   the `files` allowlist and the ignore rules are all bypassed. Those are
   exactly the things that fail silently: an earlier tarball here contained two
   licences and no code.
4. **`src/normalize.ts` must reproduce `scripts/lib/normalize.py` exactly.** It
   is half of every stable key. The Unicode tables it needs are generated from
   the same CPython that computed every `normalized_name`, and a test re-folds
   all 158,976 dataset names through the TypeScript implementation.

Two declaration trees ship: `dist/types` (`.d.ts`, for `import`) and
`dist/types-cjs` (`.d.cts`, for `require`), with relative specifiers rewritten
`.js` → `.cjs`. TypeScript picks a declaration's module system from its
extension, so one tree serving both conditions gives `require()` consumers ESM
types that only work under a dynamic import.

## Still to do

- The rest of the multi-stack packaging in
  `plans/geodata-multi-stack-library.md`: the **PyPI wheel** and the **SQLite
  artifact**. The npm package is done; `src/geodata/` still has no
  `pyproject.toml` and its data is loaded from the repo, not from a wheel.
- `seed_geography.py` at the repo root is the *old* vendored command, kept for
  reference until the Django seeding path replaces it.
- The three root JSON files are the pre-remediation snapshot. Several
  regression tests diff against them to prove the old data was wrong; they skip
  cleanly once the files are removed. Deleting them saves 35 MB.
