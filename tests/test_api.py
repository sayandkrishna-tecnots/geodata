"""Tests for the query API (plan steps 14-15).

The behaviours asserted here are the ones the data audit forced: multi-level
subdivisions, stable-key lookups, optional coordinates, and refusing to guess
when a name is ambiguous.
"""

import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import geodata as g  # noqa: E402
from geodata import loader  # noqa: E402


@pytest.fixture(autouse=True, scope="module")
def _dataset():
    try:
        loader.data_dir()
    except RuntimeError:
        pytest.skip("dataset not built -- run scripts/build_canonical.py")


# ------------------------------------------------------------------ countries


def test_get_country_by_every_key():
    ng = g.get_country("NG")
    assert ng.name == "Nigeria"
    assert g.get_country("NGA") is ng
    assert g.get_country("566") is ng
    assert g.get_country("Nigeria") is ng
    assert g.get_country("nigeria") is ng
    assert g.get_country(ng) is ng


def test_get_country_matches_native_names():
    """Upstream's English name for CI is 'Ivory Coast'; people type the other."""
    assert g.get_country("Cote d'Ivoire").iso2 == "CI"
    assert g.get_country("Côte d'Ivoire").iso2 == "CI"
    assert g.get_country("Ivory Coast").iso2 == "CI"
    assert g.get_country("Deutschland").iso2 == "DE"
    assert g.get_country("Espana").iso2 == "ES"


def test_english_name_wins_over_a_native_name_collision():
    """Georgia the country, not any native form that might collide."""
    assert g.get_country("Georgia").iso2 == "GE"


def test_missing_country_raises():
    with pytest.raises(g.CountryNotFound):
        g.get_country("ZZ")
    assert g.find_country("ZZ") is None


def test_countries_filtering():
    africa = g.countries(region="Africa")
    assert len(africa) > 50
    assert all(c.region == "Africa" for c in africa)
    assert [c.name for c in africa] == sorted(c.name for c in africa)
    assert all(c.has_states for c in g.countries(has_states=True))


def test_country_carries_the_fields_the_mirror_dropped():
    ng = g.get_country("NG")
    assert ng.phone_code == "234"
    assert ng.timezones[0].zone_name == "Africa/Lagos"
    assert ng.emoji and ng.nationality and ng.postal_code_regex


def test_stale_facts_are_not_reachable_through_the_api():
    assert g.get_country("SZ").name == "Eswatini"
    assert g.get_country("MK").name == "North Macedonia"
    assert g.get_country("UA").capital == "Kyiv"
    assert g.get_country("HR").currency == "EUR"


# --------------------------------------------------------------------- states


def test_states_of_returns_the_whole_forest():
    assert len(g.states_of("GB")) == 221


def test_root_states_are_the_dropdown_level():
    roots = g.root_states("GB")
    assert [s.name for s in roots] == ["England", "Northern Ireland", "Scotland", "Wales"]
    assert all(s.depth == 1 for s in roots)


def test_depth_filter_matches_root_states():
    assert g.states_of("GB", depth=1) == g.root_states("GB")
    assert len(g.states_of("GB", depth=2)) == 217


def test_substates_of():
    scotland = g.get_state("GB", name="Scotland")
    councils = g.substates_of(scotland)
    assert len(councils) == 32
    assert all(s.type == "council area" for s in councils)
    assert "Aberdeen" in {s.name for s in councils}


def test_parent_filter_is_equivalent_to_substates():
    assert g.states_of("GB", parent="GB-SCT") == g.substates_of(
        g.get_state("GB", name="Scotland")
    )


def test_type_filter():
    boroughs = g.states_of("GB", type="london borough")
    assert len(boroughs) == 32


def test_state_tree_shape():
    tree = g.state_tree("GB")
    assert [n.state.name for n in tree] == [
        "England", "Northern Ireland", "Scotland", "Wales",
    ]
    assert sum(1 for node in tree for _ in node.walk()) == 221
    scotland = next(n for n in tree if n.state.name == "Scotland")
    assert len(scotland.children) == 32
    assert scotland.children[0].children == ()


def test_city_of_london_sits_under_england():
    """Guards the override; upstream parents GB-LND to Scotland."""
    england = g.get_state("GB", name="England")
    assert g.get_state("GB", "GB-LND").parent_id == england.id


# ------------------------------------------------------- stable-key lookups


def test_get_state_by_iso3166_2():
    birmingham = g.get_state("GB", iso3166_2="GB-BIR")
    assert birmingham.name == "Birmingham"
    # The bare-key form and the country-prefix-less form both work.
    assert g.get_state("GB", "GB-BIR") is birmingham
    assert g.get_state("GB", "BIR") is birmingham


