#!/usr/bin/env python3
"""Map the pinned upstream export into the canonical flat NDJSON dataset.

Reads `.cache/upstream/*.json` (put there by `scripts/fetch.py`, hashes recorded
in `data/SOURCE.lock`) and writes `data/canonical/*.ndjson`.

What this step is responsible for:

  * flattening the nested `[{id, states:[{id, cities:[...]}]}]` shape into tables
    with explicit foreign keys (issue 11)
  * carrying the *full* upstream field set, including `type` / `level` /
    `parent_id` / `iso3166_2` / `timezone` (issue 6)
  * renaming `phonecode` -> `phone_code` (issue 10)
  * coercing upstream's stringly-typed ids, levels and coordinates
  * computing `normalized_name` / `stable_key` (Decision 2)
  * computing `depth` from the parent chain -- upstream's `level` is a semantic
    administrative level and does NOT track tree depth (see NOTE below)
  * attaching `also_subdivision_of` from data/curated (Decision 3)
  * applying data/overrides (Decision 4)
  * splitting `translations` into a separate optional artifact, so the base
    payload stays small enough for the npm entry point
  * emitting the ISO 639 language table from data/vendor, which is what gives
    the translation artifacts' BCP-47 keys a resolvable meaning

NOTE on `level` vs `depth`: the remediation plan assumed `level` is consistent
with parent depth. Measured against v3.2-export.7 it is not -- 999 states have a
`level` that differs from their computed depth (e.g. Belgian provinces are
`level=1` while sitting under a `level=1` region). `level` is therefore carried
through as an advisory upstream field and `depth`, computed here, is the
authoritative tree position. Validation reports the disagreement as a warning
rather than failing the build.

Usage:
    python3 scripts/build_canonical.py [--no-translations]
"""

import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.lib.normalize import clean_text, normalize_key, normalize_name

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache", "upstream")
OUT = os.path.join(ROOT, "data", "canonical")
OVERRIDES = os.path.join(ROOT, "data", "overrides")
CURATED = os.path.join(ROOT, "data", "curated")
# Committed inputs that are not part of the upstream export (see data/vendor/README.md).
VENDOR = os.path.join(ROOT, "data", "vendor")


# ---------------------------------------------------------------- helpers


