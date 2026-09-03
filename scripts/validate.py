#!/usr/bin/env python3
"""Hard CI gate over data/canonical/ (Decision 5).

    python3 scripts/validate.py              # all checks, exit 1 on any failure
    python3 scripts/validate.py --json       # machine-readable report
    python3 scripts/validate.py --accept-churn "reason"   # allow a large delta

Nine checks, in the order the plan lists them:

  1. zero orphan foreign keys        <- the check the old mirror data failed
  2. schema conformance
  3. uniqueness of identities
  4. coordinate sanity
  5. parent_id resolves, acyclic, level/depth agreement (level is advisory)
  6. counts within tolerance of the last release
  7. encoding hygiene
  8. has_states / has_cities agree with the actual relations
  9. the language table, and that every translation locale resolves into it

Failures block the build. Warnings are printed and counted but do not.
"""

import argparse
import collections
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.lib.normalize import has_html_entity, has_mojibake, normalize_name

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANON = os.path.join(ROOT, "data", "canonical")
SCHEMA = os.path.join(ROOT, "schema")
CACHE = os.path.join(ROOT, ".cache", "upstream")
RELEASE = os.path.join(ROOT, "data", "RELEASE.json")

# Decision 6 thresholds.
MAX_NET_REMOVAL_PCT = 2.0
MAX_COUNTRY_REMOVAL_PCT = 10.0

# A city more than this far outside its country's bounding box is suspicious.
BBOX_SLACK_KM = 500.0


class Report(object):
    def __init__(self):
        self.checks = []

    def add(self, name, failures, warnings=None, detail=None):
        self.checks.append(
            {
                "check": name,
                "failures": failures or [],
                "warnings": warnings or [],
                "detail": detail or {},
            }
        )

    @property
    def failed(self):
        return any(c["failures"] for c in self.checks)

    def render(self):
        lines = []
        for c in self.checks:
            nf, nw = len(c["failures"]), len(c["warnings"])
            status = "FAIL" if nf else ("warn" if nw else "ok")
            lines.append(
                "[{:>4}] {:<44} {}".format(
                    status,
                    c["check"],
                    ", ".join(
                        "{}={}".format(k, v) for k, v in sorted(c["detail"].items())
                    )
                    or "",
                )
            )
            for f in c["failures"][:12]:
                lines.append("        FAIL  " + f)
            if nf > 12:
                lines.append("        ... and {} more failures".format(nf - 12))
            for w in c["warnings"][:6]:
                lines.append("        warn  " + w)
            if nw > 6:
                lines.append("        ... and {} more warnings".format(nw - 6))
        return "\n".join(lines)


def read_ndjson(name):
    path = os.path.join(CANON, name + ".ndjson")
    if not os.path.exists(path):
        raise SystemExit("missing {} -- run scripts/build_canonical.py first".format(path))
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def bbox_distance_km(lat, lng, b):
    """Distance from a point to a country bounding box, 0 if inside.

    Handles boxes that cross the antimeridian, where `max_lng < min_lng`
    (Russia spans 19.64E to 169.05W, Fiji and New Zealand similarly). Clamping
    naively against such a box puts every Russian city ~10,000 km "outside" it.
    """
    lo, hi = b["min_lng"], b["max_lng"]
    if lo <= hi:
        inside_lng = lo <= lng <= hi
        clng = min(max(lng, lo), hi)
    else:  # wraps the antimeridian
        inside_lng = lng >= lo or lng <= hi
        clng = lng if inside_lng else (lo if abs(lng - lo) < abs(lng - hi) else hi)
    clat = min(max(lat, b["min_lat"]), b["max_lat"])
    if inside_lng and clat == lat:
        return 0.0
    return haversine_km(lat, lng, clat, clng)


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ------------------------------------------------------------------ check 1


