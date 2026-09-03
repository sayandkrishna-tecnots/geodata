"""The public query surface.

Two things here follow directly from the data audit:

* **Lookups key on stable keys, not ids** (Decision 2). `get_state("GB",
  iso3166_2="GB-BIR")` survives a dataset refresh; `get_state_by_id(2402)`
  does not, because 351 state ids and 6,321 city ids changed meaning between
  two upstream versions. The id lookups exist, and are documented as unsafe
  to persist.

* **Subdivisions are a forest, not a list** (Decision 3). `states_of("GB")`
  returns all 221 UK subdivisions; `states_of("GB", depth=1)` returns the four
  constituent countries. A cascading country -> state -> city selector wants
  the second. Flattening the two is what produced the orphan-FK bug in the
  data this package replaced.
"""

from typing import Iterator, Optional, Tuple

from . import loader
from .exceptions import (
    Ambiguous,
    CityNotFound,
    CountryNotFound,
    LanguageNotFound,
    NotFound,
    StateNotFound,
)
from .types import City, Country, Language, State, StateNode

try:  # pragma: no cover - trivial import shim
    from .normalize import normalize_name
except ImportError:  # pragma: no cover
    import os
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    from scripts.lib.normalize import normalize_name

__all__ = [
    "countries", "get_country", "find_country",
    "regions", "subregions",
    "states_of", "get_state", "state_tree", "root_states", "substates_of",
    "cities_of", "get_city", "search_cities",
    "subdivision_twin",
    "languages", "get_language", "find_language",
    "translations_of", "localized_name",
]


# ------------------------------------------------------------------ countries


def countries(region=None, subregion=None, has_states=None):
    """All countries, optionally filtered. Sorted by name."""
    rows = loader.countries()
    if region is not None:
        rows = [c for c in rows if c.region == region]
    if subregion is not None:
        rows = [c for c in rows if c.subregion == subregion]
    if has_states is not None:
        rows = [c for c in rows if c.has_states is has_states]
    return tuple(sorted(rows, key=lambda c: c.name))


def get_country(key) -> Country:
    """Look a country up by iso2, iso3, numeric code, or name.

    Names match on the English name first and the native name second, both
    accent- and case-insensitively -- `get_country("Cote d'Ivoire")` resolves
    even though upstream's English name is "Ivory Coast".

    >>> get_country("NG").name
    'Nigeria'
    >>> get_country("NGA") is get_country("566") is get_country("Nigeria")
    True
    """
    country = find_country(key)
    if country is None:
        raise CountryNotFound("no country matches {!r}".format(key))
    return country


def find_country(key) -> Optional[Country]:
    """Like `get_country` but returns None instead of raising."""
    if isinstance(key, Country):
        return key
    idx = loader.country_index()
    if isinstance(key, int):
        return idx["id"].get(key)

    text = str(key).strip()
    if not text:
        return None
    upper = text.upper()
    if len(upper) == 2:
        return idx["iso2"].get(upper)
    if len(upper) == 3 and upper.isalpha():
        return idx["iso3"].get(upper)
    if text.isdigit():
        return idx["numeric"].get(text.lstrip("0") or "0") or idx["id"].get(int(text))
    normalized = normalize_name(text)
    return idx["name"].get(normalized) or idx["native"].get(normalized)



def regions():
    """The six top-level regions, sorted by name.

    `Country.region` already carries the region *name*, so this table is only
    needed for the ids and wikidata links -- or to build a region picker.
    """
    return tuple(sorted(loader.regions(), key=lambda r: r.name))


def subregions(region=None):
    """Subregions, optionally within one region. Sorted by name.

    `region` accepts a :class:`Region`, its id, or its name.
    """
    rows = loader.subregions()
    if region is not None:
        if hasattr(region, "id"):
            region_id = region.id
        elif isinstance(region, int):
            region_id = region
        else:
            wanted = normalize_name(region)
            match = [r for r in loader.regions() if r.normalized_name == wanted]
            if not match:
                raise NotFound("no region named {0!r}".format(region))
            region_id = match[0].id
        rows = [s for s in rows if s.region_id == region_id]
    return tuple(sorted(rows, key=lambda s: s.name))


# --------------------------------------------------------------------- states


def states_of(country, depth=None, level=None, parent=None, type=None):
    """Subdivisions of a country, sorted by name.

    depth   position in the parent chain, computed and authoritative.
            depth=1 is the top level (GB -> England/Scotland/Wales/NI).
    level   upstream's semantic administrative level. ADVISORY: it disagrees
            with the tree for ~1,000 states, so prefer `depth`.
    parent  restrict to the children of one state (id, iso3166_2, or State).
    type    'council area', 'province', ...
    """
    c = get_country(country)
    rows = loader.state_index()["country"].get(c.iso2, [])

    if parent is not None:
        parent_state = parent if isinstance(parent, State) else get_state(c, parent)
        rows = [s for s in rows if s.parent_id == parent_state.id]
    if depth is not None:
        rows = [s for s in rows if s.depth == depth]
    if level is not None:
        rows = [s for s in rows if s.level == level]
    if type is not None:
        rows = [s for s in rows if s.type == type]
    return tuple(sorted(rows, key=lambda s: s.name))


