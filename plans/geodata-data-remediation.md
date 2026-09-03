# geodata — data remediation plan

**Scope:** fix every data problem found in the audit of `countries.json` / `states.json` / `cities.json`, and change the library plan where the audit invalidated its assumptions. This plan is about *data correctness*; `plans/geodata-multi-stack-library.md` remains the plan for *distribution*. This one must land first — the packaging plan currently ships known-bad data.

---

## The issues, and what fixes each

| # | Issue (from audit) | Severity | Fix |
|---|---|---|---|
| 1 | Source is `react-country-state-city`, a weekly mirror of dr5hn that never picked up v3.2 | root cause | Re-point ingestion at `dr5hn/countries-states-cities-database`, pinned to a release tag |
| 2 | 846 states missing (GB 168, EE 79, PR 68, BD 64, IS 64 …) | high | Falls out of #1 |
| 3 | 8,582 cities missing (CN 2,882, UY 1,859, FR 1,763 …); 29 countries have zero cities but shouldn't | high | Falls out of #1 |
| 4 | 27 stale country facts: Swaziland, Macedonia, Kiev, HRK/BGN→EUR, MRO/STD/VEF→MRU/STN/VES, CG currency, MX subregion | high | Falls out of #1 |
| 5 | 3,751 cities point at state ids 2335/2336/2338 (England/Scotland/Wales) that don't exist in `states.json` — orphan FKs | **blocker** | Fixed by #1 + keep `level`/`parent_id`; enforced by a zero-orphan validation gate |
| 6 | Dropped fields: `type`, `level`, `parent_id`, `iso3166_2`, `timezone`, `translations`, `native`, population/area, postal formats, `wikiDataId` | high | Canonical schema carries the full upstream field set |
| 7 | Only 501/4,813 states have lat/lng | medium | Accept as upstream reality — make coords `Optional`, never assume present |
| 8 | IDs are **not stable**: 351 state ids and 6,321 city ids vanish upstream; 2,015 states renamed/re-parented; 8,727 FR cities re-parented (v3.2 breaking change) | **blocker for adopters** | Stable-key strategy + generated remap table + `geodata migrate` |
| 9 | US has 19,819 local vs 16,731 upstream — a *correction* that looks like data loss | medium | Churn report on every refresh, reviewed by a human before release |
| 10 | `phone_code` (local) vs `phonecode` (upstream) naming | low | Canonical name `phone_code`; documented alias |
| 11 | Nested `[{id, states:[{id, cities:[…]}]}]` shape forces tree-walking | medium | Flat NDJSON canonical (already in the library plan); nested emitted as a compat artifact |

Issues 5 and 8 are the two that must be *designed for*, not just re-downloaded. Everything else is downstream of switching source.

---

## Decision 1 — source of truth

**Ingest from `dr5hn/countries-states-cities-database`, pinned to an explicit release tag** (currently `v3.2-export.7`, 29 Jul 2026), not `master`, not the mirror.

- Pin, don't track `master`: dr5hn force-pushes export artifacts; a floating ref makes builds irreproducible.
- Record the tag **and the sha256 of each downloaded file** in `data/SOURCE.lock`. A refresh that produces a different hash for the same tag is a supply-chain signal and fails the build.
- Keep the mirror comparison as a *test*, not a source — it's a useful second opinion on regressions.

Caveat carried forward from the audit: dr5hn is community-maintained and self-describes as possibly lagging geopolitical changes. It is the best free source, not an authority. Where we know better (see Decision 4) we override it in-repo rather than forking upstream.

## Decision 2 — join keys, because ids churn

The library plan asserted "stable ids — refresh never renumbers." **That is false** and must be struck from it.

New rule, in priority order:

| Entity | Primary stable key | Fallback |
|---|---|---|
| Country | `iso2` (ISO 3166-1 alpha-2) | `iso3`, `numeric_code` |
| State | `(country_iso2, iso3166_2)` | `(country_iso2, state_code)`, then `(country_iso2, normalized_name)` |
| City | `(country_iso2, state_key, normalized_name)` + lat/lng within ~1 km | upstream `id` |

`geodata_id` (the upstream integer) is still carried and still exposed — it's what existing FKs hold — but it is **not** the identity. Consumers are told, in the README and in the migration guide, to key their own FKs on the stable key.

