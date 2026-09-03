#!/usr/bin/env python3
"""Diff two dataset versions by stable key and report what actually moved.

    python3 scripts/churn.py --from-legacy --from-label 2026.05 --to-label 2026.09
    python3 scripts/churn.py --from data/snapshots/2026.09 --to data/canonical

Writes:
    artifacts/CHURN.md                       human review document
    data/remap/<from>-<to>.ndjson            {entity, old_id, new_id, ...} per row

Why this exists (Decision 6): upstream ids are not stable. A refresh that
removes 6,321 city ids and re-parents 8,727 French cities is a *correction*,
but to an operator watching row counts it looks identical to data loss. This
turns that into a reviewed decision: every removal is attributed, every id that
moved gets a remap entry, and thresholds are enforced before release.

Matching is tiered, because the two sides may not agree on which stable-key
tier is available (the old mirror had no `iso3166_2`, so its states key on
`state_code`). Each record records *how* it matched, so a report reader can
tell a confident ISO-code match from a fuzzy name match.
"""

import argparse
import collections
import datetime
import gzip
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.lib.normalize import normalize_key, normalize_name

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANON = os.path.join(ROOT, "data", "canonical")
ARTIFACTS = os.path.join(ROOT, "artifacts")
REMAP = os.path.join(ROOT, "data", "remap")

MAX_NET_REMOVAL_PCT = 2.0
MAX_COUNTRY_REMOVAL_PCT = 10.0

# Breaches a human has reviewed and signed off, keyed by "<from>-<to>".
ACCEPTED = os.path.join(ROOT, "data", "CHURN_ACCEPTED.json")

# Two cities with the same name in the same state are the same city if their
# coordinates agree to roughly this distance.
SAME_PLACE_KM = 25.0


# ------------------------------------------------------------------ loading


