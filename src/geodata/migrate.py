"""Plan a migration between two dataset versions (Decision 7).

Framework-free on purpose: the Django command is a thin wrapper, and the same
planner works for a raw SQL migration, a data pipeline, or a dry-run report.

The problem this solves
-----------------------
Upstream ids are not stable. Between two consecutive upstream releases, 351
state ids and 6,321 city ids changed meaning, and 8,727 French cities were
re-parented from ISO-3166-2 regions to INSEE departments. An application that
stored `city_id = 52` in an order row and then re-seeds is not "updating
reference data" -- it is silently repointing that order at a different place.

So a migration is never a delete-and-reload. Every locally-held id is resolved
through the remap table, and the outcome falls into one of five buckets:

    unchanged   the id still means the same place
    remapped    same place, new id -- update the FK
    reparented  same place, same id, different state -- FK is fine, but any
                query that filters by the old state now misses it
    retired     the row is gone upstream AND nothing references it -- safe to
                delete
    orphaned    the row is gone upstream BUT something references it -- must
                NOT be deleted; deactivate and record a successor if there is
                one

`orphaned` is the bucket that makes this worth writing. Deleting those rows is
what corrupts an application's history.
"""

import collections
import gzip
import json
import os

__all__ = ["Remap", "MigrationPlan", "plan_migration", "load_remap"]


class Remap(object):
    """The `data/remap/<from>-<to>.ndjson` table, indexed for lookup."""

    def __init__(self, entries, from_version=None, to_version=None):
        self.from_version = from_version
        self.to_version = to_version
        self.entries = list(entries)
        self._by_old = collections.defaultdict(dict)
        for e in self.entries:
            self._by_old[e["entity"]][e["old_id"]] = e

    def __len__(self):
        return len(self.entries)

    def lookup(self, entity, old_id):
        """The remap entry for one old id, or None if it did not move."""
        return self._by_old.get(entity, {}).get(old_id)

    def counts(self):
        return collections.Counter((e["entity"], e["reason"]) for e in self.entries)


