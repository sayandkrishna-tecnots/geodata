"""Pin the invariants so a future refresh cannot regress them (plan step 9).

These assert *structure*, not specific values -- see test_data_regressions.py
for the per-issue value assertions. Counts are asserted as floors with a
tolerance band rather than exact equality: upstream grows, and a test that
fails every time a city is added is a test people delete.
"""

import collections
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANON = os.path.join(ROOT, "data", "canonical")

# Measured at dr5hn v3.2-export.7, the tag in data/SOURCE.lock.
EXPECTED = {"countries": 250, "states": 5308, "cities": 152970}
# A refresh may add rows freely; losing more than this means something broke.
COUNT_TOLERANCE_PCT = 2.0


def load(name):
    path = os.path.join(CANON, name + ".ndjson")
    if not os.path.exists(path):
        pytest.skip("{} not built -- run scripts/build_canonical.py".format(name))
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


@pytest.fixture(scope="module")
def countries():
    return load("countries")


@pytest.fixture(scope="module")
def states():
    return load("states")


@pytest.fixture(scope="module")
def cities():
    return load("cities")


# ----------------------------------------------------------------- counts


@pytest.mark.parametrize("entity", sorted(EXPECTED))
def test_counts_within_tolerance(entity, countries, states, cities):
    rows = {"countries": countries, "states": states, "cities": cities}[entity]
    expected = EXPECTED[entity]
    floor = expected * (1 - COUNT_TOLERANCE_PCT / 100.0)
    assert len(rows) >= floor, (
        "{} dropped from {} to {} (>{}% loss). Review artifacts/CHURN.md before "
        "updating EXPECTED.".format(entity, expected, len(rows), COUNT_TOLERANCE_PCT)
    )


# --------------------------------------------------------- referential integrity


def test_no_orphan_states(countries, states):
    ids = {c["id"] for c in countries}
    orphans = [s["id"] for s in states if s["country_id"] not in ids]
    assert orphans == []


def test_no_orphan_cities(states, countries, cities):
    state_ids = {s["id"] for s in states}
    country_ids = {c["id"] for c in countries}
    assert [c["id"] for c in cities if c["state_id"] not in state_ids] == []
    assert [c["id"] for c in cities if c["country_id"] not in country_ids] == []


def test_city_state_and_country_agree(states, cities):
    """The bug that made the old mirror data unusable (issue 5)."""
    state_country = {s["id"]: s["country_id"] for s in states}
    bad = [c["id"] for c in cities if state_country[c["state_id"]] != c["country_id"]]
    assert bad == []


def test_england_scotland_wales_resolve(states):
    """The specific orphan: 3,751 cities pointed at these three missing ids."""
    by_id = {s["id"]: s for s in states}
    for sid, name in ((2335, "Scotland"), (2336, "England"), (2338, "Wales")):
        assert sid in by_id, "state {} ({}) is missing".format(sid, name)
        assert by_id[sid]["name"] == name
        assert by_id[sid]["country_iso2"] == "GB"


# ------------------------------------------------------------------ hierarchy


def test_parent_ids_resolve_and_are_acyclic(states):
    by_id = {s["id"]: s for s in states}
    for s in states:
        seen = {s["id"]}
        cur = s
        while cur["parent_id"] is not None:
            assert cur["parent_id"] in by_id, "state {} has a dangling parent".format(cur["id"])
            cur = by_id[cur["parent_id"]]
            assert cur["id"] not in seen, "parent_id cycle at state {}".format(s["id"])
            seen.add(cur["id"])


def test_depth_matches_parent_chain(states):
    by_id = {s["id"]: s for s in states}
    for s in states:
        depth, cur = 1, s
        while cur["parent_id"] is not None:
            cur = by_id[cur["parent_id"]]
            depth += 1
        assert s["depth"] == depth, "state {} depth is wrong".format(s["id"])


def test_parents_are_in_the_same_country(states):
    by_id = {s["id"]: s for s in states}
    for s in states:
        if s["parent_id"] is not None:
            assert by_id[s["parent_id"]]["country_iso2"] == s["country_iso2"]


# ----------------------------------------------------------------- uniqueness


