# geodata

Countries, subdivisions and cities as a versioned, validated dataset — plus a
Python query API over it.

```
250 countries · 5,308 subdivisions · 152,970 cities · 420 languages
built from dr5hn/countries-states-cities-database @ v3.2-export.7
```

## Two things to know before you use this

**1. Do not persist `id`.** Upstream ids are not stable. Between two
consecutive upstream releases, 351 state ids and 6,321 city ids changed
meaning. Store `stable_key`, `iso2` or `iso3166_2` instead — every lookup
accepts them.

**2. Subdivisions nest.** The UK has 221 subdivisions across two levels.
`states_of("GB")` gives all of them; `root_states("GB")` gives the four you
want in a dropdown. Flattening the two is what produced the orphan-foreign-key
bug this dataset was rebuilt to fix.

## Quick start

```python
import geodata

geodata.get_country("NG")                    # by iso2, iso3, numeric, or name
geodata.get_country("Deutschland")           # native names work too

geodata.root_states("GB")                    # England, N. Ireland, Scotland, Wales
geodata.states_of("GB")                      # all 221
geodata.get_state("GB", "GB-BIR")            # stable-key lookup
geodata.substates_of(geodata.get_state("GB", name="Scotland"))   # 32 council areas

geodata.cities_of("NG", state="Lagos")
geodata.search_cities("sao paulo")           # accent- and case-insensitive

geodata.subdivision_twin("MQ")               # Martinique as the French state FR-972

geodata.get_language("pt-BR")                # -> Language(code='pt', name='Portuguese')
geodata.localized_name(geodata.get_country("DE"), "fr")          # 'Allemagne'
geodata.localized_name(geodata.get_state("GB", "GB-SCT"), "ru")  # 'Шотландия'
geodata.translations_of(geodata.get_country("DE"))               # {'fr': ..., 'ja': ...}
```

Cities load lazily: importing the package and querying countries or states
never reads the 41 MB cities table.

## Layout

| path | what |
|---|---|
| `data/canonical/*.ndjson` | the dataset — flat, one JSON object per line, explicit foreign keys |
| `data/SOURCE.lock` | upstream repo, pinned tag, per-file sha256 |
| `data/overrides/` | reviewed local corrections, each with a reason and a source |
| `data/curated/` | relationships upstream documents in prose but not in data |
| `data/vendor/` | committed inputs that are not part of the upstream export (ISO 639 languages) |
| `data/snapshots/<version>/` | gzipped previous releases, so churn has a diff base |
| `data/remap/<from>-<to>.ndjson` | id remap table for already-seeded consumers |
| `schema/*.schema.json` | the contract |
| `scripts/` | fetch → build → validate → churn → release |
| `src/geodata/` | the query API, plus the optional Django app |
| `docs/MIGRATION.md` | how to upgrade a populated database without corrupting it |
| `docs/RELEASING.md` | the release checklist |

## Pipeline

```bash
make refresh    # fetch the pinned upstream tag, rebuild, run the gate
make check      # the gate + the full test suite (what CI runs)
make release VERSION=2026.10
```

Every step is reproducible: `scripts/fetch.py` pins upstream by release tag and
verifies sha256, and CI rebuilds from that tag and fails if the result differs
from what is committed.

## The validation gate

`scripts/validate.py` blocks a release on nine checks:

1. **Zero orphan foreign keys** — every state resolves to a country, every city
   to a state, and to a state in the same country. *The previous dataset failed
   this with 3,751 cities.*
2. Schema conformance against `schema/*.schema.json`.
3. Uniqueness of `iso2`, `iso3`, `numeric_code`, `(country, iso3166_2)`, and
   every stable key.
4. Coordinate sanity: range, Null-Island rejection, country-bbox outliers.
5. `parent_id` resolves and is acyclic.
6. Counts within the churn budget.
7. Encoding hygiene: valid UTF-8, no mojibake, no HTML entities, no edge
   whitespace.
8. Derived flags agree with the actual relations.
9. Every locale key in the translation artifacts resolves to a row in the
   language table — a translated name no consumer can label is a defect.

## Django

```python
INSTALLED_APPS = [..., "geodata.contrib.django"]
```

Models carry `geodata_id`, `stable_key`, `is_active` and `superseded_by`. On a
dataset upgrade, run `geodata_migrate` — **not** a re-seed:

```bash
python manage.py geodata_migrate --remap data/remap/2026.05-2026.09.ndjson
```

It defaults to a dry run and never deletes a referenced row. See
`docs/MIGRATION.md`.

## Provenance and limits

Upstream is [dr5hn/countries-states-cities-database](https://github.com/dr5hn/countries-states-cities-database),
community-maintained and the best free source of its kind — but not an
authority, and it can lag geopolitical changes. For strict ISO conformance the
authority is ISO 3166 itself; for French communes, INSEE.

Where we know better, corrections live in `data/overrides/` with a reason and a
source, rather than as a fork.