def load_upstream(name):
    with open(os.path.join(CACHE, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


# Upstream occasionally stores the *string* "NULL" where it means null.
_NULL_SENTINELS = {"", "null", "NULL", "None", "N/A", "n/a", "-", "undefined"}


def as_text(value):
    """Upstream string, with null sentinels mapped to a real null."""
    if value is None:
        return None
    value = str(value).strip()
    return None if value in _NULL_SENTINELS else value


def as_int(value):
    if value is None or value in _NULL_SENTINELS:
        return None
    return int(value)


def as_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Records whose coordinates upstream left at exactly (0, 0). Null Island is in
# the Gulf of Guinea; no record in this dataset is genuinely there, so (0, 0)
# is a placeholder meaning "unknown", not a location. We null it rather than
# ship a coordinate that would put 22 Chinese cities in the Atlantic. Counted
# and reported by the build so the loss stays visible.
NULL_ISLAND_REJECTED = collections.Counter()


def coords(record, label, ident):
    lat = as_float(record.get("latitude"))
    lng = as_float(record.get("longitude"))
    if lat == 0.0 and lng == 0.0:
        NULL_ISLAND_REJECTED[label] += 1
        return None, None
    return lat, lng


def read_ndjson(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                rows.append(json.loads(line))
            except ValueError as exc:
                raise SystemExit("{}:{}: {}".format(path, lineno, exc))
    return rows


def write_ndjson(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            fh.write("\n")
    return os.path.getsize(path)


# ---------------------------------------------------------------- overrides


def apply_overrides(entity, rows):
    """Apply data/overrides/<entity>.patch.ndjson. Returns (rows, applied)."""
    path = os.path.join(OVERRIDES, entity + ".patch.ndjson")
    patches = read_ndjson(path)
    if not patches:
        return rows, []

    applied = []
    for i, patch in enumerate(patches, 1):
        for required in ("_reason", "_source", "_review"):
            if not patch.get(required):
                raise SystemExit(
                    "{} entry {}: missing {} (see data/overrides/README.md)".format(
                        path, i, required
                    )
                )
        match = patch.get("_match")
        if not match:
            raise SystemExit("{} entry {}: missing _match".format(path, i))
        op = patch.get("_op", "patch")
        fields = {k: v for k, v in patch.items() if not k.startswith("_")}

        hits = [r for r in rows if all(r.get(k) == v for k, v in match.items())]
        if op == "add":
            if hits:
                raise SystemExit("{} entry {}: _op=add but _match already exists".format(path, i))
            rows.append(fields)
            applied.append((op, match))
            continue
        if len(hits) != 1:
            raise SystemExit(
                "{} entry {}: _match {} hit {} records, expected exactly 1. "
                "The override is stale -- re-check it against the new upstream tag.".format(
                    path, i, match, len(hits)
                )
            )
        if op == "remove":
            rows.remove(hits[0])
        else:
            hits[0].update(fields)
        applied.append((op, match))
    return rows, applied


# ---------------------------------------------------------------- countries


def build_countries(raw, keep_translations):
    rows = []
    translations = []
    for c in raw:
        iso2 = (c.get("iso2") or "").strip().upper()
        name = clean_text(c.get("name"))
        country_lat, country_lng = coords(c, "countries", iso2)
        rows.append(
            {
                "id": as_int(c["id"]),
                "iso2": iso2,
                "iso3": (as_text(c.get("iso3")) or "").upper() or None,
                "numeric_code": as_text(c.get("numeric_code")),
                "name": name,
                "normalized_name": normalize_name(name),
                "native": clean_text(c.get("native")),
                "capital": clean_text(c.get("capital")),
                # issue 10: upstream calls this `phonecode`
                "phone_code": (str(c["phonecode"]).strip() if c.get("phonecode") else None),
                "currency": as_text(c.get("currency")),
                "currency_name": clean_text(c.get("currency_name")),
                "currency_symbol": as_text(c.get("currency_symbol")),
                "tld": as_text(c.get("tld")),
                "region": clean_text(c.get("region")),
                "region_id": as_int(c.get("region_id")),
                "subregion": clean_text(c.get("subregion")),
                "subregion_id": as_int(c.get("subregion_id")),
                "nationality": clean_text(c.get("nationality")),
                "population": as_int(c.get("population")),
                "gdp": as_int(c.get("gdp")),
                "area_sq_km": as_int(c.get("area_sq_km")),
                "postal_code_format": as_text(c.get("postal_code_format")),
                "postal_code_regex": as_text(c.get("postal_code_regex")),
                "latitude": country_lat,
                "longitude": country_lng,
                "emoji": as_text(c.get("emoji")),
                "emoji_unicode": as_text(c.get("emojiU")),
                "wikidata_id": as_text(c.get("wikiDataId")),
                "timezones": [
                    {
                        "zone_name": t.get("zoneName"),
                        "gmt_offset": t.get("gmtOffset"),
                        "gmt_offset_name": t.get("gmtOffsetName"),
                        "abbreviation": t.get("abbreviation"),
                        "tz_name": t.get("tzName"),
                    }
                    for t in (c.get("timezones") or [])
                ],
                "stable_key": iso2,
                "also_subdivision_of": None,  # filled in later from data/curated
            }
        )
        if keep_translations and c.get("translations"):
            translations.append({"iso2": iso2, "translations": c["translations"]})
    rows.sort(key=lambda r: r["iso2"])
    return rows, translations


# ---------------------------------------------------------------- states


def state_stable_suffix(iso3166_2, state_code, normalized):
    """Stable key tiers for a state, in the priority order of Decision 2."""
    if iso3166_2:
        return "iso:" + normalize_key(iso3166_2)
    if state_code:
        return "code:" + normalize_key(state_code)
    return "name:" + normalized.replace(" ", "-")


def build_states(raw, country_by_id, keep_translations):
    rows = []
    translations = []
    for s in raw:
        cid = as_int(s["country_id"])
        country = country_by_id.get(cid)
        iso2 = country["iso2"] if country else (s.get("country_code") or "").upper()
        name = clean_text(s.get("name"))
        normalized = normalize_name(name)
        iso3166_2 = as_text(s.get("iso3166_2"))
        state_code = as_text(s.get("iso2"))
        state_lat, state_lng = coords(s, "states", s["id"])
        rows.append(
            {
                "id": as_int(s["id"]),
                "country_id": cid,
                "country_iso2": iso2,
                "name": name,
                "normalized_name": normalized,
                "native": clean_text(s.get("native")),
                "state_code": state_code,
                "iso3166_2": iso3166_2,
                "fips_code": as_text(s.get("fips_code")),
                "type": clean_text(s.get("type")),
                "level": as_int(s.get("level")),
                "parent_id": as_int(s.get("parent_id")),
                "depth": None,  # computed after overrides
                "latitude": state_lat,
                "longitude": state_lng,
                "timezone": as_text(s.get("timezone")),
                "population": as_int(s.get("population")),
                "wikidata_id": as_text(s.get("wikiDataId")),
                "stable_key": "{}/{}".format(
                    iso2, state_stable_suffix(iso3166_2, state_code, normalized)
                ),
            }
        )
        if keep_translations and s.get("translations"):
            translations.append({"state_id": as_int(s["id"]), "translations": s["translations"]})
    rows.sort(key=lambda r: (r["country_iso2"], r["id"]))
    return rows, translations


def compute_depth(states):
    """Depth from the parent chain. Cycles raise -- overrides must fix them."""
    by_id = {s["id"]: s for s in states}
    for s in states:
        depth = 1
        seen = {s["id"]}
        cur = s
        while cur["parent_id"] is not None:
            parent = by_id.get(cur["parent_id"])
            if parent is None:
                raise SystemExit(
                    "state {} ({}) has unresolvable parent_id {}".format(
                        s["id"], s["name"], cur["parent_id"]
                    )
                )
            if parent["id"] in seen:
                raise SystemExit(
                    "parent_id cycle at state {} ({} {}). Add an override to "
                    "data/overrides/states.patch.ndjson.".format(s["id"], s["country_iso2"], s["name"])
                )
            seen.add(parent["id"])
            cur = parent
            depth += 1
        s["depth"] = depth


# ---------------------------------------------------------------- cities


def build_cities(combined, country_by_id, state_by_id):
    """Flatten country -> state -> city into a table with explicit FKs."""
    rows = []
    # Disambiguate cities that share a normalized name inside the same state.
    seen_key = collections.Counter()
    staged = []
    for c in combined:
        cid = as_int(c["id"])
        country = country_by_id.get(cid)
        if country is None:
            raise SystemExit("combined export has country id {} absent from countries.json".format(cid))
        for st in c.get("states") or []:
            sid = as_int(st["id"])
            state = state_by_id.get(sid)
            if state is None:
                raise SystemExit(
                    "combined export has state id {} ({}) absent from states.json".format(
                        sid, st.get("name")
                    )
                )
            for city in st.get("cities") or []:
                name = clean_text(city.get("name"))
                normalized = normalize_name(name)
                staged.append((cid, country, sid, state, city, name, normalized))

    for cid, country, sid, state, city, name, normalized in staged:
        city_lat, city_lng = coords(city, "cities", city["id"])
        base = "{}/{}".format(state["stable_key"], normalized.replace(" ", "-") or "unnamed")
        seen_key[base] += 1
        n = seen_key[base]
        rows.append(
            {
                "id": as_int(city["id"]),
                "state_id": sid,
                "country_id": cid,
                "country_iso2": country["iso2"],
                "state_code": state["state_code"],
                "state_iso3166_2": state["iso3166_2"],
                "name": name,
                "normalized_name": normalized,
                "latitude": city_lat,
                "longitude": city_lng,
                "timezone": as_text(city.get("timezone")),
                "stable_key": base if n == 1 else "{}#{}".format(base, n),
            }
        )
    rows.sort(key=lambda r: (r["country_iso2"], r["state_id"], r["id"]))
    return rows


# ---------------------------------------------------------------- languages


def build_languages(raw):
    """ISO 639 codes from data/vendor/languages.json.

    This table has no upstream integer id and does not need one: the code *is*
    the identity, so `stable_key == code` and invariant 1 (ids churn) simply
    does not apply here. `standard` is derived from code length -- two letters
    is ISO 639-1, three is ISO 639-2/T -- which is the only classification the
    vendored file supports; it carries no scope or macrolanguage information.
    """
    rows = []
    for entry in raw:
        code = (entry.get("code") or "").strip().lower()
        name = clean_text(entry.get("name"))
        if not code or not name:
            raise SystemExit(
                "data/vendor/languages.json: entry {!r} is missing code or name".format(entry)
            )
        rows.append(
            {
                "code": code,
                "name": name,
                "normalized_name": normalize_name(name),
                "standard": "iso639_1" if len(code) == 2 else "iso639_2",
                "stable_key": code,
            }
        )
    rows.sort(key=lambda r: r["code"])
    return rows


# ---------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--no-translations",
        action="store_true",
        help="skip the translations artifact entirely",
    )
    args = ap.parse_args()
    keep_translations = not args.no_translations

    print("reading upstream cache ...")
    raw_countries = load_upstream("countries")
    raw_states = load_upstream("states")
    raw_regions = load_upstream("regions")
    raw_subregions = load_upstream("subregions")
    raw_combined = load_upstream("combined")
    with open(os.path.join(VENDOR, "languages.json"), encoding="utf-8") as fh:
        raw_languages = json.load(fh)

    countries, country_translations = build_countries(raw_countries, keep_translations)
    countries, applied_c = apply_overrides("countries", countries)
    country_by_id = {c["id"]: c for c in countries}

    states, state_translations = build_states(raw_states, country_by_id, keep_translations)
    states, applied_s = apply_overrides("states", states)
    compute_depth(states)
    state_by_id = {s["id"]: s for s in states}

    # also_subdivision_of (Decision 3) -- validated against the real state rows
    curated = read_ndjson(os.path.join(CURATED, "multi_level_territories.ndjson"))
    country_by_iso2 = {c["iso2"]: c for c in countries}
    for entry in curated:
        target = country_by_iso2.get(entry["country_iso2"])
        if target is None:
            raise SystemExit(
                "curated multi-level territory {} is not a country at this tag".format(
                    entry["country_iso2"]
                )
            )
        state = state_by_id.get(entry["state_id"])
        if state is None:
            raise SystemExit(
                "curated multi-level territory {}: state id {} no longer exists. "
                "Re-read MULTI_LEVEL_TERRITORIES.md at the new tag.".format(
                    entry["country_iso2"], entry["state_id"]
                )
            )
        if state["country_iso2"] != entry["parent_iso2"]:
            raise SystemExit(
                "curated multi-level territory {}: state {} now belongs to {}, "
                "not {}.".format(
                    entry["country_iso2"], entry["state_id"], state["country_iso2"],
                    entry["parent_iso2"],
                )
            )
        target["also_subdivision_of"] = {
            "country_iso2": entry["parent_iso2"],
            "state_id": entry["state_id"],
            "state_stable_key": state["stable_key"],
            "iso3166_2": state["iso3166_2"],
            "type": state["type"],
        }

    cities = build_cities(raw_combined, country_by_id, state_by_id)
    cities, applied_ct = apply_overrides("cities", cities)

    languages = build_languages(raw_languages)
    languages, applied_l = apply_overrides("languages", languages)
    languages.sort(key=lambda r: r["code"])

    regions = [
        {
            "id": as_int(r["id"]),
            "name": clean_text(r.get("name")),
            "normalized_name": normalize_name(r.get("name")),
            "wikidata_id": as_text(r.get("wikiDataId")),
        }
        for r in raw_regions
    ]
    subregions = [
        {
            "id": as_int(r["id"]),
            "name": clean_text(r.get("name")),
            "normalized_name": normalize_name(r.get("name")),
            "region_id": as_int(r.get("region_id")),
            "wikidata_id": as_text(r.get("wikiDataId")),
        }
        for r in raw_subregions
    ]

    # hasStates / hasCities, derived rather than trusted (validation check 8)
    states_per_country = collections.Counter(s["country_id"] for s in states)
    cities_per_country = collections.Counter(c["country_id"] for c in cities)
    cities_per_state = collections.Counter(c["state_id"] for c in cities)
    for c in countries:
        c["state_count"] = states_per_country.get(c["id"], 0)
        c["city_count"] = cities_per_country.get(c["id"], 0)
        c["has_states"] = c["state_count"] > 0
        c["has_cities"] = c["city_count"] > 0
    for s in states:
        s["city_count"] = cities_per_state.get(s["id"], 0)
        s["has_cities"] = s["city_count"] > 0

    outputs = [
        ("countries.ndjson", countries),
        ("states.ndjson", states),
        ("cities.ndjson", cities),
        ("regions.ndjson", regions),
        ("subregions.ndjson", subregions),
        ("languages.ndjson", languages),
    ]
    if keep_translations:
        outputs.append(("translations.countries.ndjson", country_translations))
        outputs.append(("translations.states.ndjson", state_translations))

    print("\nwriting {}/".format(os.path.relpath(OUT, ROOT)))
    for filename, rows in outputs:
        size = write_ndjson(os.path.join(OUT, filename), rows)
        print("  {:<32} {:>8,} rows  {:>10,} bytes".format(filename, len(rows), size))

    if NULL_ISLAND_REJECTED:
        print("\ncoordinates nulled (upstream had exactly 0,0):")
        for label, n in sorted(NULL_ISLAND_REJECTED.items()):
            print("  {:<12} {}".format(label, n))

    total_overrides = len(applied_c) + len(applied_s) + len(applied_ct) + len(applied_l)
    print("\noverrides applied: {}".format(total_overrides))
    print("multi-level territories linked: {}".format(len(curated)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