def test_get_state_by_state_code_and_name():
    assert g.get_state("GB", state_code="BIR").iso3166_2 == "GB-BIR"
    assert g.get_state("GB", name="Birmingham").iso3166_2 == "GB-BIR"
    assert g.get_state("GB", name="birmingham").iso3166_2 == "GB-BIR"


def test_get_state_rejects_a_state_from_another_country():
    with pytest.raises(g.StateNotFound):
        g.get_state("FR", iso3166_2="GB-BIR")


def test_ambiguous_name_raises_rather_than_guessing():
    """Two subdivisions can share a name across levels; refuse to pick."""
    ambiguous = None
    for iso2 in ("GB", "ES", "FR", "IT", "US"):
        names = {}
        for s in g.states_of(iso2):
            names.setdefault(s.normalized_name, []).append(s)
        for bucket in names.values():
            if len(bucket) > 1:
                ambiguous = (iso2, bucket[0].name)
                break
        if ambiguous:
            break
    if ambiguous is None:
        pytest.skip("no ambiguous subdivision name in the sampled countries")
    with pytest.raises(g.Ambiguous):
        g.get_state(ambiguous[0], name=ambiguous[1])


def test_missing_state_raises():
    with pytest.raises(g.StateNotFound):
        g.get_state("GB", iso3166_2="GB-ZZZ")


def test_stable_keys_round_trip():
    """The identity a consumer should persist (Decision 2)."""
    for iso2 in ("GB", "NG", "US"):
        for s in g.states_of(iso2)[:20]:
            assert s.stable_key.startswith(iso2 + "/")
            if s.iso3166_2:
                assert g.get_state(iso2, iso3166_2=s.iso3166_2) is s


# ------------------------------------------------- multi-level territories


def test_subdivision_twin():
    twin = g.subdivision_twin("MQ")
    assert twin.country_iso2 == "FR"
    assert twin.iso3166_2 == "FR-972"
    assert g.subdivision_twin("PR").country_iso2 == "US"
    assert g.subdivision_twin("HK").country_iso2 == "CN"


def test_most_countries_have_no_twin():
    assert g.subdivision_twin("NG") is None
    assert g.subdivision_twin("GL") is None  # documented upstream as a known gap
    twinned = [c for c in g.countries() if c.is_also_a_subdivision]
    assert len(twinned) == 21


def test_a_territory_keeps_its_own_metadata():
    """NC uses XPF, not the euro -- the reason both levels are modelled."""
    assert g.get_country("NC").currency == "XPF"
    assert g.get_country("MQ").currency == "EUR"


# --------------------------------------------------------------------- cities


def test_cities_of_state():
    lagos = g.cities_of("NG", state="Lagos")
    assert len(lagos) > 10
    assert all(c.country_iso2 == "NG" for c in lagos)
    assert [c.name for c in lagos] == sorted(c.name for c in lagos)


def test_cities_of_country():
    assert len(g.cities_of("NG")) >= 491


def test_cities_of_requires_an_argument():
    with pytest.raises(ValueError):
        g.cities_of()


def test_limit():
    assert len(g.cities_of("US", limit=5)) == 5


def test_get_city():
    city = g.get_city("GB", "GB-BIR", "Birmingham")
    assert city.name == "Birmingham"
    with pytest.raises(g.CityNotFound):
        g.get_city("GB", "GB-BIR", "Atlantis")


def test_search_is_accent_and_case_insensitive():
    names = [c.name for c in g.search_cities("sao paulo", limit=5)]
    assert "São Paulo" in names
    assert [c.name for c in g.search_cities("SAO PAULO", limit=5)] == names


def test_search_scoped_to_a_country():
    hits = g.search_cities("lagos", country="NG", limit=10)
    assert hits and all(c.country_iso2 == "NG" for c in hits)


def test_search_empty_query():
    assert g.search_cities("") == ()
    assert g.search_cities("   ") == ()


def test_city_coordinates_may_be_absent():
    """Issue 7 / null-island stripping: never assume coordinates exist."""
    cities = g.cities_of("CN")
    assert any(c.latitude is None for c in cities), (
        "expected the 22 null-island CN cities to have null coordinates"
    )


# ------------------------------------------------------------------ laziness


def test_importing_geodata_does_not_load_cities():
    """Cities are 41 MB. Importing the package must not pay for them."""
    code = (
        "import sys; sys.path.insert(0, {!r});"
        "import geodata;"
        "from geodata import loader;"
        "geodata.get_country('NG');"
        "geodata.states_of('GB');"
        "print(loader.cities_loaded())"
    ).format(os.path.join(ROOT, "src"))
    out = subprocess.check_output([sys.executable, "-c", code]).decode().strip()
    assert out == "False", "a country or state query pulled in the cities table"


