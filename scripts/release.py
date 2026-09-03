#!/usr/bin/env python3
"""Cut a dataset release: validate, snapshot, record the baseline.

    python3 scripts/release.py --version 2026.09

Steps, in order, each blocking the next:

  1. `scripts/validate.py` must pass (Decision 5).
  2. If a previous release exists, churn against it must be within budget or
     carry a recorded sign-off (Decision 6).
  3. Copy `data/canonical/` to `data/snapshots/<version>/` so the next refresh
     has something to diff against.
  4. Write `data/RELEASE.json` -- the baseline validation check 6 compares to.

The snapshot is what makes churn detection work at all: without a committed
previous version there is nothing to diff, and every refresh looks like a
first build.
"""

import argparse
import collections
import datetime
import gzip
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANON = os.path.join(ROOT, "data", "canonical")
SNAPSHOTS = os.path.join(ROOT, "data", "snapshots")
RELEASE = os.path.join(ROOT, "data", "RELEASE.json")
LOCK = os.path.join(ROOT, "data", "SOURCE.lock")


def read_ndjson(name):
    with open(os.path.join(CANON, name + ".ndjson"), encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def run(cmd):
    sys.stderr.write("$ {}\n".format(" ".join(cmd)))
    return subprocess.call(cmd, cwd=ROOT)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", required=True, help="release version, e.g. 2026.09")
    ap.add_argument("--skip-validate", action="store_true", help="for debugging only")
    ap.add_argument("--force", action="store_true", help="overwrite an existing snapshot")
    args = ap.parse_args()

    if not args.skip_validate:
        if run([sys.executable, "scripts/validate.py"]) != 0:
            raise SystemExit("\nvalidation failed -- not releasing")

    previous = None
    if os.path.exists(RELEASE):
        with open(RELEASE, encoding="utf-8") as fh:
            previous = json.load(fh)

    if previous and previous.get("version") != args.version:
        prev_dir = os.path.join(SNAPSHOTS, previous["version"])
        if os.path.isdir(prev_dir):
            code = run([
                sys.executable, "scripts/churn.py",
                "--from", prev_dir,
                "--from-label", previous["version"],
                "--to-label", args.version,
                "--fail-on-breach",
            ])
            if code != 0:
                raise SystemExit(
                    "\nchurn budget exceeded -- review artifacts/CHURN.md and re-run\n"
                    "scripts/churn.py with --accept-churn '<justification>'"
                )

    snapshot = os.path.join(SNAPSHOTS, args.version)
    if os.path.isdir(snapshot):
        if not args.force:
            raise SystemExit("{} already exists (use --force)".format(snapshot))
        shutil.rmtree(snapshot)
    os.makedirs(snapshot)
    # Snapshots are gzipped: the raw canonical set is ~44 MB and a release
    # commits one every time, which would bloat the repo within a year.
    for filename in sorted(os.listdir(CANON)):
        if not filename.endswith(".ndjson"):
            continue
        src = os.path.join(CANON, filename)
        with open(src, "rb") as fin:
            with gzip.open(os.path.join(snapshot, filename + ".gz"), "wb", compresslevel=9) as fout:
                shutil.copyfileobj(fin, fout)

    countries = read_ndjson("countries")
    states = read_ndjson("states")
    cities = read_ndjson("cities")
    # Vendored, not upstream -- but the manifest should describe everything a
    # release ships, and a silent drop in this table is worth noticing.
    languages = read_ndjson("languages")

    with open(LOCK, encoding="utf-8") as fh:
        lock = json.load(fh)

    payload = {
        "version": args.version,
        "released_on": datetime.datetime.now().strftime("%Y-%m-%d"),
        "source": {"repo": lock["repo"], "tag": lock["tag"], "url": lock["url"]},
        "counts": {
            "countries": len(countries),
            "states": len(states),
            "cities": len(cities),
            "languages": len(languages),
        },
        "cities_by_country": dict(collections.Counter(c["country_iso2"] for c in cities)),
        "states_by_country": dict(collections.Counter(s["country_iso2"] for s in states)),
    }
    with open(RELEASE, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print("\nreleased {} from upstream {}".format(args.version, lock["tag"]))
    print("  snapshot: {}".format(os.path.relpath(snapshot, ROOT)))
    print("  baseline: {}".format(os.path.relpath(RELEASE, ROOT)))
    for entity, n in sorted(payload["counts"].items()):
        print("  {:<10} {:>8,}".format(entity, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