def test_country_identities_are_unique(countries):
    for field in ("id", "iso2", "stable_key"):
        values = [c[field] for c in countries]
        assert len(set(values)) == len(values), "duplicate country {}".format(field)
    for field in ("iso3", "numeric_code"):
        values = [c[field] for c in countries if c[field]]
        assert len(set(values)) == len(values), "duplicate country {}".format(field)


def test_iso2_is_two_uppercase_letters(countries):
    assert all(len(c["iso2"]) == 2 and c["iso2"].isupper() for c in countries)


def test_stable_keys_are_unique(states, cities):
    for label, rows in (("state", states), ("city", cities)):
        keys = [r["stable_key"] for r in rows]
        dupes = [k for k, n in collections.Counter(keys).items() if n > 1]
        assert dupes == [], "duplicate {} stable_key: {}".format(label, dupes[:5])


def test_state_iso3166_2_unique_within_country(states):
    seen = collections.Counter(
        (s["country_iso2"], s["iso3166_2"]) for s in states if s["iso3166_2"]
    )
    assert [k for k, n in seen.items() if n > 1] == []


# ---------------------------------------------------------------- coordinates


def test_coordinates_are_in_range(countries, states, cities):
    for rows in (countries, states, cities):
        for r in rows:
            if r["latitude"] is not None:
                assert -90 <= r["latitude"] <= 90, r["id"]
            if r["longitude"] is not None:
                assert -180 <= r["longitude"] <= 180, r["id"]


def test_nothing_sits_on_null_island(countries, states, cities):
    """(0, 0) is upstream's placeholder for unknown; the build nulls it."""
    for rows in (countries, states, cities):
        assert [r["id"] for r in rows if r["latitude"] == 0 and r["longitude"] == 0] == []


def test_state_coordinates_are_optional(states):
    """Issue 7: never assume a state has coordinates."""
    without = [s for s in states if s["latitude"] is None]
    assert len(without) < len(states), "sanity: not every state can be missing coords"


# --------------------------------------------------------------------- flags


def test_flags_agree_with_relations(countries, states, cities):
    states_per = collections.Counter(s["country_id"] for s in states)
    cities_per = collections.Counter(c["country_id"] for c in cities)
    for c in countries:
        assert c["state_count"] == states_per.get(c["id"], 0), c["iso2"]
        assert c["city_count"] == cities_per.get(c["id"], 0), c["iso2"]
        assert c["has_states"] is (states_per.get(c["id"], 0) > 0), c["iso2"]
        assert c["has_cities"] is (cities_per.get(c["id"], 0) > 0), c["iso2"]


# ------------------------------------------------------- multi-level territories


def test_multi_level_territories_are_linked(countries, states):
    """Decision 3: Martinique et al are both a country and an FR subdivision."""
    by_iso2 = {c["iso2"]: c for c in countries}
    by_state_id = {s["id"]: s for s in states}
    linked = [c for c in countries if c["also_subdivision_of"]]
    assert len(linked) == 21, "expected 21 multi-level territories, got {}".format(len(linked))

    for c in linked:
        link = c["also_subdivision_of"]
        assert link["state_id"] in by_state_id
        state = by_state_id[link["state_id"]]
        assert state["country_iso2"] == link["country_iso2"]
        assert link["country_iso2"] in by_iso2

    mq = by_iso2["MQ"]["also_subdivision_of"]
    assert mq["country_iso2"] == "FR" and mq["state_id"] == 4827
    assert by_iso2["PR"]["also_subdivision_of"]["country_iso2"] == "US"
    assert by_iso2["HK"]["also_subdivision_of"]["country_iso2"] == "CN"
    # Greenland is documented upstream as a known gap: country only.
    assert by_iso2["GL"]["also_subdivision_of"] is None


# ----------------------------------------------------------------- field set


def test_fields_the_mirror_dropped_are_present(countries, states, cities):
    """Issue 6: the fields the react-country-state-city mirror minified away."""
    for field in ("timezones", "nationality", "population", "area_sq_km",
                  "postal_code_format", "postal_code_regex", "region_id",
                  "subregion_id", "emoji_unicode", "wikidata_id", "native"):
        assert field in countries[0], "countries lost {}".format(field)
    for field in ("iso3166_2", "fips_code", "type", "level", "parent_id",
                  "native", "timezone", "wikidata_id", "population"):
        assert field in states[0], "states lost {}".format(field)
    for field in ("timezone", "state_code", "country_iso2"):
        assert field in cities[0], "cities lost {}".format(field)


