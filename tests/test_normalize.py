import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.lib.normalize import (
    clean_text,
    has_html_entity,
    has_mojibake,
    normalize_key,
    normalize_name,
    slugify,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "normalize.json")


def test_non_latin_scripts_survive():
    """The fold is script-preserving, not transliterating."""
    assert normalize_name("Октябрьский") == "октябрьский"  # й is a letter, not и+breve
    assert normalize_name("сёла") == "сёла"
    assert normalize_name("北京") == "北京"
    assert normalize_name("سروستان") == "سروستان"
    assert normalize_name("Θεσσαλονίκη") == "θεσσαλονικη"  # Greek tonos is decorative
    assert normalize_name("Đà Nẵng") == "đa nang"


def test_no_name_folds_to_empty():
    """A name that folds to '' would break the stable key."""
    for value in ["Октябрьский", "北京", "سروستان", "Чучер - Сандево"]:
        assert normalize_name(value) != ""


def test_accents_and_case():
    assert normalize_name("Saint-Étienne") == "saint etienne"
    assert normalize_name("SÃO PAULO".replace("Ã", "Ã")) is not None
    assert normalize_name("São Paulo") == "sao paulo"
    assert normalize_name("Ürümqi") == "urumqi"


def test_punctuation_and_whitespace():
    assert normalize_name("  N'Djamena ") == "n djamena"
    assert normalize_name("Washington, D.C.") == "washington d c"
    assert normalize_name("Al-Ḥudaydah") == "al hudaydah"
    assert normalize_name("Sainte‐Anne") == "sainte anne"  # U+2010 hyphen


def test_idempotent():
    for value in ["Saint-Étienne", "São Paulo", "  N'Djamena "]:
        once = normalize_name(value)
        assert normalize_name(once) == once


def test_empty_and_none():
    assert normalize_name(None) == ""
    assert normalize_name("") == ""
    assert normalize_name("---") == ""


def test_normalize_key():
    assert normalize_key("GB-BIR") == "gbbir"
    assert normalize_key("gb bir") == "gbbir"
    assert normalize_key(None) == ""


def test_slugify():
    assert slugify("Saint-Étienne") == "saint-etienne"


def test_clean_text():
    assert clean_text("  São   Paulo ") == "São Paulo"
    assert clean_text("") is None
    assert clean_text(None) is None
    # NFC: precomposed and decomposed forms converge
    assert clean_text("é") == clean_text("é")


def test_mojibake_and_entities():
    assert has_mojibake("SÃ£o Paulo".replace("Ã£", "Ã©"))
    assert not has_mojibake("São Paulo")
    assert has_html_entity("Cote d&#39;Ivoire")
    assert not has_html_entity("Cote d'Ivoire")


def test_conformance_fixture_matches():
    """The fixture the JS build must reproduce byte-for-byte."""
    with open(FIXTURE, encoding="utf-8") as fh:
        cases = json.load(fh)
    for case in cases["normalize_name"]:
        assert normalize_name(case["in"]) == case["out"], case["in"]
    for case in cases["normalize_key"]:
        assert normalize_key(case["in"]) == case["out"], case["in"]


def test_the_two_copies_of_the_normalizer_are_identical():
    """`src/geodata/normalize.py` is a copy of `scripts/lib/normalize.py`.

    The build computes `stable_key` with the scripts copy and the query API
    matches against it with the package copy. If they drift, lookups silently
    stop finding records that are actually present -- the worst kind of bug in
    reference data, because nothing errors.

    Keep them byte-identical. (Packaging cannot import across the two trees:
    the package must be installable without the scripts directory.)
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "scripts", "lib", "normalize.py"), "rb") as fh:
        build_copy = fh.read()
    with open(os.path.join(root, "src", "geodata", "normalize.py"), "rb") as fh:
        package_copy = fh.read()
    assert build_copy == package_copy, (
        "normalize.py has drifted between scripts/lib and src/geodata. "
        "Copy one over the other: cp scripts/lib/normalize.py src/geodata/normalize.py"
    )


def test_stable_keys_in_the_data_match_the_current_normalizer():
    """A normalizer change invalidates every stable_key already published."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "data", "canonical", "states.ndjson")
    if not os.path.exists(path):
        import pytest

        pytest.skip("dataset not built")
    with open(path, encoding="utf-8") as fh:
        for _, line in zip(range(300), fh):
            row = json.loads(line)
            assert normalize_name(row["name"]) == row["normalized_name"], row["name"]
