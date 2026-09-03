"""One test per audit finding (plan step 10).

Every assertion here corresponds to a specific defect in the old
react-country-state-city snapshot. If any of these fails, we have regressed to
mirror-quality data.

Where the old snapshot files (`countries.json`, `states.json`, `cities.json` at
the repo root) are still present, the tests also assert the old value was
*actually wrong*, so a passing test proves the fix rather than restating
upstream.
"""

import collections
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANON = os.path.join(ROOT, "data", "canonical")
LEGACY = ROOT  # the pre-remediation snapshot, if it has not been deleted yet


def load_canonical(name):
    path = os.path.join(CANON, name + ".ndjson")
    if not os.path.exists(path):
        pytest.skip("run scripts/build_canonical.py first")
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


@pytest.fixture(scope="module")
def countries():
    return {c["iso2"]: c for c in load_canonical("countries")}


@pytest.fixture(scope="module")
def states():
    return load_canonical("states")


@pytest.fixture(scope="module")
def cities():
    return load_canonical("cities")


@pytest.fixture(scope="module")
def legacy_countries():
    path = os.path.join(LEGACY, "countries.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return {c["iso2"]: c for c in json.load(fh)}


# =====================================================================
# Issue 4 -- 27 stale country facts
# =====================================================================

# (iso2, field, stale value the mirror shipped, correct value)
STALE_FACTS = [
    ("SZ", "name", "Swaziland", "Eswatini"),
    ("MK", "name", "Macedonia", "North Macedonia"),
    ("UA", "capital", "Kiev", "Kyiv"),
    ("HR", "currency", "HRK", "EUR"),
    ("BG", "currency", "BGN", "EUR"),
    ("MR", "currency", "MRO", "MRU"),
    ("ST", "currency", "STD", "STN"),
    ("VE", "currency", "VEF", "VES"),
    ("CG", "currency", "XAF", "CDF"),
    ("MX", "subregion", "Central America", "Northern America"),
    ("TL", "name", "East Timor", "Timor-Leste"),
    ("GM", "name", "Gambia The", "The Gambia"),
]


@pytest.mark.parametrize(
    "iso2,field,stale,correct", STALE_FACTS, ids=[f"{c[0]}-{c[1]}" for c in STALE_FACTS]
)
def test_stale_country_facts_are_corrected(iso2, field, stale, correct, countries, legacy_countries):
    assert countries[iso2][field] == correct, (
        "{}.{} is {!r}, expected {!r}".format(iso2, field, countries[iso2][field], correct)
    )
    if legacy_countries and iso2 in legacy_countries:
        # Proves the fix is real: the old snapshot did carry the stale value.
        assert legacy_countries[iso2].get(field) == stale, (
            "old snapshot no longer shows the stale value -- update the test"
        )


def test_cote_divoire_name(countries):
    """The mirror shipped 'Cote D'Ivoire (Ivory Coast)'."""
    assert "(" not in countries["CI"]["name"]
    assert countries["CI"]["name"] in ("Ivory Coast", "Cote D'Ivoire", "Côte d'Ivoire")


def test_country_name_casing_is_fixed(countries):
    """The mirror had 'Antigua And Barbuda', 'Papua new Guinea'."""
    assert countries["AG"]["name"] == "Antigua and Barbuda"
    assert countries["PG"]["name"] == "Papua New Guinea"


def test_eurozone_currencies(countries):
    """Croatia joined 2023, Bulgaria followed; the mirror had neither."""
    for iso2 in ("HR", "BG"):
        assert countries[iso2]["currency"] == "EUR"
        assert countries[iso2]["currency_symbol"] == "€"


# =====================================================================
# Issue 2 -- 846 missing states
# =====================================================================

# Minimum subdivision counts, from the upstream diff in the audit.
MIN_STATE_COUNTS = {
    "GB": 221,  # mirror had 74
    "EE": 79,
    "PR": 68,
    "BD": 64,
    "IS": 64,
    "MH": 24,
    "GU": 19,
    "ES": 19,
}


@pytest.mark.parametrize("iso2,minimum", sorted(MIN_STATE_COUNTS.items()))
def test_state_counts_recovered(iso2, minimum, states):
    n = sum(1 for s in states if s["country_iso2"] == iso2)
    assert n >= minimum, "{} has {} subdivisions, expected at least {}".format(iso2, n, minimum)


def test_uk_subdivisions_are_complete(states):
    """The mirror's 74 GB rows made a UK address form unusable."""
    gb = {s["name"] for s in states if s["country_iso2"] == "GB"}
    assert len(gb) >= 221
    for name in ("Birmingham", "Bradford", "Bristol", "Aberdeen",
                 "Bath and North East Somerset", "England", "Scotland",
                 "Wales", "Northern Ireland"):
        assert name in gb, "GB is missing {}".format(name)


def test_uk_has_all_32_scottish_council_areas(states):
    """Also guards the override that moved the City of London out of Scotland."""
    children = [s for s in states if s["country_iso2"] == "GB" and s["parent_id"] == 2335]
    council_areas = [s for s in children if s["type"] == "council area"]
    assert len(council_areas) == 32, "expected 32 Scottish council areas, got {}".format(
        len(council_areas)
    )
    assert children == council_areas, "non-council-area under Scotland: {}".format(
        [s["name"] for s in children if s["type"] != "council area"]
    )


def test_city_of_london_is_in_england(states):
    """Upstream parents GB-LND to Scotland; corrected by an override."""
    london = next(s for s in states if s["id"] == 2424)
    assert london["name"] == "London" and london["iso3166_2"] == "GB-LND"
    assert london["parent_id"] == 2336, "City of London must sit under England"


def test_uk_hierarchy_is_navigable(states):
    """states_of('GB', level=1) must give 4, not 221 (Decision 3)."""
    gb = [s for s in states if s["country_iso2"] == "GB"]
    roots = [s for s in gb if s["parent_id"] is None]
    assert {s["name"] for s in roots} == {"England", "Scotland", "Wales", "Northern Ireland"}
    assert all(s["depth"] == 1 for s in roots)
    assert all(s["depth"] == 2 for s in gb if s["parent_id"] is not None)


# =====================================================================
# Issue 3 -- 8,582 missing cities
# =====================================================================

MIN_CITY_COUNTS = {
    "CN": 4133,  # mirror had 1,296 -- 69% missing
    "FR": 10000,  # v3.2 INSEE commune import
    "UY": 1800,
    "PH": 1000,
    # The mirror had 424; the audit measured 67 missing. Upstream has 491.
    "NG": 491,
}


@pytest.mark.parametrize("iso2,minimum", sorted(MIN_CITY_COUNTS.items()))
def test_city_counts_recovered(iso2, minimum, cities):
    n = sum(1 for c in cities if c["country_iso2"] == iso2)
    assert n >= minimum, "{} has {} cities, expected at least {}".format(iso2, n, minimum)


# The 29 countries the mirror shipped with zero cities.
FORMERLY_EMPTY = ["PS", "PR", "XK", "HK", "GL", "MQ", "GP", "RE", "FO", "JE"]


@pytest.mark.parametrize("iso2", FORMERLY_EMPTY)
def test_countries_that_had_no_cities_now_do(iso2, cities):
    n = sum(1 for c in cities if c["country_iso2"] == iso2)
    assert n > 0, "{} still has no cities".format(iso2)


def test_us_deduplication_is_present(cities):
    """Issue 9: upstream removed ~3,000 duplicate US rows. Fewer is correct."""
    n = sum(1 for c in cities if c["country_iso2"] == "US")
    assert n < 19819, "US still carries the mirror's duplicate rows"
    assert n > 15000, "US city count collapsed -- check artifacts/CHURN.md"


def test_no_country_is_unexpectedly_empty(countries, cities):
    """A country with states but no cities at all is a red flag."""
    by_country = collections.Counter(c["country_iso2"] for c in cities)
    empty = sorted(
        iso2 for iso2, c in countries.items() if c["has_states"] and not by_country.get(iso2)
    )
    # Upstream genuinely has no city rows for these; asserted so the list can
    # only shrink, never silently grow.
    assert len(empty) <= 27, "countries with states but zero cities grew to {}: {}".format(
        len(empty), empty
    )


# =====================================================================
# Issue 5 -- orphan foreign keys (the blocker)
# =====================================================================


def test_the_3751_orphan_cities_now_resolve(states, cities):
    """Cities on state ids 2335/2336/2338 were unseedable in the old data."""
    by_id = {s["id"]: s for s in states}
    affected = [c for c in cities if c["state_id"] in (2335, 2336, 2338)]
    for c in affected:
        assert c["state_id"] in by_id


def test_legacy_snapshot_actually_had_the_orphans():
    """Proves the blocker was real, not a misreading of the old files."""
    states_path = os.path.join(LEGACY, "states.json")
    cities_path = os.path.join(LEGACY, "cities.json")
    if not (os.path.exists(states_path) and os.path.exists(cities_path)):
        pytest.skip("legacy snapshot has been removed")
    with open(states_path, encoding="utf-8") as fh:
        legacy_states = json.load(fh)
    known = {s["id"] for entry in legacy_states for s in entry.get("states", [])}
    assert not ({2335, 2336, 2338} & known), (
        "legacy states.json unexpectedly contains England/Scotland/Wales"
    )


# =====================================================================
# Issue 6 -- dropped fields
# =====================================================================


def test_dropped_country_fields_are_back(countries):
    ng = countries["NG"]
    assert ng["timezones"] and ng["timezones"][0]["zone_name"] == "Africa/Lagos"
    assert ng["nationality"] == "Nigerian"
    assert ng["population"] and ng["population"] > 100_000_000
    assert ng["area_sq_km"] == 923768
    assert ng["postal_code_format"] and ng["postal_code_regex"]
    assert ng["region_id"] and ng["subregion_id"]
    assert ng["emoji_unicode"] == "U+1F1F3 U+1F1EC"
    assert ng["wikidata_id"] == "Q1033"


def test_dropped_state_fields_are_back(states):
    aberdeen = next(s for s in states if s["id"] == 2463)
    assert aberdeen["iso3166_2"] == "GB-ABE"
    assert aberdeen["fips_code"] == "T5"
    assert aberdeen["type"] == "council area"
    assert aberdeen["timezone"] == "Europe/London"
    assert aberdeen["parent_id"] == 2335
    assert aberdeen["wikidata_id"] == "Q36405"


def test_dropped_city_fields_are_back(cities):
    with_tz = sum(1 for c in cities if c["timezone"])
    assert with_tz > len(cities) * 0.9, "city timezone coverage collapsed"


# =====================================================================
# Issue 7 -- state coordinates are mostly absent (accept as reality)
# =====================================================================


def test_state_coordinate_coverage_improved(states):
    """The mirror had 501/4,813. Upstream is far better, but never assume."""
    with_coords = sum(1 for s in states if s["latitude"] is not None)
    assert with_coords > len(states) * 0.9, (
        "only {}/{} states have coordinates".format(with_coords, len(states))
    )


# =====================================================================
# Issue 8 -- ids churn (the assumption the library plan got wrong)
# =====================================================================


def test_every_record_carries_a_stable_key(countries, states, cities):
    assert all(c["stable_key"] for c in countries.values())
    assert all(s["stable_key"] for s in states)
    assert all(c["stable_key"] for c in cities)


def test_country_stable_key_is_iso2_not_id(countries):
    for iso2, c in countries.items():
        assert c["stable_key"] == iso2


def test_state_stable_key_prefers_iso3166_2(states):
    by_iso = [s for s in states if s["iso3166_2"]]
    assert len(by_iso) > len(states) * 0.9
    assert all(s["stable_key"].split("/")[1].startswith("iso:") for s in by_iso)


def test_fr_cities_are_parented_to_insee_departments(states, cities):
    """v3.2's documented breaking change: 8,727 FR cities were re-parented."""
    fr_states = {s["id"]: s for s in states if s["country_iso2"] == "FR"}
    fr_cities = [c for c in cities if c["country_iso2"] == "FR"]
    assert len(fr_cities) > 10000
    assert all(c["state_id"] in fr_states for c in fr_cities)
    departments = {s["id"] for s in fr_states.values() if s["type"] == "metropolitan department"}
    if departments:
        in_departments = sum(1 for c in fr_cities if c["state_id"] in departments)
        assert in_departments > len(fr_cities) * 0.8, (
            "FR cities are not attached to departments -- the INSEE re-parenting is missing"
        )


# =====================================================================
# Issue 10 / 11 -- naming and shape
# =====================================================================


def test_canonical_shape_is_flat_with_explicit_fks(cities):
    """Issue 11: no tree-walking to find one city."""
    c = cities[0]
    assert "states" not in c and "cities" not in c
    assert {"country_id", "state_id", "country_iso2"} <= set(c)


def test_ndjson_is_one_object_per_line():
    path = os.path.join(CANON, "cities.ndjson")
    with open(path, encoding="utf-8") as fh:
        for _ in range(50):
            line = fh.readline()
            if not line:
                break
            assert json.loads(line)["id"]


# =====================================================================
# Overrides -- Decision 4
# =====================================================================


def test_spanish_uniprovincial_cycles_are_broken(states):
    for sid in (1160, 1170, 1171):
        s = next(x for x in states if x["id"] == sid)
        assert s["parent_id"] is None, "{} still self-references".format(s["name"])
        assert s["depth"] == 1


def test_geocoder_collision_coordinates_are_corrected(cities):
    by_id = {c["id"]: c for c in cities}
    copenhagen = by_id[30620]
    assert 55.0 < copenhagen["latitude"] < 56.5
    assert 12.0 < copenhagen["longitude"] < 13.0
    # Puerto Rico municipalities must actually be in Puerto Rico.
    for cid in (153557, 153574, 153576, 153590, 153591, 153609, 153611, 153615):
        c = by_id[cid]
        assert 17.8 < c["latitude"] < 18.6, "{} is not in PR".format(c["name"])
        assert -67.3 < c["longitude"] < -65.5, "{} is not in PR".format(c["name"])


def test_every_override_is_documented():
    """Decision 4: no undocumented patches."""
    directory = os.path.join(ROOT, "data", "overrides")
    for filename in os.listdir(directory):
        if not filename.endswith(".patch.ndjson"):
            continue
        with open(os.path.join(directory, filename), encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                patch = json.loads(line)
                for field in ("_reason", "_source", "_review", "_match"):
                    assert patch.get(field), "{}:{} missing {}".format(filename, lineno, field)
                assert patch["_source"].startswith("http"), "{}:{}".format(filename, lineno)