def check_orphan_fks(report, countries, states, cities):
    country_ids = {c["id"] for c in countries}
    state_ids = {s["id"] for s in states}
    failures = []

    bad_states = [s for s in states if s["country_id"] not in country_ids]
    for s in bad_states[:50]:
        failures.append(
            "state {} ({}) -> missing country_id {}".format(s["id"], s["name"], s["country_id"])
        )

    bad_city_state = [c for c in cities if c["state_id"] not in state_ids]
    for c in bad_city_state[:50]:
        failures.append(
            "city {} ({}) -> missing state_id {}".format(c["id"], c["name"], c["state_id"])
        )

    bad_city_country = [c for c in cities if c["country_id"] not in country_ids]
    for c in bad_city_country[:50]:
        failures.append(
            "city {} ({}) -> missing country_id {}".format(c["id"], c["name"], c["country_id"])
        )

    # A city's state must belong to the city's country. The multi-level
    # territory policy means a territory's cities live under the territory's
    # own states, so this should hold with no exceptions.
    state_country = {s["id"]: s["country_id"] for s in states}
    mismatched = [
        c
        for c in cities
        if c["state_id"] in state_country and state_country[c["state_id"]] != c["country_id"]
    ]
    for c in mismatched[:50]:
        failures.append(
            "city {} ({}) country_id {} but state {} belongs to country {}".format(
                c["id"], c["name"], c["country_id"], c["state_id"], state_country[c["state_id"]]
            )
        )

    report.add(
        "1. zero orphan foreign keys",
        failures,
        detail={
            "orphan_states": len(bad_states),
            "orphan_city_state": len(bad_city_state),
            "orphan_city_country": len(bad_city_country),
            "cross_country_state": len(mismatched),
        },
    )


# ------------------------------------------------------------------ check 2


def check_schema(report, datasets):
    try:
        import jsonschema
    except ImportError:
        report.add(
            "2. schema conformance",
            [],
            ["jsonschema not installed -- check skipped (pip install jsonschema)"],
        )
        return

    failures = []
    checked = 0
    for entity, rows in datasets:
        with open(os.path.join(SCHEMA, entity + ".schema.json"), encoding="utf-8") as fh:
            schema = json.load(fh)
        validator = jsonschema.Draft202012Validator(schema)
        for row in rows:
            checked += 1
            for err in validator.iter_errors(row):
                failures.append(
                    "{} id={}: {} at {}".format(
                        entity,
                        row.get("id"),
                        err.message,
                        "/".join(str(p) for p in err.absolute_path) or "<root>",
                    )
                )
                if len(failures) > 200:
                    break
            if len(failures) > 200:
                break
    report.add("2. schema conformance", failures, detail={"rows_checked": checked})


# ------------------------------------------------------------------ check 3


def check_uniqueness(report, countries, states, cities):
    failures = []

    def dupes(rows, key, label, skip_null=False):
        seen = collections.defaultdict(list)
        for r in rows:
            v = r.get(key)
            if skip_null and v in (None, ""):
                continue
            seen[v].append(r.get("id"))
        out = {k: v for k, v in seen.items() if len(v) > 1}
        for k, ids in list(out.items())[:20]:
            failures.append("duplicate {} {}={!r} on ids {}".format(label, key, k, ids[:6]))
        return len(out)

    n = {}
    n["country_id"] = dupes(countries, "id", "country")
    n["country_iso2"] = dupes(countries, "iso2", "country")
    n["country_iso3"] = dupes(countries, "iso3", "country", skip_null=True)
    n["country_numeric"] = dupes(countries, "numeric_code", "country", skip_null=True)
    n["state_id"] = dupes(states, "id", "state")
    n["city_id"] = dupes(cities, "id", "city")

    # (country_iso2, iso3166_2) must be unique where iso3166_2 is present
    seen = collections.defaultdict(list)
    for s in states:
        if s.get("iso3166_2"):
            seen[(s["country_iso2"], s["iso3166_2"])].append(s["id"])
    dup_iso = {k: v for k, v in seen.items() if len(v) > 1}
    for k, ids in list(dup_iso.items())[:20]:
        failures.append("duplicate state iso3166_2 {} on ids {}".format(k, ids[:6]))
    n["state_iso3166_2"] = len(dup_iso)

    # stable keys are the identity -- they must not collide
    for label, rows in (("country", countries), ("state", states), ("city", cities)):
        seen = collections.defaultdict(list)
        for r in rows:
            seen[r["stable_key"]].append(r["id"])
        dup = {k: v for k, v in seen.items() if len(v) > 1}
        for k, ids in list(dup.items())[:20]:
            failures.append("duplicate {} stable_key {!r} on ids {}".format(label, k, ids[:6]))
        n[label + "_stable_key"] = len(dup)

    report.add("3. uniqueness of identities", failures, detail=n)


