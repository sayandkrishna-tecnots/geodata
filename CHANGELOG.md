# Changelog

Two versions are tracked separately and both matter:

- **Dataset version** (`2026.09`) — this repository's release.
- **Upstream tag** (`v3.2-export.7`) — the pinned
  [dr5hn](https://github.com/dr5hn/countries-states-cities-database) release it
  was built from, recorded in `data/SOURCE.lock`.

## Unreleased

### Added

- **Language table** — `data/canonical/languages.ndjson`, 420 ISO 639 rows
  (184 two-letter 639-1 codes, 236 three-letter 639-2 codes) built from the
  committed `data/vendor/languages.json`. This is the first table that does not
  come from the upstream export; `data/vendor/` is where such inputs live, and
  they are never fetched at build time so the build stays reproducible offline.
- Language codes are their own identity: `stable_key == code`, so unlike every
  other table in this dataset a language code **is** safe to persist in a
  foreign key. Invariant 1 does not apply to it.
- API: `languages()`, `get_language()` / `find_language()` — which accept a
  BCP-47 tag and match on the primary subtag, so `pt-BR` resolves to
  Portuguese — plus `translations_of()` and `localized_name()`, which give the
  previously unreachable `translations.*.ndjson` artifacts a query surface.
  `localized_name` falls back from a regional tag to its base language and
  returns the caller's default rather than a wrong name.
- Validation **check 9**: every locale key in the translation artifacts must
  resolve to a language row. Until now those artifacts shipped BCP-47 keys with
  nothing in the repo defining them; an unknown locale is now a build failure.
  Measured at this tag: 28 distinct locales, all resolving, all keyed on
  two-letter codes.
- `data/RELEASE.json` records the language count.

## 2026.09 — upstream `v3.2-export.7`

First release after the data remediation. Everything below fixes a defect
found in the audit of the previous snapshot; see
`plans/geodata-data-remediation.md`.

### Source

- **Ingest moved from the `react-country-state-city` CDN mirror to dr5hn
  directly**, pinned to release tag `v3.2-export.7` with per-file sha256 in
  `data/SOURCE.lock`. The mirror was a weekly re-export that never picked up
  upstream v3.2, and its minification dropped a third of the field set. Every
  fix below follows from this one change.

### Fixed — blockers

- **Orphan foreign keys eliminated.** 3,751 cities referenced state ids
  2335/2336/2338 (England, Scotland, Wales) that did not exist in the previous
  `states.json`. The mirror had flattened away `level`/`parent_id`, dropping
  the three constituent countries while keeping the cities beneath them. Those
  states now exist and every foreign key resolves; a zero-orphan check is a
  hard CI gate.
- **`id` is no longer treated as stable.** 351 state ids and 6,321 city ids
  changed meaning between the two versions, and v3.2 re-parented 8,727 French
  cities from ISO-3166-2 regions to INSEE departments. Every record now carries
  a `stable_key`, refreshes emit a remap table, and `geodata_migrate` applies
  it without deleting referenced rows. The previous plan's "stable ids"
  guarantee was factually wrong and has been struck.

### Fixed — data

- **+846 subdivisions** (5,308, was 4,813). The UK goes from 74 to 221,
  recovering Birmingham, Bradford, Bristol, all 32 Scottish council areas and
  every English district — the previous data could not back a UK address form.
- **+8,582 cities net** (152,970, was 150,709). China +2,837 (the mirror was
  missing 69%), France +1,763 via the INSEE commune import, Uruguay +1,859.
- **29 countries that had no cities now do**, including Palestine (132),
  Puerto Rico (78), Kosovo (59), Hong Kong (27) and Greenland (18).
- **27 stale country facts corrected**: Swaziland → Eswatini, Macedonia →
  North Macedonia, Kiev → Kyiv, Croatia and Bulgaria to EUR, MRO/STD/VEF →
  MRU/STN/VES, Congo to CDF, Mexico to Northern America, plus name-casing
  fixes.

### Added

- **The full upstream field set**, which the mirror had minified away:
  countries gain `timezones`, `nationality`, `population`, `area_sq_km`,
  postal format/regex, `region_id`, `subregion_id`, `emoji_unicode` and
  `wikidata_id`; states gain `iso3166_2`, `fips_code`, `type`, `level`,
  `parent_id`, `native`, `timezone`, `population` and `wikidata_id`; cities
  gain `timezone`.
- **Multi-level territories are first-class.** The 21 territories ISO 3166
  lists both as countries and as subdivisions of another country (Martinique,
  Puerto Rico, Hong Kong, …) carry an `also_subdivision_of` link, transcribed
  from upstream's policy document and validated against the data at build time.
- **`depth`**, computed from the parent chain. Upstream's `level` is a semantic
  administrative level that disagrees with the tree for ~1,000 states, so it is
  carried as advisory and `depth` is authoritative.
- **`translations` as a separate artifact**, so the base payload stays small
  enough for the npm entry point.
- **An overrides layer** (`data/overrides/`), each entry requiring a reason, a
  source URL and a review date.
- **A churn report and remap table** on every refresh, with a budget that
  blocks a release exceeding it.
- **A query API** with stable-key lookups, subdivision trees, and lazy city
  loading — importing the package does not read the 41 MB cities table.

### Local corrections (`data/overrides/`)

- **Three Spanish self-referencing states.** Asturias, Cantabria and La Rioja
  had `parent_id` pointing at their own id, creating cycles. They are
  uniprovincial autonomous communities with no parent subdivision.
- **City of London re-parented to England.** Upstream parents `GB-LND` to
  Scotland. Found by a test asserting Scotland has exactly 32 council areas.
- **Nine geocoder name collisions.** Copenhagen (DK) sat at 43.89,-75.67 —
  Copenhagen, New York, 5,825 km away. Eight Puerto Rican municipalities
  pointed at same-named places elsewhere: Barceloneta at Barcelona (Spain),
  Salinas at Salinas (California), San Sebastián at San Sebastián (Spain).

### Ingest hygiene

- Coordinates of exactly `(0, 0)` are treated as upstream's "unknown"
  placeholder and nulled — 22 Chinese cities and one country were otherwise
  located in the Gulf of Guinea. Reported by the build, not silent.
- The literal string `"NULL"` is mapped to a real null.
- `phonecode` renamed to `phone_code`.
- Names are NFC-normalised; the comparison key folds Latin diacritics but
  preserves Cyrillic combining marks, which are distinct letters rather than
  decorations.

### Churn accepted for this release

The budget (2% net removal per entity, 10% per country) was exceeded and
signed off on 2026-09-03. Full justification in `data/CHURN_ACCEPTED.json` and
`artifacts/CHURN.md`. Summary: every removal is an upstream reclassification of
rows that were never cities —

- **US −3,104**: county rows ("Autauga County") moved out of the cities table.
- **TH −645**: *amphoe* (districts). **ID −424**: *kabupaten* (regencies).
- **TR −510**: *ilçe* (districts) and duplicated province names.
- **PL −315**: *powiat* (counties). **RO −107**: *comuna* / *oraș* units.
- **states −432**: real administrative reforms — North Macedonia (83), Latvia's
  2021 municipal reform (78), Albania (34), Vietnam's province mergers (29),
  Greece's Kallikratis regional units (25).

Net effect is +495 subdivisions and +2,261 cities.

### Breaking changes for consumers

Anyone holding these ids in a foreign key must run `geodata_migrate` rather
than re-seeding. See `docs/MIGRATION.md`, which works through the France
re-parenting and the US county removal in detail.
