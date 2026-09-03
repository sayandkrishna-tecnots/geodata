#!/usr/bin/env python3
"""Download the pinned upstream dataset and record a supply-chain lock.

Source of truth is `dr5hn/countries-states-cities-database` pinned to a release
TAG -- never `master`, which is force-pushed and therefore irreproducible
(Decision 1).

  python3 scripts/fetch.py                 # use the tag in data/SOURCE.lock
  python3 scripts/fetch.py --tag v3.2-export.8
  python3 scripts/fetch.py --verify-only   # re-hash the cache, no network

A file whose sha256 differs from the lock for the *same tag* is a supply-chain
signal: the fetch fails rather than silently using new bytes.
"""

import argparse
import datetime
import hashlib
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache", "upstream")
LOCK = os.path.join(ROOT, "data", "SOURCE.lock")

REPO = "dr5hn/countries-states-cities-database"
DEFAULT_TAG = "v3.2-export.7"
RAW = "https://raw.githubusercontent.com/{repo}/{tag}/{path}"

# There is no standalone json/cities.json at this tag -- cities only exist
# inside the combined tree, so we pay the 46 MB download for them.
FILES = {
    "countries": "json/countries.json",
    "states": "json/states.json",
    "regions": "json/regions.json",
    "subregions": "json/subregions.json",
    "combined": "json/countries+states+cities.json",
    # Upstream's own coordinate-validation reference data; used by check 4.
    "country_bounds": ".github/data/country-bounds.json",
}


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_lock():
    if not os.path.exists(LOCK):
        return None
    with open(LOCK, encoding="utf-8") as fh:
        return json.load(fh)


def cache_path(name):
    return os.path.join(CACHE, name + ".json")


def download(tag, name, path, force=False):
    dest = cache_path(name)
    if os.path.exists(dest) and not force:
        return dest, False
    url = RAW.format(repo=REPO, tag=tag, path=path)
    os.makedirs(CACHE, exist_ok=True)
    tmp = dest + ".part"
    sys.stderr.write("  fetching {} ... ".format(path))
    sys.stderr.flush()
    with urllib.request.urlopen(url, timeout=300) as resp, open(tmp, "wb") as out:
        if resp.status != 200:
            raise SystemExit("HTTP {} for {}".format(resp.status, url))
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    os.replace(tmp, dest)
    sys.stderr.write("{:.1f} MB\n".format(os.path.getsize(dest) / 1e6))
    return dest, True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", help="upstream release tag (default: from SOURCE.lock)")
    ap.add_argument("--force", action="store_true", help="re-download even if cached")
    ap.add_argument("--verify-only", action="store_true", help="hash the cache, no network")
    ap.add_argument(
        "--accept-new-hashes",
        action="store_true",
        help="rewrite the lock when hashes change for the same tag (audit the diff first)",
    )
    args = ap.parse_args()

    lock = read_lock()
    tag = args.tag or (lock or {}).get("tag") or DEFAULT_TAG
    same_tag = bool(lock) and lock.get("tag") == tag

    if args.verify_only:
        if not lock:
            raise SystemExit("no data/SOURCE.lock to verify against")
        tag = lock["tag"]

    entries = {}
    mismatches = []
    for name, path in sorted(FILES.items()):
        dest = cache_path(name)
        if args.verify_only:
            if not os.path.exists(dest):
                raise SystemExit("missing cache file {} -- run without --verify-only".format(dest))
        else:
            dest, _ = download(tag, name, path, force=args.force)
        digest = sha256_file(dest)
        size = os.path.getsize(dest)
        entries[name] = {"path": path, "sha256": digest, "bytes": size}
        if same_tag:
            prev = lock["files"].get(name)
            if prev and prev["sha256"] != digest:
                mismatches.append((name, prev["sha256"], digest))

    if mismatches and not args.accept_new_hashes:
        sys.stderr.write(
            "\nSUPPLY-CHAIN MISMATCH: tag {} now serves different bytes.\n".format(tag)
        )
        for name, old, new in mismatches:
            sys.stderr.write("  {}\n    locked {}\n    actual {}\n".format(name, old, new))
        sys.stderr.write(
            "\nUpstream force-pushed this tag. Audit the change, then re-run with\n"
            "--accept-new-hashes to update data/SOURCE.lock.\n"
        )
        return 2

    if args.verify_only and not mismatches:
        print("SOURCE.lock verified: tag {}, {} files".format(tag, len(entries)))
        return 0

    payload = {
        "repo": REPO,
        "tag": tag,
        "url": "https://github.com/{}/releases/tag/{}".format(REPO, tag),
        "fetched_at": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "files": entries,
    }
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    with open(LOCK, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("wrote {} (tag {})".format(os.path.relpath(LOCK, ROOT), tag))
    for name, meta in sorted(entries.items()):
        print("  {:<12} {:>10,} bytes  {}".format(name, meta["bytes"], meta["sha256"][:16]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