`normalized_name` = NFKD → strip combining marks → casefold → collapse whitespace/punctuation. Deterministic, implemented once in `scripts/lib/normalize.py`, and shared with the JS build via a conformance fixture so both languages normalize identically.

## Decision 3 — multi-level territories are first-class

The England/Scotland/Wales orphan bug (issue 5) exists precisely because the mirror flattened away `level`/`parent_id`. So:

- Canonical `states.ndjson` carries `type`, `level`, `parent_id`, `iso3166_2`, `native`, `timezone`.
- A state may have a `parent_id` pointing at another state (GB: `England` level 1 → `Birmingham` level 2).
- Validation asserts: every `parent_id` resolves; no cycles; `level` is consistent with parent depth.
- The API exposes both a flat list and a tree (`states_of("GB", level=1)` → 4 constituent countries; `level=None` → all 221).

Territories that are *both* a country and another country's subdivision (Martinique, Puerto Rico, Hong Kong) get an explicit `also_subdivision_of` link rather than being silently duplicated.

## Decision 4 — an overrides layer

Some corrections shouldn't wait on upstream, and some upstream choices are wrong for us. Add `data/overrides/*.ndjson` — a small, hand-maintained, **reviewed** patch set applied after ingest and before validation.

```
data/overrides/
├── countries.patch.ndjson    {"iso2":"XK","name":"Kosovo","_reason":"...","_review":"2026-09-03"}
├── states.patch.ndjson
└── cities.patch.ndjson
```

Rules: every entry needs `_reason` and a source URL; the file is tiny by design; CI reports any override that upstream has since adopted so it can be retired. This is the escape hatch that stops us from forking 35 MB.

## Decision 5 — the validation gate

`scripts/validate.py` is a hard CI gate. It fails the build on:

1. **Zero orphan FKs** — every `state.country_id` and `city.state_id`/`city.country_id` resolves. *The current dataset fails this today (3,751 cities). That is the correct outcome.*
2. Schema conformance against `schema/*.schema.json`.
3. Uniqueness: `iso2`, `iso3`, `numeric_code`; `(country_iso2, iso3166_2)` where present; no duplicate ids within an entity.
4. Coordinate sanity: lat ∈ [-90,90], lng ∈ [-180,180], not (0,0) unless genuinely Null Island; flag cities >500 km outside their country bbox.
5. `parent_id` resolves, no cycles, `level` consistent.
6. Counts within tolerance of the previous release (see churn budget below).
7. Encoding: valid UTF-8, no mojibake (`Ã©`, `â€™`), no leading/trailing whitespace, no HTML entities.
8. `hasStates`/`hasCities` flags agree with the actual relations.

## Decision 6 — churn budget + report

Every refresh emits `artifacts/CHURN.md`:

- added / removed / renamed / re-parented, per entity, with per-country breakdown
- the full remap table `data/remap/<from>-<to>.ndjson`: `{entity, old_id, new_id|null, stable_key, reason}`
- top-20 largest per-country deltas, so a US -3,000 (issue 9) is *seen* before release

Thresholds: >2% net removal in any entity, or >10% in any single country, requires an explicit `--accept-churn` flag with a written justification recorded in the CHANGELOG. Refuses to build otherwise. This is what turns "silent corruption on upgrade" into a reviewed decision.

## Decision 7 — migration path for already-seeded apps

For consumers who already have these ids in FK columns (issue 8), a straight re-seed is data corruption. Ship:

- `python manage.py geodata_migrate --from 2026.05 --to 2026.09 [--dry-run]`
  - resolves every local row via stable key → new id
  - reports: matched, re-parented, removed-with-references, ambiguous
  - **never deletes a referenced row** — marks it `is_active=False`, `superseded_by=<new_id>`, so historical records keep resolving
  - writes an operator report; `--dry-run` is the default in the first release
- Models gain `is_active`, `superseded_by`, and the stable-key columns, with indexes.
- The FR region→INSEE-department re-parenting (8,727 cities) gets a documented worked example in the migration guide, since it's the largest single break.

---

## Ordered execution

**Phase A — ingest from the real source** *(unblocks everything)*
1. `scripts/lib/normalize.py` — shared normalization, unit-tested.
2. `scripts/refresh.py` — download pinned dr5hn tag, verify sha256, write `data/SOURCE.lock`.
3. Map upstream → canonical: full field set (issue 6), `phonecode`→`phone_code` (issue 10), flat NDJSON with explicit FKs (issue 11).
4. Apply `data/overrides/` (Decision 4).
5. Commit `data/canonical/*.ndjson` + `SOURCE.lock`.