def load_remap(path):
    from_version = to_version = None
    # Strip the extension, not everything after the first dot -- versions are
    # themselves dotted ("2026.05-2026.09.ndjson").
    stem = os.path.basename(path)
    for suffix in (".ndjson.gz", ".ndjson", ".gz"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    if "-" in stem:
        from_version, to_version = stem.split("-", 1)

    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:
        entries = [json.loads(line) for line in fh if line.strip()]
    return Remap(entries, from_version, to_version)


class MigrationPlan(object):
    """What to do, per entity. Nothing here has been applied yet."""

    BUCKETS = ("unchanged", "remapped", "reparented", "retired", "orphaned", "ambiguous")

    def __init__(self, entity):
        self.entity = entity
        for bucket in self.BUCKETS:
            setattr(self, bucket, [])

    def add(self, bucket, item):
        getattr(self, bucket).append(item)

    @property
    def is_safe(self):
        """True if applying this cannot lose a referenced row."""
        return not any(item.get("successor") is None for item in self.orphaned)

    def summary(self):
        return collections.OrderedDict(
            (bucket, len(getattr(self, bucket))) for bucket in self.BUCKETS
        )

    def __repr__(self):
        return "<MigrationPlan {} {}>".format(
            self.entity, dict(self.summary())
        )


def plan_migration(entity, local_ids, remap, referenced_ids=None, new_ids=None):
    """Work out what happens to each locally-held id.

    entity          "countries" | "states" | "cities"
    local_ids       every id this application currently stores for that entity
    remap           a `Remap`
    referenced_ids  the subset that other tables point at via FK. Anything in
                    here is never deleted. Defaults to "all of them", which is
                    the safe assumption when the caller does not know.
    new_ids         ids present in the new dataset. When given, an id absent
                    from both the remap table and the new dataset is reported
                    as retired/orphaned rather than silently assumed fine.
    """
    if referenced_ids is None:
        referenced_ids = set(local_ids)
    else:
        referenced_ids = set(referenced_ids)

    plan = MigrationPlan(entity)

    for old_id in local_ids:
        entry = remap.lookup(entity, old_id)

        if entry is None:
            # Not in the remap table. Either it never moved, or -- if we were
            # given the new dataset -- it quietly vanished.
            if new_ids is not None and old_id not in new_ids:
                bucket = "orphaned" if old_id in referenced_ids else "retired"
                plan.add(bucket, {
                    "old_id": old_id,
                    "successor": None,
                    "reason": "absent_from_new_dataset",
                    "referenced": old_id in referenced_ids,
                })
            else:
                plan.add("unchanged", {"old_id": old_id, "new_id": old_id})
            continue

        reason = entry.get("reason")
        new_id = entry.get("new_id")

        if reason == "id_changed" and new_id is not None:
            plan.add("remapped", {
                "old_id": old_id,
                "new_id": new_id,
                "stable_key": entry.get("stable_key"),
                "name": entry.get("name"),
            })
        elif reason == "reparented":
            plan.add("reparented", {
                "old_id": old_id,
                "new_id": new_id if new_id is not None else old_id,
                "old_state_id": entry.get("old_state_id"),
                "new_state_id": entry.get("new_state_id"),
                "stable_key": entry.get("stable_key"),
                "name": entry.get("name"),
            })
        elif reason == "unmatched":
            # The name still exists upstream but could not be paired
            # one-to-one. Never delete on this basis -- a human decides.
            plan.add("ambiguous", {
                "old_id": old_id,
                "successor": None,
                "name": entry.get("name"),
                "country_iso2": entry.get("country_iso2"),
                "reason": "could_not_pair_uniquely",
                "referenced": old_id in referenced_ids,
            })
        else:  # "removed"
            bucket = "orphaned" if old_id in referenced_ids else "retired"
            plan.add(bucket, {
                "old_id": old_id,
                "successor": new_id,
                "name": entry.get("name"),
                "country_iso2": entry.get("country_iso2"),
                "reason": "removed_upstream",
                "referenced": old_id in referenced_ids,
            })

    return plan


def render_plan(plans, from_version, to_version, applied=False):
    """A human-readable operator report."""
    lines = []
    verb = "Applied" if applied else "Planned"
    lines.append("{} migration {} -> {}".format(verb, from_version, to_version))
    lines.append("")
    header = "{:<12} {:>10} {:>10} {:>11} {:>9} {:>9} {:>10}".format(
        "entity", "unchanged", "remapped", "reparented", "retired", "orphaned", "ambiguous"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for plan in plans:
        s = plan.summary()
        lines.append("{:<12} {:>10,} {:>10,} {:>11,} {:>9,} {:>9,} {:>10,}".format(
            plan.entity, s["unchanged"], s["remapped"], s["reparented"],
            s["retired"], s["orphaned"], s["ambiguous"],
        ))
    lines.append("")

    for plan in plans:
        if plan.orphaned:
            lines.append(
                "{}: {:,} referenced rows no longer exist upstream. They are "
                "NOT deleted -- each is deactivated (is_active=False) and, where "
                "a successor is known, superseded_by is set.".format(
                    plan.entity, len(plan.orphaned)
                )
            )
            for item in plan.orphaned[:10]:
                lines.append("    {} {} ({}) -> {}".format(
                    item["old_id"], item.get("name") or "?",
                    item.get("country_iso2") or "?",
                    item.get("successor") or "no successor",
                ))
            if len(plan.orphaned) > 10:
                lines.append("    ... and {:,} more".format(len(plan.orphaned) - 10))
            lines.append("")
        if plan.ambiguous:
            lines.append(
                "{}: {:,} rows need a human decision -- the place still exists "
                "upstream but could not be paired one-to-one.".format(
                    plan.entity, len(plan.ambiguous)
                )
            )
            lines.append("")
        if plan.reparented:
            lines.append(
                "{}: {:,} rows kept their id but moved to a different parent. "
                "Foreign keys stay valid, but any query that filters by the old "
                "parent will now miss them -- this is the France/INSEE change.".format(
                    plan.entity, len(plan.reparented)
                )
            )
            lines.append("")

    return "\n".join(lines)