def test_phone_code_is_renamed_from_upstream(countries):
    """Issue 10: upstream calls it `phonecode`."""
    by_iso2 = {c["iso2"]: c for c in countries}
    assert "phonecode" not in by_iso2["NG"]
    assert by_iso2["NG"]["phone_code"] == "234"


def test_field_coverage_is_not_mostly_null(countries, states):
    """A mapping bug shows up as a field that is null everywhere."""
    for field in ("timezones", "nationality", "region", "capital", "emoji"):
        filled = sum(1 for c in countries if c.get(field))
        assert filled > len(countries) * 0.8, "{} is only {}/{} filled".format(
            field, filled, len(countries)
        )
    for field in ("iso3166_2", "type", "timezone"):
        filled = sum(1 for s in states if s.get(field))
        assert filled > len(states) * 0.8, "{} is only {}/{} filled".format(
            field, filled, len(states)
        )


def test_no_translations_in_the_base_payload(countries, states):
    """They live in a separate artifact to keep the npm entry point small."""
    assert "translations" not in countries[0]
    assert "translations" not in states[0]
    assert os.path.exists(os.path.join(CANON, "translations.countries.ndjson"))


# ------------------------------------------------------------------ provenance


def test_source_lock_pins_a_release_tag():
    with open(os.path.join(ROOT, "data", "SOURCE.lock"), encoding="utf-8") as fh:
        lock = json.load(fh)
    assert lock["repo"] == "dr5hn/countries-states-cities-database"
    assert lock["tag"].startswith("v"), "must pin a tag, never a branch (Decision 1)"
    assert lock["tag"] != "master"
    for meta in lock["files"].values():
        assert len(meta["sha256"]) == 64


# -------------------------------------------------------------- languages


@pytest.fixture(scope="module")
def languages():
    return load("languages")


def test_language_codes_are_unique_and_well_formed(languages):
    assert len(languages) == 420
    codes = [row["code"] for row in languages]
    assert len(set(codes)) == len(codes)
    for code in codes:
        assert 2 <= len(code) <= 3 and code.isalpha() and code.islower(), code


def test_language_names_are_unique(languages):
    # A name collision would make find_language(name) arbitrary. The vendored
    # list carries one code per language, so this must hold.
    names = collections.Counter(row["normalized_name"] for row in languages)
    assert [n for n, c in names.items() if c > 1] == []


def test_language_standard_matches_code_length(languages):
    for row in languages:
        expected = "iso639_1" if len(row["code"]) == 2 else "iso639_2"
        assert row["standard"] == expected, row


def test_languages_are_sorted_by_code(languages):
    codes = [row["code"] for row in languages]
    assert codes == sorted(codes)


def test_every_translation_locale_has_a_language(languages):
    """The cross-table check: translation keys must be labellable.

    Before the language table landed, `translations.*.ndjson` shipped BCP-47
    keys with nothing in the repo defining them. This is the assertion that
    turns an unknown locale into a build failure.
    """
    codes = {row["code"] for row in languages}
    locales = set()
    for artifact in ("translations.countries", "translations.states"):
        path = os.path.join(CANON, artifact + ".ndjson")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    locales.update(json.loads(line)["translations"].keys())
    assert locales, "no translation artifacts to check"
    unresolved = sorted(t for t in locales if t.split("-")[0].lower() not in codes)
    assert unresolved == [], (
        "translation locales with no language row: {}. Add them to "
        "data/vendor/languages.json.".format(unresolved)
    )


def test_translation_locales_use_iso639_1_codes(languages):
    """Every locale we ship keys on a two-letter code, not a 639-2 one.

    Not a hard requirement of BCP-47, but true today and worth knowing if it
    ever stops being true -- consumers key their i18n on `pt`, not `por`.
    """
    by_code = {row["code"]: row for row in languages}
    path = os.path.join(CANON, "translations.countries.ndjson")
    if not os.path.exists(path):
        pytest.skip("translations not built")
    with open(path, encoding="utf-8") as fh:
        locales = set()
        for line in fh:
            if line.strip():
                locales.update(json.loads(line)["translations"].keys())
    for tag in locales:
        assert by_code[tag.split("-")[0]]["standard"] == "iso639_1", tag
