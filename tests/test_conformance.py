"""The Python half of the cross-language conformance suite.

`packages/js/test/conformance.test.ts` runs this exact corpus. A case that
passes there and fails here means the two SDKs disagree about the same
dataset -- the failure the multi-stack design exists to prevent.

Expectations in `tests/conformance/cases.json` are generated from
`data/canonical` by `scripts/build_conformance.py`, not from either
implementation, so neither language is privileged: both are measured against
the data they claim to serve.

Regenerate after a dataset refresh and read the diff -- a changed expectation
is a changed fact about the world.
"""

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

import geodata  # noqa: E402

with open(os.path.join(HERE, "conformance", "cases.json"), encoding="utf-8") as fh:
    SUITE = json.load(fh)
CASES = SUITE["cases"]

# The corpus is written in the JS naming, since it is shared. Mapping it here
# rather than renaming either API: both are idiomatic in their own language,
# and the whole point is that the *answers* agree, not the spellings.
DISPATCH = {}


def case(fn):
    def register(func):
        DISPATCH[fn] = func
        return func

    return register


@case("getCountry")
def _get_country(key):
    row = geodata.get_country(key)
    return {"iso2": row.iso2, "name": row.name}


@case("statesOf")
def _states_of(country):
    return {"count": len(geodata.states_of(country))}


@case("rootStates")
def _root_states(country):
    rows = geodata.root_states(country)
    return {"count": len(rows), "names": [s.name for s in rows][:8]}


@case("getState")
def _get_state(country, key):
    row = geodata.get_state(country, key)
    return {"iso3166_2": row.iso3166_2, "name": row.name}


@case("getStateByName")
def _get_state_by_name(country, name):
    return {"iso3166_2": geodata.get_state(country, name=name).iso3166_2}


@case("citiesOf")
def _cities_of(country, state):
    rows = geodata.cities_of(country, state=state)
    return {"count": len(rows), "first": rows[0].name if rows else None}


@case("searchCities")
def _search_cities(query, country, limit):
    rows = geodata.search_cities(query, country=country, limit=limit)
    return {"first": rows[0].name if rows else None}


@case("localizedName")
def _localized_name(country, locale):
    return {"name": geodata.localized_name(geodata.get_country(country), locale)}


@case("subdivisionTwin")
def _subdivision_twin(country):
    twin = geodata.subdivision_twin(country)
    if twin is None:
        return None
    return {"country_iso2": twin.country_iso2, "iso3166_2": twin.iso3166_2}


@case("getLanguage")
def _get_language(key):
    row = geodata.get_language(key)
    return {"code": row.code, "name": row.name}


@case("languageCounts")
def _language_counts():
    return {
        "total": len(geodata.languages()),
        "iso639_1": len(geodata.languages("iso639_1")),
        "iso639_2": len(geodata.languages("iso639_2")),
    }


@case("normalizeName")
def _normalize_name(text):
    return {"out": geodata.normalize_name(text)}


def _ids():
    return ["{0}({1})".format(c["fn"], ",".join(str(a) for a in c["args"])) for c in CASES]


@pytest.mark.parametrize("case_", CASES, ids=_ids())
def test_case(case_):
    runner = DISPATCH.get(case_["fn"])
    assert runner is not None, "unknown conformance fn: {0}".format(case_["fn"])
    actual = runner(*case_["args"])

    expected = case_["expect"]
    if expected is None:
        assert actual is None
        return
    # Compare only the keys the case pins, exactly as the JS runner does.
    assert {k: actual[k] for k in expected} == expected


def test_corpus_is_current_and_not_hollowed_out():
    with open(os.path.join(ROOT, "data", "RELEASE.json"), encoding="utf-8") as fh:
        release = json.load(fh)
    assert SUITE["dataset_version"] == release["version"], (
        "cases.json was generated from dataset {0} but the repo is at {1}; "
        "re-run scripts/build_conformance.py and review the diff".format(
            SUITE["dataset_version"], release["version"]
        )
    )
    assert len(CASES) > 200
    assert set(c["fn"] for c in CASES) <= set(DISPATCH), "corpus uses an fn this runner cannot run"
    assert len(set(c["fn"] for c in CASES)) >= 11