def root_states(country):
    """The top-level subdivisions -- what a first-tier dropdown should show."""
    return states_of(country, depth=1)


def substates_of(state) -> Tuple[State, ...]:
    """The direct children of a state."""
    sid = state.id if isinstance(state, State) else int(state)
    return tuple(sorted(loader.state_index()["children"].get(sid, []), key=lambda s: s.name))


def get_state(country, key=None, iso3166_2=None, state_code=None, name=None) -> State:
    """Look a state up within a country, by stable key.

    Tiers, in the priority order of Decision 2:

        get_state("GB", "GB-BIR")        # iso3166_2, the preferred key
        get_state("GB", state_code="BIR")
        get_state("GB", name="Birmingham")

    Raises `Ambiguous` rather than guessing when a name matches twice.
    """
    c = get_country(country)
    idx = loader.state_index()

    if iso3166_2 is None and state_code is None and name is None:
        if key is None:
            raise StateNotFound("give a key, iso3166_2, state_code or name")
        if isinstance(key, State):
            return key
        if isinstance(key, int):
            state = idx["id"].get(key)
            if state is None or state.country_iso2 != c.iso2:
                raise StateNotFound("no state {} in {}".format(key, c.iso2))
            return state
        # A bare string is tried against every tier, most specific first.
        text = str(key).strip()
        for candidate in (
            idx["iso3166_2"].get(text.upper()),
            idx["iso3166_2"].get("{}-{}".format(c.iso2, text).upper()),
        ):
            if candidate is not None and candidate.country_iso2 == c.iso2:
                return candidate
        for bucket in (
            idx["code"].get((c.iso2, text.upper())),
            idx["name"].get((c.iso2, normalize_name(text))),
        ):
            if bucket:
                if len(bucket) > 1:
                    raise Ambiguous(
                        "{!r} matches {} states in {}: {}".format(
                            key, len(bucket), c.iso2,
                            ", ".join(sorted(s.iso3166_2 or s.name for s in bucket)),
                        )
                    )
                return bucket[0]
        raise StateNotFound("no state {!r} in {}".format(key, c.iso2))

    if iso3166_2 is not None:
        text = str(iso3166_2).upper()
        state = idx["iso3166_2"].get(text) or idx["iso3166_2"].get(
            "{}-{}".format(c.iso2, text)
        )
        if state is None or state.country_iso2 != c.iso2:
            raise StateNotFound("no state with iso3166_2 {!r} in {}".format(iso3166_2, c.iso2))
        return state

    bucket = (
        idx["code"].get((c.iso2, str(state_code).upper()))
        if state_code is not None
        else idx["name"].get((c.iso2, normalize_name(name)))
    )
    if not bucket:
        raise StateNotFound(
            "no state with {}={!r} in {}".format(
                "state_code" if state_code is not None else "name",
                state_code if state_code is not None else name,
                c.iso2,
            )
        )
    if len(bucket) > 1:
        raise Ambiguous(
            "{} states in {} match: {}".format(
                len(bucket), c.iso2, ", ".join(sorted(s.iso3166_2 or s.name for s in bucket))
            )
        )
    return bucket[0]


def state_tree(country) -> Tuple[StateNode, ...]:
    """Subdivisions as a forest, roots first.

    >>> [node.state.name for node in state_tree("GB")]
    ['England', 'Northern Ireland', 'Scotland', 'Wales']
    """
    c = get_country(country)
    children = loader.state_index()["children"]

    def build(state):
        kids = sorted(
            (s for s in children.get(state.id, []) if s.country_iso2 == c.iso2),
            key=lambda s: s.name,
        )
        return StateNode(state=state, children=tuple(build(k) for k in kids))

    return tuple(build(s) for s in root_states(c))


def subdivision_twin(country):
    """For a multi-level territory, the state row it also exists as.

    >>> subdivision_twin("MQ").country_iso2
    'FR'

    Returns None for the 229 countries that are only countries.
    """
    c = get_country(country)
    if c.also_subdivision_of is None:
        return None
    return loader.state_index()["id"].get(c.also_subdivision_of.state_id)


# --------------------------------------------------------------------- cities