def read_ndjson(path):
    """Read `<path>`, or `<path>.gz` if that is what exists.

    Released snapshots are stored gzipped; the working canonical set is not.
    """
    if not os.path.exists(path) and os.path.exists(path + ".gz"):
        with gzip.open(path + ".gz", "rt", encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_canonical(directory):
    return {
        "countries": read_ndjson(os.path.join(directory, "countries.ndjson")),
        "states": read_ndjson(os.path.join(directory, "states.ndjson")),
        "cities": read_ndjson(os.path.join(directory, "cities.ndjson")),
    }


def load_legacy(directory):
    """Read the pre-remediation mirror snapshot into canonical-ish records.

    The mirror shape is nested and field-poor, so this fills in only what the
    churn diff needs. Notably the mirror has no `iso3166_2`, which is why the
    state matcher has to fall back to `state_code`.
    """
    with open(os.path.join(directory, "countries.json"), encoding="utf-8") as fh:
        raw_countries = json.load(fh)
    with open(os.path.join(directory, "states.json"), encoding="utf-8") as fh:
        raw_states = json.load(fh)
    with open(os.path.join(directory, "cities.json"), encoding="utf-8") as fh:
        raw_cities = json.load(fh)

    countries = []
    iso2_by_id = {}
    for c in raw_countries:
        iso2 = (c.get("iso2") or "").upper()
        iso2_by_id[c["id"]] = iso2
        countries.append(
            {
                "id": c["id"],
                "iso2": iso2,
                "name": c.get("name"),
                "normalized_name": normalize_name(c.get("name")),
                "stable_key": iso2,
                "currency": c.get("currency"),
                "capital": c.get("capital"),
            }
        )

    states = []
    country_of_state = {}
    for entry in raw_states:
        iso2 = iso2_by_id.get(entry["id"], "")
        for s in entry.get("states") or []:
            country_of_state[s["id"]] = iso2
            states.append(
                {
                    "id": s["id"],
                    "country_iso2": iso2,
                    "name": s.get("name"),
                    "normalized_name": normalize_name(s.get("name")),
                    "state_code": s.get("state_code"),
                    "iso3166_2": None,  # the mirror dropped it
                    "latitude": s.get("latitude"),
                    "longitude": s.get("longitude"),
                }
            )

    cities = []
    for entry in raw_cities:
        iso2 = iso2_by_id.get(entry["id"], "")
        for s in entry.get("states") or []:
            for c in s.get("cities") or []:
                cities.append(
                    {
                        "id": c["id"],
                        "country_iso2": iso2,
                        "state_id": s["id"],
                        "name": c.get("name"),
                        "normalized_name": normalize_name(c.get("name")),
                        "latitude": c.get("latitude"),
                        "longitude": c.get("longitude"),
                    }
                )
    return {"countries": countries, "states": states, "cities": cities}


# ------------------------------------------------------------------ matching


def km(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    r = 6371.0088
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(float(lon2) - float(lon1)) / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def token_key(row):
    """Word-order-insensitive name key.

    Upstream fixed a family of article-inverted names in v3.2 ('Coruña A' ->
    'A Coruña', 'Ballestero El' -> 'El Ballestero'). Those are renames, and
    counting them as deletions would inflate the churn budget with work that
    was in fact a correction.
    """
    normalized = row.get("normalized_name")
    if not normalized:
        return None
    return (row.get("country_iso2") or row.get("iso2"), " ".join(sorted(normalized.split())))


def index(rows, keyfunc):
    out = collections.defaultdict(list)
    for r in rows:
        k = keyfunc(r)
        if k is not None:
            out[k].append(r)
    return out


def match_countries(old, new):
    """iso2 is the identity; the fallback is a rename with the same id."""
    by_iso2 = {c["iso2"]: c for c in new}
    by_id = {c["id"]: c for c in new}
    pairs, unmatched = [], []
    for c in old:
        hit = by_iso2.get(c["iso2"])
        if hit:
            pairs.append((c, hit, "iso2"))
            continue
        hit = by_id.get(c["id"])
        if hit:
            pairs.append((c, hit, "id"))
            continue
        unmatched.append(c)
    return pairs, unmatched


def match_states(old, new):
    tiers = [
        ("iso3166_2", lambda s: (s["country_iso2"], normalize_key(s["iso3166_2"])) if s.get("iso3166_2") else None),
        ("state_code", lambda s: (s["country_iso2"], normalize_key(s["state_code"])) if s.get("state_code") else None),
        ("name", lambda s: (s["country_iso2"], s["normalized_name"]) if s.get("normalized_name") else None),
        ("name_tokens", token_key),
    ]
    indexes = [(label, index(new, fn), fn) for label, fn in tiers]
    by_id = {s["id"]: s for s in new}
    taken = set()
    pairs, unmatched = [], []
    for s in old:
        found = None
        for label, idx, fn in indexes:
            k = fn(s)
            if k is None:
                continue
            # A tier that is ambiguous on the new side is not a match.
            candidates = [c for c in idx.get(k, []) if c["id"] not in taken]
            if len(candidates) == 1:
                found = (candidates[0], label)
                break
        if found is None:
            hit = by_id.get(s["id"])
            # An id match is only trustworthy if the name agrees; ids are
            # recycled across versions, which is the whole problem (issue 8).
            if hit and hit["normalized_name"] == s["normalized_name"] and hit["id"] not in taken:
                found = (hit, "id+name")
        if found is None:
            unmatched.append(s)
            continue
        taken.add(found[0]["id"])
        pairs.append((s, found[0], found[1]))
    return pairs, unmatched


def match_cities(old, new, state_remap):
    """Match within the *new* state a city's old state maps to."""
    by_state_name = index(
        new, lambda c: (c["state_id"], c["normalized_name"]) if c.get("normalized_name") else None
    )
    by_country_name = index(
        new, lambda c: (c["country_iso2"], c["normalized_name"]) if c.get("normalized_name") else None
    )
    by_tokens = index(new, token_key)
    by_id = {c["id"]: c for c in new}
    taken = set()
    pairs, unmatched = [], []

    for c in old:
        new_state_id = state_remap.get(c["state_id"])
        found = None

        if new_state_id is not None:
            candidates = [
                x for x in by_state_name.get((new_state_id, c["normalized_name"]), [])
                if x["id"] not in taken
            ]
            if len(candidates) == 1:
                found = (candidates[0], "state+name")
            elif len(candidates) > 1:
                # Same name twice in one state: nearest coordinate wins.
                scored = [
                    (km(c["latitude"], c["longitude"], x["latitude"], x["longitude"]), x)
                    for x in candidates
                ]
                scored = [(d, x) for d, x in scored if d is not None]
                if scored:
                    scored.sort(key=lambda t: t[0])
                    if scored[0][0] <= SAME_PLACE_KM:
                        found = (scored[0][1], "state+name+coords")

        if found is None:
            # The FR re-parenting moves cities between states, so fall back to
            # a country-wide name match disambiguated by distance.
            candidates = [
                x for x in by_country_name.get((c["country_iso2"], c["normalized_name"]), [])
                if x["id"] not in taken
            ]
            scored = [
                (km(c["latitude"], c["longitude"], x["latitude"], x["longitude"]), x)
                for x in candidates
            ]
            scored = [(d, x) for d, x in scored if d is not None and d <= SAME_PLACE_KM]
            if len(candidates) == 1 and not scored:
                found = (candidates[0], "country+name")
            elif scored:
                scored.sort(key=lambda t: t[0])
                found = (scored[0][1], "country+name+coords")

        if found is None:
            candidates = [
                x for x in by_tokens.get(token_key(c) or (), []) if x["id"] not in taken
            ]
            scored = [
                (km(c["latitude"], c["longitude"], x["latitude"], x["longitude"]), x)
                for x in candidates
            ]
            scored = [(d, x) for d, x in scored if d is not None and d <= SAME_PLACE_KM]
            if scored:
                scored.sort(key=lambda t: t[0])
                found = (scored[0][1], "name_tokens+coords")
            elif len(candidates) == 1:
                found = (candidates[0], "name_tokens")

        if found is None:
            hit = by_id.get(c["id"])
            if hit and hit["normalized_name"] == c["normalized_name"] and hit["id"] not in taken:
                found = (hit, "id+name")

        if found is None:
            unmatched.append(c)
            continue
        taken.add(found[0]["id"])
        pairs.append((c, found[0], found[1]))
    return pairs, unmatched


# ------------------------------------------------------------------ reporting


def classify_removals(removed, new_rows):
    """Split removals into genuinely absent vs still-present-but-unmatched.

    A name that no longer appears anywhere in its country is a real deletion.
    A name that is still there but could not be matched one-to-one usually
    means upstream deduplicated it or moved it, and the matcher could not
    decide which survivor it maps to. The two need very different review:
    the first is data leaving, the second is bookkeeping.
    """
    present = collections.defaultdict(int)
    for r in new_rows:
        present[(r.get("country_iso2") or r.get("iso2"), r.get("normalized_name"))] += 1
        tk = token_key(r)
        if tk:
            present[tk] += 1
    absent, ambiguous = [], []
    for r in removed:
        key = (r.get("country_iso2") or r.get("iso2"), r.get("normalized_name"))
        tk = token_key(r)
        (ambiguous if (present.get(key) or (tk and present.get(tk))) else absent).append(r)
    return absent, ambiguous


def summarize(entity, old_rows, new_rows, pairs, unmatched, extra_fields=()):
    matched_new = {n["id"] for _, n, _ in pairs}
    added = [n for n in new_rows if n["id"] not in matched_new]
    absent, ambiguous = classify_removals(unmatched, new_rows)

    renamed = [
        (o, n) for o, n, _ in pairs if o.get("normalized_name") != n.get("normalized_name")
    ]
    id_changed = [(o, n) for o, n, _ in pairs if o["id"] != n["id"]]
    reparented = [
        (o, n)
        for o, n, _ in pairs
        if "state_id" in o and "state_id" in n and o["state_id"] != n["state_id"]
    ]
    field_changes = collections.Counter()
    for field in extra_fields:
        for o, n, _ in pairs:
            if o.get(field) is not None and o.get(field) != n.get(field):
                field_changes[field] += 1

    return {
        "entity": entity,
        "before": len(old_rows),
        "after": len(new_rows),
        "matched": len(pairs),
        "added": added,
        "removed": unmatched,
        "removed_absent": absent,
        "removed_ambiguous": ambiguous,
        "renamed": renamed,
        "id_changed": id_changed,
        "reparented": reparented,
        "match_tiers": collections.Counter(t for _, _, t in pairs),
        "field_changes": field_changes,
    }


def per_country(rows):
    return collections.Counter(r.get("country_iso2") or r.get("iso2") for r in rows)


def render_markdown(summaries, from_label, to_label, from_desc, to_desc, breaches,
                    signed_off=None):
    now = datetime.datetime.now().strftime("%Y-%m-%d")
    out = []
    add = out.append

    add("# Churn report: {} -> {}".format(from_label, to_label))
    add("")
    add("Generated {}. Review this before releasing (Decision 6).".format(now))
    add("")
    add("- **from:** {}".format(from_desc))
    add("- **to:** {}".format(to_desc))
    add("")

    if breaches and signed_off:
        add("## Threshold breaches -- signed off")
        add("")
        add("Reviewed and accepted on {}.".format(signed_off["accepted_on"]))
        add("")
        for line in signed_off["reason"].splitlines():
            add("> {}".format(line) if line.strip() else ">")
        add("")
        for b in breaches:
            add("- {}".format(b))
        add("")
    elif breaches:
        add("## Threshold breaches -- sign-off required")
        add("")
        add("These exceed the churn budget ({}% net removal per entity, {}% per "
            "country). Releasing anyway requires `--accept-churn` with a written "
            "justification recorded in the CHANGELOG.".format(
                MAX_NET_REMOVAL_PCT, MAX_COUNTRY_REMOVAL_PCT))
        add("")
        for b in breaches:
            add("- {}".format(b))
        add("")
    else:
        add("## Threshold breaches")
        add("")
        add("None. All deltas are within the churn budget.")
        add("")

    add("## Summary")
    add("")
    add("| entity | before | after | net | matched | added | gone | unmatched | renamed | id changed | re-parented |")
    add("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for s in summaries:
        net = s["after"] - s["before"]
        add("| {} | {:,} | {:,} | {:+,} | {:,} | {:,} | {:,} | {:,} | {:,} | {:,} | {:,} |".format(
            s["entity"], s["before"], s["after"], net, s["matched"],
            len(s["added"]), len(s["removed_absent"]), len(s["removed_ambiguous"]),
            len(s["renamed"]), len(s["id_changed"]), len(s["reparented"])))
    add("")
    add("**gone** = the name no longer appears anywhere in that country: real "
        "data leaving. **unmatched** = the name is still present but could not "
        "be paired one-to-one, which usually means upstream deduplicated or "
        "re-parented it. Only *gone* counts against the churn budget.")
    add("")

    for s in summaries:
        add("## {}".format(s["entity"]))
        add("")
        add("Match quality: " + ", ".join(
            "`{}` {:,}".format(k, v) for k, v in s["match_tiers"].most_common()
        ) + ".")
        add("")
        if s["field_changes"]:
            add("Field-level changes on matched rows: " + ", ".join(
                "`{}` {:,}".format(k, v) for k, v in s["field_changes"].most_common()
            ) + ".")
            add("")

        if s["id_changed"]:
            add("**{:,} rows kept their identity but changed id.** This is the "
                "churn that silently corrupts foreign keys in already-seeded "
                "apps -- see the remap table and `geodata_migrate`.".format(
                    len(s["id_changed"])))
            add("")

        for label, rows, extract in (
            ("Added", s["added"], lambda r: r),
            ("Gone (name absent from the country)", s["removed_absent"], lambda r: r),
            ("Unmatched (name still present)", s["removed_ambiguous"], lambda r: r),
        ):
            if not rows:
                continue
            counts = per_country(rows)
            add("### {} ({:,})".format(label, len(rows)))
            add("")
            add("| country | count |")
            add("|---|---:|")
            for iso2, n in counts.most_common(20):
                add("| {} | {:,} |".format(iso2, n))
            if len(counts) > 20:
                add("| _{} more_ | {:,} |".format(
                    len(counts) - 20, sum(n for _, n in counts.most_common()[20:])))
            add("")
            add("<details><summary>first 25 rows</summary>")
            add("")
            for r in rows[:25]:
                add("- `{}` {} ({})".format(
                    r["id"], r.get("name"), r.get("country_iso2") or r.get("iso2")))
            add("")
            add("</details>")
            add("")

        if s["renamed"]:
            add("### Renamed ({:,})".format(len(s["renamed"])))
            add("")
            add("| id | before | after | country |")
            add("|---|---|---|---|")
            for o, n in s["renamed"][:30]:
                add("| {} | {} | {} | {} |".format(
                    n["id"], o.get("name"), n.get("name"),
                    n.get("country_iso2") or n.get("iso2")))
            if len(s["renamed"]) > 30:
                add("")
                add("_...and {:,} more._".format(len(s["renamed"]) - 30))
            add("")

        if s["reparented"]:
            add("### Re-parented ({:,})".format(len(s["reparented"])))
            add("")
            counts = per_country([n for _, n in s["reparented"]])
            add("| country | count |")
            add("|---|---:|")
            for iso2, n in counts.most_common(15):
                add("| {} | {:,} |".format(iso2, n))
            add("")
            add("A re-parented city keeps its identity but answers a different "
                "`state_id`. Queries that filter by the old state return "
                "nothing -- this is the France/INSEE breaking change.")
            add("")

    return "\n".join(out) + "\n"


def check_thresholds(summaries):
    breaches = []
    for s in summaries:
        if not s["before"]:
            continue
        removal_pct = len(s["removed_absent"]) / float(s["before"]) * 100.0
        if removal_pct > MAX_NET_REMOVAL_PCT:
            breaches.append(
                "**{}**: {:,} rows disappeared entirely ({:.1f}% of {:,}, limit "
                "{:.1f}%)".format(
                    s["entity"], len(s["removed_absent"]), removal_pct,
                    s["before"], MAX_NET_REMOVAL_PCT
                )
            )
        removed_by_country = per_country(s["removed_absent"])
        added_by_country = per_country(s["added"])
        before_by_country = collections.Counter()
        for r in s["removed"]:
            before_by_country[r.get("country_iso2") or r.get("iso2")] += 1
        for iso2, n_removed in removed_by_country.most_common():
            # Approximate the country's before-count from matched + removed.
            base = n_removed + added_by_country.get(iso2, 0)
            if base < 50:
                continue
            pct = n_removed / float(base) * 100.0
            if pct > MAX_COUNTRY_REMOVAL_PCT and n_removed > 100:
                breaches.append(
                    "**{}/{}**: {:,} rows disappeared entirely ({:.0f}% of the "
                    "rows that moved for this country)".format(
                        s["entity"], iso2, n_removed, pct)
                )
    return breaches


def write_remap(path, summaries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    n = 0
    with open(path, "w", encoding="utf-8") as fh:
        for s in summaries:
            entity = s["entity"]
            for o, new in s["id_changed"]:
                fh.write(json.dumps({
                    "entity": entity,
                    "old_id": o["id"],
                    "new_id": new["id"],
                    "stable_key": new.get("stable_key"),
                    "name": new.get("name"),
                    "country_iso2": new.get("country_iso2") or new.get("iso2"),
                    "reason": "id_changed",
                }, ensure_ascii=False, sort_keys=True) + "\n")
                n += 1
            for o, new in s["reparented"]:
                fh.write(json.dumps({
                    "entity": entity,
                    "old_id": o["id"],
                    "new_id": new["id"],
                    "old_state_id": o.get("state_id"),
                    "new_state_id": new.get("state_id"),
                    "stable_key": new.get("stable_key"),
                    "name": new.get("name"),
                    "country_iso2": new.get("country_iso2"),
                    "reason": "reparented",
                }, ensure_ascii=False, sort_keys=True) + "\n")
                n += 1
            for reason, rows in (("removed", s["removed_absent"]),
                                 ("unmatched", s["removed_ambiguous"])):
                for r in rows:
                    fh.write(json.dumps({
                        "entity": entity,
                        "old_id": r["id"],
                        "new_id": None,
                        "stable_key": None,
                        "name": r.get("name"),
                        "country_iso2": r.get("country_iso2") or r.get("iso2"),
                        "reason": reason,
                    }, ensure_ascii=False, sort_keys=True) + "\n")
                    n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="src", help="directory of the previous canonical dataset")
    ap.add_argument("--from-legacy", action="store_true",
                    help="compare against the pre-remediation mirror snapshot at the repo root")
    ap.add_argument("--to", default=CANON, help="directory of the new canonical dataset")
    ap.add_argument("--from-label", default="previous")
    ap.add_argument("--to-label", default="current")
    ap.add_argument("--fail-on-breach", action="store_true",
                    help="exit non-zero if the churn budget is exceeded (for CI)")
    ap.add_argument("--accept-churn", metavar="REASON",
                    help="record sign-off for this version pair in data/CHURN_ACCEPTED.json")
    args = ap.parse_args()

    if args.from_legacy:
        old = load_legacy(ROOT)
        from_desc = ("pre-remediation snapshot (react-country-state-city mirror, "
                     "nested JSON at the repo root)")
    elif args.src:
        old = load_canonical(args.src)
        from_desc = os.path.relpath(args.src, ROOT)
    else:
        raise SystemExit("give --from <dir> or --from-legacy")

    new = load_canonical(args.to)
    to_desc = os.path.relpath(args.to, ROOT)

    sys.stderr.write("matching countries ...\n")
    cpairs, cunmatched = match_countries(old["countries"], new["countries"])
    sys.stderr.write("matching states ...\n")
    spairs, sunmatched = match_states(old["states"], new["states"])
    state_remap = {o["id"]: n["id"] for o, n, _ in spairs}
    sys.stderr.write("matching cities ({:,} old rows) ...\n".format(len(old["cities"])))
    tpairs, tunmatched = match_cities(old["cities"], new["cities"], state_remap)

    summaries = [
        summarize("countries", old["countries"], new["countries"], cpairs, cunmatched,
                  extra_fields=("currency", "capital")),
        summarize("states", old["states"], new["states"], spairs, sunmatched),
        summarize("cities", old["cities"], new["cities"], tpairs, tunmatched),
    ]

    breaches = check_thresholds(summaries)
    pair = "{}-{}".format(args.from_label, args.to_label)

    accepted = {}
    if os.path.exists(ACCEPTED):
        with open(ACCEPTED, encoding="utf-8") as fh:
            accepted = json.load(fh)

    if args.accept_churn:
        accepted[pair] = {
            "reason": args.accept_churn,
            "accepted_on": datetime.datetime.now().strftime("%Y-%m-%d"),
            "breaches": [b.replace("**", "") for b in breaches],
        }
        with open(ACCEPTED, "w", encoding="utf-8") as fh:
            json.dump(accepted, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print("recorded sign-off for {} in {}".format(pair, os.path.relpath(ACCEPTED, ROOT)))

    signed_off = accepted.get(pair)

    os.makedirs(ARTIFACTS, exist_ok=True)
    report_path = os.path.join(ARTIFACTS, "CHURN.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(summaries, args.from_label, args.to_label,
                                 from_desc, to_desc, breaches, signed_off))

    remap_path = os.path.join(REMAP, "{}-{}.ndjson".format(args.from_label, args.to_label))
    n_remap = write_remap(remap_path, summaries)

    print("\nwrote {}".format(os.path.relpath(report_path, ROOT)))
    print("wrote {} ({:,} entries)".format(os.path.relpath(remap_path, ROOT), n_remap))
    print("")
    for s in summaries:
        print("{:<10} {:>7,} -> {:>7,}  matched {:>7,}  added {:>6,}  gone {:>6,}  "
              "unmatched {:>6,}  id-changed {:>6,}  re-parented {:>6,}".format(
                  s["entity"], s["before"], s["after"], s["matched"],
                  len(s["added"]), len(s["removed_absent"]),
                  len(s["removed_ambiguous"]), len(s["id_changed"]),
                  len(s["reparented"])))
    if breaches:
        print("\nCHURN BUDGET EXCEEDED:")
        for b in breaches:
            print("  - " + b.replace("**", ""))
        if signed_off:
            print("\nSigned off {}: {}".format(
                signed_off["accepted_on"], signed_off["reason"].splitlines()[0]))
        elif args.fail_on_breach:
            print("\nNo sign-off recorded for {}. Review artifacts/CHURN.md, then\n"
                  "re-run with --accept-churn '<justification>'.".format(pair))
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
