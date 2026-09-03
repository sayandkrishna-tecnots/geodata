# Release checklist

A dataset release is cheap to make and expensive to get wrong: every consumer
inherits whatever it contains. Work through this in order.

## 1. Refresh

```bash
make refresh          # fetch (pinned tag) + build + validate
```

`fetch.py` verifies each downloaded file's sha256 against `data/SOURCE.lock`.
If a hash changed for the *same tag*, upstream force-pushed it — audit the
change before passing `--accept-new-hashes`.

## 2. Gate

```bash
make check            # validate + the full test suite
```

The gate has to be **green**, not "green except". If a check is wrong, fix the
check; do not lower it. The one deliberate exception is the churn budget, which
has an explicit sign-off path (step 4).

## 3. Read the churn report

```bash
python3 scripts/churn.py \
    --from data/snapshots/<previous> --from-label <previous> --to-label <new>
open artifacts/CHURN.md
```

Three sections decide whether this release is safe:

- **Gone** — names that no longer appear anywhere in their country. Every entry
  needs an explanation. "Upstream removed it" is not an explanation; *why* they
  removed it is.
- **Re-parented** — rows that kept their id but moved under a different parent.
  These pass every integrity check and still break queries written against the
  old parent. This is the France/INSEE class of change.
- **Unmatched** — still present, could not be paired. Usually deduplication.

## 4. Sign off on any breach

If the budget is exceeded, the build refuses. Once you have attributed every
breach:

```bash
python3 scripts/churn.py --from ... --accept-churn "$(cat <<'MSG'
<what changed, per country, and the upstream reason for each>
MSG
)"
```

The justification is written to `data/CHURN_ACCEPTED.json`, embedded in
`artifacts/CHURN.md`, and must also be summarised in `CHANGELOG.md`.

## 5. Retire stale overrides

The gate reports any `data/overrides/` entry upstream has since adopted. Delete
those — an override that duplicates upstream is a future merge conflict.

## 6. Cut the release

```bash
python3 scripts/release.py --version YYYY.MM
```

This re-runs validation, re-checks churn, writes the gzipped snapshot to
`data/snapshots/<version>/`, and updates `data/RELEASE.json` — the baseline the
*next* refresh diffs against. Skipping it means the next release has nothing to
compare to and every row looks new.

## 7. Update the CHANGELOG

Record both numbers: the **dataset version** (`2026.09`) and the **upstream
tag** it came from (`v3.2-export.7`). They are not the same thing and consumers
need both.

## 8. Tell consumers what breaks

If the churn report shows anything under *Gone*, *Re-parented*, or *Renamed*,
the release notes must say so explicitly, and point at `docs/MIGRATION.md`.
Anyone with these ids in a foreign key needs `geodata_migrate`, not a re-seed.

---

## What never happens

- **No auto-merge of a data refresh.** The scheduled workflow opens a draft PR
  and stops. A human reads the churn report.
- **No release on a failed gate.**
- **No `master` as a source.** Upstream force-pushes export tags; a floating
  ref makes the build irreproducible.
- **No deleting a referenced row** during a consumer migration. Deactivate and
  supersede.