# ------------------------------------------------------------------ check 4


def check_coordinates(report, countries, states, cities):
    failures = []
    warnings = []

    bounds = {}
    bounds_path = os.path.join(CACHE, "country_bounds.json")
    if os.path.exists(bounds_path):
        with open(bounds_path, encoding="utf-8") as fh:
            raw = json.load(fh)
        entries = raw.get("bounds", raw) if isinstance(raw, dict) else raw
        if isinstance(entries, dict):
            for iso2, b in entries.items():
                # upstream uses camelCase: minLat / maxLat / minLon / maxLon
                if isinstance(b, dict) and {"minLat", "maxLat", "minLon", "maxLon"} <= set(b):
                    bounds[iso2.upper()] = {
                        "min_lat": b["minLat"],
                        "max_lat": b["maxLat"],
                        "min_lng": b["minLon"],
                        "max_lng": b["maxLon"],
                    }

    for label, rows in (("country", countries), ("state", states), ("city", cities)):
        for r in rows:
            lat, lng = r.get("latitude"), r.get("longitude")
            if lat is None or lng is None:
                continue
            if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
                failures.append(
                    "{} {} ({}) out of range: {},{}".format(label, r["id"], r["name"], lat, lng)
                )
            elif lat == 0 and lng == 0:
                # Null Island is never a real populated place in this dataset.
                failures.append("{} {} ({}) sits at 0,0".format(label, r["id"], r["name"]))

    outside = 0
    if bounds:
        by_country = collections.defaultdict(list)
        for c in cities:
            lat, lng = c.get("latitude"), c.get("longitude")
            b = bounds.get(c["country_iso2"])
            if lat is None or lng is None or not b:
                continue
            km = bbox_distance_km(lat, lng, b)
            if km > BBOX_SLACK_KM:
                outside += 1
                by_country[c["country_iso2"]].append((km, c))

        # A country with hundreds of outliers almost always has a bounding box
        # that excludes its outlying regions (US/Hawaii, ES/Canaries,
        # PT/Azores) -- that is a limitation of the reference bbox, not bad
        # city data. A country with one or two is the interesting case, so
        # report ascending by count and name the worst offender in each.
        for iso2, hits in sorted(by_country.items(), key=lambda kv: (len(kv[1]), kv[0])):
            hits.sort(reverse=True, key=lambda h: h[0])
            km, c = hits[0]
            warnings.append(
                "{}: {} cit{} >{:.0f} km outside the country bbox; farthest is "
                "{} (id {}) at {},{} -- {:.0f} km".format(
                    iso2, len(hits), "y" if len(hits) == 1 else "ies",
                    BBOX_SLACK_KM, c["name"], c["id"], c["latitude"], c["longitude"], km,
                )
            )
    else:
        warnings.append("no country bounds available -- bbox sub-check skipped")

    missing_state_coords = sum(1 for s in states if s.get("latitude") is None)
    report.add(
        "4. coordinate sanity",
        failures,
        warnings,
        detail={
            "cities_outside_bbox": outside,
            "states_without_coords": missing_state_coords,
            "bounds_countries": len(bounds),
        },
    )


# ------------------------------------------------------------------ check 5