def test_a_city_query_does_load_cities():
    code = (
        "import sys; sys.path.insert(0, {!r});"
        "import geodata;"
        "from geodata import loader;"
        "geodata.cities_of('NG');"
        "print(loader.cities_loaded())"
    ).format(os.path.join(ROOT, "src"))
    out = subprocess.check_output([sys.executable, "-c", code]).decode().strip()
    assert out == "True"


# ------------------------------------------------------------------ immutability


def test_records_are_frozen():
    import dataclasses

    ng = g.get_country("NG")
    with pytest.raises(dataclasses.FrozenInstanceError):
        ng.name = "Something else"


# ------------------------------------------------------------------ languages


def test_language_table_shape():
    langs = g.languages()
    assert len(langs) == 420
    assert len(g.languages(standard="iso639_1")) == 184
    assert len(g.languages(standard="iso639_2")) == 236
    assert [l.name for l in langs] == sorted(l.name for l in langs)


def test_language_code_is_the_identity():
    # Unlike every other table, a language code is safe to persist: there is no
    # upstream integer id to churn (invariant 1 does not apply here).
    for lang in g.languages():
        assert lang.stable_key == lang.code


def test_get_language_by_code_and_name():
    assert g.get_language("pt").name == "Portuguese"
    assert g.get_language("Portuguese").code == "pt"
    assert g.get_language("portuguese").code == "pt"
    # The vendored list carries exactly one code per language -- the ISO 639-1
    # one where it exists, otherwise a three-letter 639-2 code. So Chinese is
    # only `zh`, and Achinese, having no two-letter code, is only `ace`.
    assert g.get_language("ace").name == "Achinese"
    assert g.get_language("ace").standard == "iso639_2"
    assert g.find_language("zho") is None


def test_get_language_ignores_region_subtag():
    # `pt-BR` is Portuguese; this table describes languages, not locales.
    assert g.get_language("pt-BR") is g.get_language("pt")
    assert g.get_language("zh-Hans-CN") is g.get_language("zh")
    assert g.get_language("pt_BR") is g.get_language("pt")


def test_find_language_returns_none_and_get_raises():
    assert g.find_language("not-a-language") is None
    assert g.find_language("") is None
    with pytest.raises(g.LanguageNotFound):
        g.get_language("zz")


def test_every_translation_locale_resolves_to_a_language():
    # The point of shipping the language table: a translation key nothing can
    # label is a defect, and this is the assertion that says so.
    seen = set()
    for country in g.countries():
        seen.update(g.translations_of(country))
    assert seen
    for tag in seen:
        assert g.find_language(tag) is not None, tag


def test_translations_of_country_and_state():
    de = g.translations_of(g.get_country("DE"))
    assert de["fr"] == "Allemagne"
    assert de["ja"] == "ドイツ"
    scotland = g.translations_of(g.get_state("GB", "GB-SCT"))
    assert scotland["ru"] == "Шотландия"
    # Mutating the returned dict must not corrupt the shared cache.
    de["fr"] = "tampered"
    assert g.translations_of(g.get_country("DE"))["fr"] == "Allemagne"


def test_translations_of_city_is_empty_and_other_types_raise():
    assert g.translations_of(g.cities_of("NG")[0]) == {}
    with pytest.raises(TypeError):
        g.translations_of("NG")


def test_localized_name_falls_back_across_region_tags():
    de = g.get_country("DE")
    assert g.localized_name(de, "fr") == "Allemagne"
    # pt-BR is not a key for countries; it falls back to the base language.
    assert g.localized_name(de, "pt-BR") == g.localized_name(de, "pt")
    assert g.localized_name(de, g.get_language("zh")) == "德国"
    # Unknown language -> the caller's default, never a wrong name.
    assert g.localized_name(de, "zz") is None
    assert g.localized_name(de, "zz", de.name) == "Germany"
    # A known language we simply do not translate into.
    assert g.localized_name(de, "af", de.name) == "Germany"


def test_languages_do_not_load_the_cities_table():
    code = (
        "import sys; sys.path.insert(0, {!r});"
        "import geodata;"
        "from geodata import loader;"
        "geodata.get_language('pt');"
        "geodata.localized_name(geodata.get_country('DE'), 'fr');"
        "print(loader.cities_loaded())"
    ).format(os.path.join(ROOT, "src"))
    out = subprocess.check_output([sys.executable, "-c", code]).decode().strip()
    assert out == "False"