**Phase B — prove it's clean**
6. `schema/*.schema.json` covering the full field set, incl. `type`/`level`/`parent_id`/`iso3166_2`/`timezone`, coords `Optional` (issue 7).
7. `scripts/validate.py` — all 8 checks from Decision 5.
8. Run it. Expect: orphan FKs = 0 (issue 5 resolved), counts ≈ 250 / 5,308 / 152,970.
9. `tests/test_dataset_integrity.py` — pin the checks so a future refresh can't regress.
10. **Regression test against the old data**: assert Eswatini, North Macedonia, Kyiv, HR/BG=EUR, MRU/STN/VES, CG=CDF, MX=Northern America; assert GB has 221 subdivisions incl. Birmingham/Bradford/Bristol/Aberdeen; assert CN ≈ 4,133 cities; assert PS/PR/XK/HK/GL are non-empty. One explicit test per issue-4 and issue-2/3 finding.

**Phase C — churn tooling**
11. `scripts/churn.py` — diff old snapshot vs new canonical via stable keys → `CHURN.md` + remap table.
12. Run old→new. Review the report by hand. This is the first place the US -3,000 (issue 9) and the FR re-parenting show up as a reviewed decision rather than a surprise.
13. Wire the churn budget into CI (Decision 6).

**Phase D — schema/API consequences**
14. Multi-level territory support in the core API: `states_of(country, level=…)`, `state_tree(country)`, `also_subdivision_of` (Decision 3).
15. Stable-key lookups in the public API: `get_state("GB", iso3166_2="GB-BIR")`.
16. Update `plans/geodata-multi-stack-library.md`: **strike the "stable ids" guarantee**, add the overrides layer, add `type`/`level`/`parent_id`/`iso3166_2`/`timezone` to the canonical schema, add the zero-orphan gate, add `geodata migrate` to the Django command list.

**Phase E — migration**
17. Model fields `is_active` / `superseded_by` / stable-key columns + migration.
18. `geodata_migrate` command (Decision 7), `--dry-run` default.
19. `tests/test_migrate.py`: seed old snapshot → migrate → assert no referenced row is deleted, FR cities re-parent correctly, removed-with-references are deactivated not dropped.
20. `docs/MIGRATION.md` with the FR worked example.

**Phase F — keep it fresh**
21. Scheduled CI job: check for a new dr5hn release tag → open a PR containing the new canonical data + `CHURN.md`. Never auto-merge. A human reads the churn report.
22. Release checklist: validate → churn review → bump `VERSION` → build artifacts → publish.

Phases A–B are the ones that make the current data usable at all. C–F are what stop this from rotting again.

---

## What this changes in the library plan

Four edits to `plans/geodata-multi-stack-library.md`:

1. **Delete** the "Stable ids — refresh never renumbers" guarantee. Replace with the stable-key strategy (Decision 2) + remap table. This was factually wrong.
2. Source becomes dr5hn pinned-by-tag, not the react-country-state-city CDN.
3. Canonical schema grows: `type`, `level`, `parent_id`, `iso3166_2`, `timezone`, `native`, `translations`, population/area, postal format/regex, `wikiDataId`. Note the size impact — `translations` alone is significant; it goes in a **separate optional artifact** (`translations.json.gz`, npm subpath `@yourorg/geodata/translations`) rather than the base payload, to protect the ~92 KB gz countries+states entry point that the Next.js design depends on.
4. Add `geodata migrate` alongside `seed_geography`, and the `is_active`/`superseded_by` model fields.

## Open questions

1. **Do any of your apps already have these ids in FK columns?** If yes, Phase E is mandatory and must ship in v1. If every app is greenfield, Phase E can slip to v1.1 and Phases A–D are the whole job.
2. **Accept the US -3,000 correction?** It's upstream deduplication and I believe it's right, but it will delete rows some app may reference. Confirm, or I gate it behind an override.
3. **Do you need `translations`?** It's the single biggest optional payload. Separate artifact either way, but it changes whether Phase A carries it at all.
4. **How current must this be?** Phase F's scheduled check is cheap; if a yearly manual refresh is enough, skip the automation.
5. Still outstanding from the previous plan: publishing target (public vs private registries) and the org/scope name.