def check_hierarchy(report, states):
    failures = []
    warnings = []
    by_id = {s["id"]: s for s in states}

    unresolved = [s for s in states if s["parent_id"] is not None and s["parent_id"] not in by_id]
    for s in unresolved[:20]:
        failures.append("state {} ({}) parent_id {} does not resolve".format(s["id"], s["name"], s["parent_id"]))

    cycles = 0
    for s in states:
        seen = {s["id"]}
        cur = s
        while cur["parent_id"] is not None:
            nxt = by_id.get(cur["parent_id"])
            if nxt is None:
                break
            if nxt["id"] in seen:
                cycles += 1
                if cycles <= 20:
                    failures.append(
                        "parent_id cycle involving state {} ({} {})".format(
                            s["id"], s["country_iso2"], s["name"]
                        )
                    )
                break
            seen.add(nxt["id"])
            cur = nxt

    cross_country = [
        s
        for s in states
        if s["parent_id"] is not None
        and s["parent_id"] in by_id
        and by_id[s["parent_id"]]["country_iso2"] != s["country_iso2"]
    ]
    for s in cross_country[:20]:
        failures.append(
            "state {} ({}) has a parent in a different country ({})".format(
                s["id"], s["name"], by_id[s["parent_id"]]["country_iso2"]
            )
        )

    # `level` is advisory (see build_canonical.py). Disagreement with the
    # computed depth is reported, not fatal.
    level_mismatch = [
        s for s in states if s.get("level") is not None and s["level"] != s["depth"]
    ]
    if level_mismatch:
        by_country = collections.Counter(s["country_iso2"] for s in level_mismatch)
        warnings.append(
            "{} states where upstream `level` != computed `depth` (advisory field); "
            "top: {}".format(
                len(level_mismatch),
                ", ".join("{}={}".format(k, v) for k, v in by_country.most_common(5)),
            )
        )

    bad_depth = [s for s in states if s["parent_id"] is None and s["depth"] != 1]
    for s in bad_depth[:10]:
        failures.append("state {} ({}) is a root but depth={}".format(s["id"], s["name"], s["depth"]))

    report.add(
        "5. parent_id resolves, acyclic",
        failures,
        warnings,
        detail={
            "roots": sum(1 for s in states if s["parent_id"] is None),
            "max_depth": max(s["depth"] for s in states) if states else 0,
            "cycles": cycles,
            "level_vs_depth_mismatch": len(level_mismatch),
        },
    )


# ------------------------------------------------------------------ check 6


def check_counts(report, countries, states, cities, accept_churn):
    counts = {"countries": len(countries), "states": len(states), "cities": len(cities)}
    failures = []
    warnings = []

    if not os.path.exists(RELEASE):
        warnings.append(
            "no data/RELEASE.json -- first build, nothing to compare against. "
            "It is written by the release step."
        )
        report.add("6. counts within tolerance", [], warnings, detail=counts)
        return

    with open(RELEASE, encoding="utf-8") as fh:
        prev = json.load(fh)
    prev_counts = prev.get("counts", {})
    prev_by_country = prev.get("cities_by_country", {})

    for entity, now in counts.items():
        before = prev_counts.get(entity)
        if not before:
            continue
        delta_pct = (before - now) / float(before) * 100.0
        if delta_pct > MAX_NET_REMOVAL_PCT:
            msg = "{}: {} -> {} ({:.1f}% net removal, limit {:.1f}%)".format(
                entity, before, now, delta_pct, MAX_NET_REMOVAL_PCT
            )
            (warnings if accept_churn else failures).append(msg)

    now_by_country = collections.Counter(c["country_iso2"] for c in cities)
    for iso2, before in prev_by_country.items():
        now = now_by_country.get(iso2, 0)
        if not before:
            continue
        delta_pct = (before - now) / float(before) * 100.0
        if delta_pct > MAX_COUNTRY_REMOVAL_PCT:
            msg = "cities/{}: {} -> {} ({:.1f}% removal, limit {:.1f}%)".format(
                iso2, before, now, delta_pct, MAX_COUNTRY_REMOVAL_PCT
            )
            (warnings if accept_churn else failures).append(msg)

    if failures:
        failures.append(
            "re-run with --accept-churn '<written justification>' once the churn "
            "report has been reviewed (Decision 6)"
        )
    report.add("6. counts within tolerance", failures, warnings, detail=counts)


# ------------------------------------------------------------------ check 7

_LEADING_TRAILING_WS = re.compile(r"^\s|\s$")


