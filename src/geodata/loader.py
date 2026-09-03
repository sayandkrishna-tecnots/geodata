"""Lazy, memoized loading of the canonical dataset.

Importing `geodata` must not pull 41 MB of cities into memory. Countries and
states load on first use; cities load only when a cities query is actually
made, and the loaders are keyed so the cost is paid once per process.
"""

import gzip
import json
import os
import threading

from .normalize import normalize_name
from .types import City, Country, Language, State, SubdivisionLink, Timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
# During development the data lives in the repo; a packaged build ships it
# inside the package directory.
_CANDIDATES = (
    os.path.join(_HERE, "data"),
    os.path.join(_HERE, "..", "..", "data", "canonical"),
)

# Reentrant: an index builder calls the table loader, which re-enters the
# memoizer. A plain Lock deadlocks the first time an index is built.
_lock = threading.RLock()
_cache = {}


def data_dir():
    for path in _CANDIDATES:
        if os.path.isdir(path) and (
            os.path.exists(os.path.join(path, "countries.ndjson"))
            or os.path.exists(os.path.join(path, "countries.ndjson.gz"))
        ):
            return os.path.abspath(path)
    raise RuntimeError(
        "geodata cannot find its dataset. Looked in:\n  "
        + "\n  ".join(os.path.abspath(p) for p in _CANDIDATES)
    )


def _read(name):
    base = os.path.join(data_dir(), name + ".ndjson")
    if os.path.exists(base):
        with open(base, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    with gzip.open(base + ".gz", "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _memoize(key, build):
    got = _cache.get(key)
    if got is not None:
        return got
    with _lock:
        got = _cache.get(key)
        if got is None:
            got = build()
            _cache[key] = got
    return got


def _country(row):
    link = row.get("also_subdivision_of")
    return Country(
        timezones=tuple(Timezone(**tz) for tz in row.get("timezones") or ()),
        also_subdivision_of=SubdivisionLink(**link) if link else None,
        **{k: v for k, v in row.items() if k not in ("timezones", "also_subdivision_of")}
    )


def countries():
    return _memoize("countries", lambda: tuple(_country(r) for r in _read("countries")))


def states():
    return _memoize("states", lambda: tuple(State(**r) for r in _read("states")))


def cities():
    """Loads ~153k rows. Only a cities query should trigger this."""
    return _memoize("cities", lambda: tuple(City(**r) for r in _read("cities")))


def languages():
    """420 ISO 639 rows, ~42 KB. Cheap enough to load on first touch."""
    return _memoize("languages", lambda: tuple(Language(**r) for r in _read("languages")))


def country_translations():
    """iso2 -> {locale: name}. Separate artifact, so pay for it only if asked."""
    def build():
        return {
            row["iso2"]: row["translations"]
            for row in _read("translations.countries")
        }

    return _memoize("translations.countries", build)


def state_translations():
    """state id -> {locale: name}.

    Keyed by upstream id because that is what the artifact carries; every
    caller reaches it through a State object, never by persisting the key.
    """
    def build():
        return {row["state_id"]: row["translations"] for row in _read("translations.states")}

    return _memoize("translations.states", build)


def cities_loaded():
    """True if the cities table has been paid for in this process."""
    return "cities" in _cache


# ------------------------------------------------------------------ indexes


def country_index():
    def build():
        by_iso2, by_iso3, by_numeric, by_id, by_name = {}, {}, {}, {}, {}
        # Native names are a separate, lower-priority index: people type
        # "Deutschland" and "Cote d'Ivoire", and a native name occasionally
        # collides with another country's English name, so it must not win.
        by_native = {}
        for c in countries():
            by_iso2[c.iso2] = c
            by_id[c.id] = c
            by_name.setdefault(c.normalized_name, c)
            if c.native:
                by_native.setdefault(normalize_name(c.native), c)
            if c.iso3:
                by_iso3[c.iso3] = c
            if c.numeric_code:
                by_numeric[c.numeric_code.lstrip("0") or "0"] = c
        return {
            "iso2": by_iso2, "iso3": by_iso3, "numeric": by_numeric,
            "id": by_id, "name": by_name, "native": by_native,
        }

    return _memoize("country_index", build)


def language_index():
    def build():
        by_code, by_name = {}, {}
        for lang in languages():
            by_code[lang.code] = lang
            # Two-letter codes win a name collision: "Greek" is both `el` and
            # `grc` (Ancient Greek) in some vintages of this list, and callers
            # asking by name mean the living language.
            existing = by_name.get(lang.normalized_name)
            if existing is None or (lang.is_iso639_1 and not existing.is_iso639_1):
                by_name[lang.normalized_name] = lang
        return {"code": by_code, "name": by_name}

    return _memoize("language_index", build)


def state_index():
    def build():
        by_id, by_country, by_iso3166_2, by_code, by_name, children = (
            {}, {}, {}, {}, {}, {}
        )
        for s in states():
            by_id[s.id] = s
            by_country.setdefault(s.country_iso2, []).append(s)
            if s.iso3166_2:
                by_iso3166_2[s.iso3166_2.upper()] = s
            if s.state_code:
                by_code.setdefault((s.country_iso2, s.state_code.upper()), []).append(s)
            by_name.setdefault((s.country_iso2, s.normalized_name), []).append(s)
            children.setdefault(s.parent_id, []).append(s)
        return {
            "id": by_id, "country": by_country, "iso3166_2": by_iso3166_2,
            "code": by_code, "name": by_name, "children": children,
        }

    return _memoize("state_index", build)


def city_index():
    def build():
        by_id, by_state, by_country, by_name = {}, {}, {}, {}
        for c in cities():
            by_id[c.id] = c
            by_state.setdefault(c.state_id, []).append(c)
            by_country.setdefault(c.country_iso2, []).append(c)
            by_name.setdefault(c.normalized_name, []).append(c)
        return {"id": by_id, "state": by_state, "country": by_country, "name": by_name}

    return _memoize("city_index", build)


def reset():
    """Drop every cache. Tests use this; applications should not need it."""
    with _lock:
        _cache.clear()
