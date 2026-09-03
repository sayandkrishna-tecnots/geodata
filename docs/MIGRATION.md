# Migrating between dataset versions

## Read this first

**Upstream geodata ids are not stable.** Between the two versions this
repository currently spans:

| | churn |
|---|---|
| state ids that changed meaning | 351 |
| city ids that changed meaning | 6,321 |
| French cities re-parented to a different state | 8,727 |
| US city rows removed (counties, moved out of the cities table) | 3,104 |
| subdivisions removed by administrative reform | 432 |

If your application stores a geodata id in a foreign key — an address, an
order, a user profile — then **re-seeding is not an update, it is silent
corruption**. `city_id = 52` before the refresh and `city_id = 52` after it can
be two different places.

So: never re-seed a populated database. Run `geodata_migrate`.

## The rule that governs everything here

> A row that something references is never deleted.

When upstream drops a place your data points at, the row is deactivated
(`is_active = False`) and, where a successor is known, `superseded_by` is set.
An order placed in 2024 against a city that no longer exists still resolves to
something meaningful. This is the whole reason the command exists.

## What to store instead of an id

Persist `stable_key`, or the underlying ISO codes:

| entity | what to store | example |
|---|---|---|
| country | `iso2` | `NG` |
| state | `iso3166_2`, else `stable_key` | `GB-BIR`, `GB/iso:gbbir` |
| city | `stable_key` | `GB/iso:gbbir/birmingham` |

`geodata_id` is still carried on every model — it is what existing foreign keys
hold, and it is what the remap table is keyed on — but it is not the identity.

## Running a migration

```bash
# 1. Refresh the dataset and gate it.
make refresh

# 2. Produce the remap table for this version pair.
python3 scripts/churn.py \
    --from data/snapshots/2026.05 --from-label 2026.05 --to-label 2026.09

# 3. Read artifacts/CHURN.md. Actually read it.

# 4. Dry run. This is the default -- it writes nothing.
python manage.py geodata_migrate --remap data/remap/2026.05-2026.09.ndjson

# 5. Apply, once the plan looks right.
python manage.py geodata_migrate --remap data/remap/2026.05-2026.09.ndjson --apply
```

### Reading the plan

```
entity        unchanged   remapped  reparented   retired  orphaned  ambiguous
-----------------------------------------------------------------------------
countries           250          0           0         0         0          0
states            4,303         77           0       432         1          0
cities          141,981        795      25,124     6,351         0      1,562
```

| bucket | meaning | what the command does |
|---|---|---|
| `unchanged` | the id still means the same place | nothing |
| `remapped` | same place, new id | updates `geodata_id` and `stable_key` |
| `reparented` | same place, same id, **different parent** | nothing to the row — but see below |
| `retired` | gone upstream, nothing detectably references it | deactivates, records a successor if known |
| `orphaned` | gone upstream, **something references it** | deactivates, records a successor. Never deletes. |
| `ambiguous` | still exists upstream, could not be paired 1:1 | **nothing** — a human decides |

`ambiguous` is deliberately untouched. If upstream deduplicated three "Carmen"
rows into one and we cannot tell which of yours maps to it, guessing is worse
than leaving it alone and telling you.

### Reference detection is best-effort

The command walks Django's reverse relations to find which rows are pointed at
from outside the geodata app. It cannot see references made through raw SQL, a
second database, or a denormalised text column. That is why rows in `retired`
are deactivated rather than deleted too — the conservative direction costs a
boolean, and the other direction is unrecoverable.

If you know your references live somewhere the ORM cannot see, treat every
`retired` row as `orphaned`.

---

## Worked example: the France re-parenting

This is the largest single break in the dataset, and the one most likely to
look like "the migration worked" while quietly breaking a feature.

### What upstream changed

Before v3.2, French cities hung off ISO 3166-2 **regions** — 18 of them,
Île-de-France, Occitanie, Nouvelle-Aquitaine. In v3.2, 8,727 cities were
re-parented onto INSEE **departments** — 101 of them, Paris (75), Nord (59),
Bouches-du-Rhône (13).

The city rows kept their ids. Only `state_id` moved.

### What that means for you

Your foreign keys are all still valid. Nothing is orphaned, nothing is
deleted, and `geodata_migrate` reports these under `reparented` and touches
nothing.

**And yet your address form is broken.** Any query written against the old
region ids returns an empty list:

```python
# Before: Île-de-France, region id 4000
City.objects.filter(state__geodata_id=4000)      # was ~1,300 cities
                                                 # now 0 -- Paris is under
                                                 # department 75, not region 4000
```

A cascading country → state → city selector built on this silently stops
offering any French city. No exception, no failed constraint. Just an empty
dropdown.

### Finding your exposure before you migrate

```python
import json

reparented = [
    json.loads(line) for line in open("data/remap/2026.05-2026.09.ndjson")
    if json.loads(line)["reason"] == "reparented"
]
affected_old_states = {e["old_state_id"] for e in reparented}

# Anything in your codebase that hard-codes one of these is about to go quiet.
print(sorted(affected_old_states))
```

Then grep your application for those ids, and for any state id at all:

```bash
grep -rn "state_id\s*=\s*[0-9]" --include=*.py --include=*.ts .
```

### Fixing it

Rewrite the query against the stable key rather than the id, and against the
tree rather than a flat list:

```python
# Wrong: a hard-coded state id, which the next refresh may re-point.
City.objects.filter(state__geodata_id=4000)

# Right: resolve through the stable key.
City.objects.filter(state__iso3166_2="FR-75")

# Right, if you want everything under a region regardless of how upstream
# reorganises the levels beneath it:
region = State.objects.get(country__iso2="FR", iso3166_2="FR-IDF")
City.objects.filter(state__in=region.children.all())
```

And in the pure-Python API:

```python
import geodata

geodata.root_states("FR")                       # top-level subdivisions
geodata.states_of("FR", parent="FR-IDF")        # what sits under one of them
geodata.cities_of("FR", state="FR-75")          # cities of a department
```

### The general lesson

A re-parenting is invisible to your database's integrity checks and invisible
to your tests if those tests use ids. It is only visible if you diff the
`state_id` distribution before and after — which is exactly what
`artifacts/CHURN.md` prints, under "Re-parented".

Read that section every refresh.

---

## Worked example: the US county removal

Upstream removed 3,104 US rows from the cities table — "Autauga County",
"Baldwin County" and so on. These were never cities; they are counties that had
been loaded into the wrong table.

This one *is* visible: any address referencing "Autauga County" as its city now
points at a deactivated row.

```python
# After migrating, find what your data referenced that upstream dropped.
from myapp.models import Address

Address.objects.filter(city__is_active=False).values_list(
    "city__name", flat=True
).distinct()
```

Your options, in order of preference:

1. **Leave it.** The row still exists and still resolves. Historical addresses
   read correctly. New addresses cannot select it, which is the desired
   outcome — it was never a city.
2. **Re-point to the real city.** Where `superseded_by` is set, follow it.
3. **Re-geocode.** For a county-as-city, there is no correct single successor;
   the address needs a real city. That is a product decision, not a migration.

Do not delete the deactivated rows. That is the one thing that cannot be undone.

---

## After migrating

```bash
# The dataset gate should still pass.
python3 scripts/validate.py

# And your own data should have no dangling references.
python manage.py geodata_migrate --remap <same file> --json > /tmp/plan.json
```

Then update the version you record as your baseline, so the *next* refresh
diffs against the right thing:

```bash
python3 scripts/release.py --version 2026.09
```