def check_encoding(report, datasets):
    failures = []
    warnings = []
    text_fields = ("name", "native", "capital", "type", "currency_name", "nationality")
    for entity, rows in datasets:
        for r in rows:
            for field in text_fields:
                v = r.get(field)
                if not isinstance(v, str):
                    continue
                if has_mojibake(v):
                    failures.append("{} {} {}={!r} looks like mojibake".format(entity, r["id"], field, v))
                if has_html_entity(v):
                    failures.append("{} {} {}={!r} contains an HTML entity".format(entity, r["id"], field, v))
                if _LEADING_TRAILING_WS.search(v):
                    failures.append("{} {} {}={!r} has edge whitespace".format(entity, r["id"], field, v))
                if "�" in v:
                    failures.append("{} {} {}={!r} contains U+FFFD".format(entity, r["id"], field, v))
            if r.get("name") and normalize_name(r["name"]) != r.get("normalized_name"):
                failures.append(
                    "{} {}: normalized_name {!r} does not match name {!r}".format(
                        entity, r["id"], r.get("normalized_name"), r["name"]
                    )
                )
            if len(failures) > 200:
                break
    report.add("7. encoding hygiene", failures, warnings)


# ------------------------------------------------------------------ check 8


def check_flags(report, countries, states, cities):
    failures = []
    states_per_country = collections.Counter(s["country_id"] for s in states)
    cities_per_country = collections.Counter(c["country_id"] for c in cities)
    cities_per_state = collections.Counter(c["state_id"] for c in cities)

    for c in countries:
        if c.get("state_count") != states_per_country.get(c["id"], 0):
            failures.append("country {} state_count is wrong".format(c["iso2"]))
        if c.get("city_count") != cities_per_country.get(c["id"], 0):
            failures.append("country {} city_count is wrong".format(c["iso2"]))
        if c.get("has_states") != (states_per_country.get(c["id"], 0) > 0):
            failures.append("country {} has_states disagrees with the data".format(c["iso2"]))
        if c.get("has_cities") != (cities_per_country.get(c["id"], 0) > 0):
            failures.append("country {} has_cities disagrees with the data".format(c["iso2"]))
    for s in states:
        if s.get("city_count") != cities_per_state.get(s["id"], 0):
            failures.append("state {} city_count is wrong".format(s["id"]))

    no_states = [c["iso2"] for c in countries if not c["has_states"]]
    no_cities = [c["iso2"] for c in countries if not c["has_cities"]]
    report.add(
        "8. has_states / has_cities agree",
        failures,
        detail={"countries_without_states": len(no_states), "countries_without_cities": len(no_cities)},
    )


# ------------------------------------------------------------------ overrides


# ------------------------------------------------------------------ check 9


def check_languages(report, languages):
    """The language table, and whether it can label every translation we ship.

    The translations artifacts are keyed by BCP-47 tags. A tag whose primary
    subtag is not in the language table is a key no consumer can render a label
    for, so a refresh that introduces one fails here rather than shipping it.
    Region subtags are stripped before the lookup: `pt-BR` is Portuguese, and
    this table deliberately does not enumerate regional variants.
    """
    failures = []
    warnings = []

    seen = {}
    for row in languages:
        code = row.get("code")
        if code in seen:
            failures.append("duplicate language code {!r}".format(code))
        seen[code] = row
        if row.get("stable_key") != code:
            failures.append(
                "language {!r}: stable_key {!r} must equal the code -- the code is "
                "the identity for this table".format(code, row.get("stable_key"))
            )
        expected = "iso639_1" if len(code or "") == 2 else "iso639_2"
        if row.get("standard") != expected:
            failures.append(
                "language {!r}: standard is {!r}, expected {!r} for a {}-letter "
                "code".format(code, row.get("standard"), expected, len(code or ""))
            )

    by_name = collections.defaultdict(list)
    for row in languages:
        by_name[row.get("normalized_name")].append(row.get("code"))
    for name, codes in sorted(by_name.items()):
        if len(codes) > 1:
            failures.append(
                "language name {!r} is shared by codes {}".format(name, ", ".join(sorted(codes)))
            )

    locales = collections.Counter()
    for artifact in ("translations.countries", "translations.states"):
        path = os.path.join(CANON, artifact + ".ndjson")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    locales.update(json.loads(line).get("translations", {}).keys())

    for tag in sorted(locales):
        primary = tag.split("-")[0].lower()
        if primary not in seen:
            failures.append(
                "translation locale {!r} has no language row for primary subtag "
                "{!r} -- add it to data/vendor/languages.json".format(tag, primary)
            )

    unused = len(seen) - len({t.split("-")[0].lower() for t in locales})
    if unused:
        warnings.append(
            "{} of {} languages are not used by any translation -- the table is a "
            "reference list, not a manifest of what we translate".format(unused, len(seen))
        )

    report.add(
        "9. languages + translation locales",
        failures,
        warnings,
        detail={"languages": len(languages), "locales": len(locales)},
    )