def cities_of(country=None, state=None, limit=None):
    """Cities in a country, or in one state. Triggers the cities load.

    >>> len(cities_of("NG", state="Lagos")) > 0
    True
    """
    if country is None and state is None:
        raise ValueError("give a country or a state")

    if state is not None and isinstance(state, State):
        rows = loader.city_index()["state"].get(state.id, [])
    elif state is not None:
        s = get_state(country, state)
        rows = loader.city_index()["state"].get(s.id, [])
    else:
        c = get_country(country)
        rows = loader.city_index()["country"].get(c.iso2, [])

    rows = sorted(rows, key=lambda c: c.name)
    return tuple(rows[:limit] if limit else rows)


def get_city(country, state, name) -> City:
    """Exact city lookup within a state."""
    matches = [c for c in cities_of(country, state) if c.normalized_name == normalize_name(name)]
    if not matches:
        raise CityNotFound("no city {!r} in that state".format(name))
    if len(matches) > 1:
        raise Ambiguous("{} cities match {!r}".format(len(matches), name))
    return matches[0]


def search_cities(query, country=None, limit=25):
    """Prefix search over city names, exact matches first.

    Accent- and case-insensitive via the shared normalizer, so 'sao paulo'
    finds 'São Paulo'.
    """
    needle = normalize_name(query)
    if not needle:
        return ()

    pool = (
        loader.city_index()["country"].get(get_country(country).iso2, [])
        if country
        else loader.cities()
    )
    exact, prefix, contains = [], [], []
    for c in pool:
        n = c.normalized_name
        if n == needle:
            exact.append(c)
        elif n.startswith(needle):
            prefix.append(c)
        elif needle in n:
            contains.append(c)
        if len(exact) >= limit:
            break

    out = exact + sorted(prefix, key=lambda c: c.name) + sorted(contains, key=lambda c: c.name)
    return tuple(out[:limit])


# ------------------------------------------------------------------ languages


def languages(standard=None) -> Tuple[Language, ...]:
    """The ISO 639 table, sorted by name.

    standard='iso639_1' gives the 184 two-letter codes -- the ones translation
    keys actually use; 'iso639_2' gives the 236 three-letter codes.
    """
    rows = loader.languages()
    if standard is not None:
        rows = [l for l in rows if l.standard == standard]
    return tuple(sorted(rows, key=lambda l: l.name))


def get_language(key) -> Language:
    """Look a language up by code or English name. Raises if there is no match.

    >>> get_language("pt").name
    'Portuguese'
    >>> get_language("pt-BR") is get_language("pt")   # region subtag ignored
    True
    """
    lang = find_language(key)
    if lang is None:
        raise LanguageNotFound("no language matches {!r}".format(key))
    return lang


def find_language(key) -> Optional[Language]:
    """Like `get_language` but returns None instead of raising.

    Accepts a bare code (`pt`), a BCP-47 tag (`pt-BR`, `zh-Hans-CN`) or an
    English name. Only the primary subtag is matched: this table describes
    languages, not regional variants, so `pt-BR` and `pt` are the same row.
    """
    if isinstance(key, Language):
        return key
    text = str(key or "").strip()
    if not text:
        return None
    idx = loader.language_index()
    primary = text.split("-")[0].split("_")[0].lower()
    return idx["code"].get(primary) or idx["name"].get(normalize_name(text))


def translations_of(record):
    """Translated names for a country or state, as {locale: name}.

    Locales are BCP-47 tags, so `pt` and `pt-BR` can both be present and mean
    different strings. Resolve a tag to a Language with `get_language`.

    Returns an empty dict for records upstream has no translations for -- 12
    states and any city (cities are not translated at all).
    """
    if isinstance(record, Country):
        return dict(loader.country_translations().get(record.iso2, {}))
    if isinstance(record, State):
        return dict(loader.state_translations().get(record.id, {}))
    if isinstance(record, City):
        return {}
    raise TypeError("translations_of expects a Country or State, got {!r}".format(type(record)))


def localized_name(record, language, default=None):
    """The record's name in `language`, or `default` if it is not translated.

    Falls back from a regional tag to its base language -- asking for `pt-BR`
    where only `pt` exists returns the Portuguese name rather than nothing,
    which is the behaviour a UI wants. `default=None` means "fall back to the
    caller's own choice"; pass `record.name` for the English name.

    >>> localized_name(get_country("DE"), "fr")
    'Allemagne'
    """
    table = translations_of(record)
    if not table:
        return default
    tag = str(language.code if isinstance(language, Language) else language or "").strip()
    if tag in table:
        return table[tag]
    lang = find_language(tag)
    if lang is None:
        return default
    if lang.code in table:
        return table[lang.code]
    # The requested language exists but only in a regional variant (`zh` asked
    # for, `zh-CN` shipped). One variant is better than no name at all.
    for key in sorted(table):
        if key.split("-")[0].lower() == lang.code:
            return table[key]
    return default