def check_retired_overrides(report):
    """Report overrides upstream has since adopted (Decision 4, rule 3)."""
    warnings = []
    path = os.path.join(ROOT, "data", "overrides")
    raw_states = None
    for entity, cache_name in (("states", "states"), ("countries", "countries")):
        f = os.path.join(path, entity + ".patch.ndjson")
        if not os.path.exists(f):
            continue
        with open(f, encoding="utf-8") as fh:
            patches = [json.loads(l) for l in fh if l.strip()]
        if not patches:
            continue
        cache_file = os.path.join(CACHE, cache_name + ".json")
        if not os.path.exists(cache_file):
            continue
        with open(cache_file, encoding="utf-8") as fh:
            raw = json.load(fh)
        by_id = {int(r["id"]): r for r in raw}
        for p in patches:
            match_id = p.get("_match", {}).get("id")
            if match_id is None:
                continue
            up = by_id.get(match_id)
            if up is None:
                continue
            fields = {k: v for k, v in p.items() if not k.startswith("_")}
            adopted = []
            for k, v in fields.items():
                uv = up.get(k)
                if uv is not None and not isinstance(uv, (dict, list)):
                    try:
                        uv = int(uv) if isinstance(v, int) else uv
                    except (TypeError, ValueError):
                        pass
                if uv == v:
                    adopted.append(k)
            if adopted and len(adopted) == len(fields):
                warnings.append(
                    "override {}#{} is retired -- upstream now agrees on {}".format(
                        entity, match_id, ", ".join(adopted)
                    )
                )
    report.add("overrides: retired?", [], warnings)
    return raw_states


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="emit the report as JSON")
    ap.add_argument(
        "--accept-churn",
        metavar="REASON",
        help="downgrade check 6 failures to warnings; the reason is recorded",
    )
    args = ap.parse_args()

    countries = read_ndjson("countries")
    states = read_ndjson("states")
    cities = read_ndjson("cities")
    regions = read_ndjson("regions")
    subregions = read_ndjson("subregions")
    languages = read_ndjson("languages")

    datasets = [
        ("country", countries),
        ("state", states),
        ("city", cities),
        ("region", regions),
        ("subregion", subregions),
        ("language", languages),
    ]

    report = Report()
    check_orphan_fks(report, countries, states, cities)
    check_schema(report, datasets)
    check_uniqueness(report, countries, states, cities)
    check_coordinates(report, countries, states, cities)
    check_hierarchy(report, states)
    check_counts(report, countries, states, cities, args.accept_churn)
    check_encoding(report, datasets)
    check_flags(report, countries, states, cities)
    check_languages(report, languages)
    check_retired_overrides(report)

    if args.json:
        print(json.dumps({"checks": report.checks, "failed": report.failed}, indent=2))
    else:
        print(report.render())
        total_f = sum(len(c["failures"]) for c in report.checks)
        total_w = sum(len(c["warnings"]) for c in report.checks)
        print("\n{}: {} failures, {} warnings".format(
            "FAILED" if report.failed else "PASSED", total_f, total_w
        ))
        if args.accept_churn:
            print("churn accepted: {}".format(args.accept_churn))
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
