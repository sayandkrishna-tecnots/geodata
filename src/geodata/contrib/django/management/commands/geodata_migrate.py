"""Migrate seeded geodata rows across a dataset version bump (Decision 7).

    python manage.py geodata_migrate --remap data/remap/2026.05-2026.09.ndjson
    python manage.py geodata_migrate --remap ... --apply

**`--dry-run` is the default.** You must pass `--apply` to write anything. The
first release ships this way deliberately: the whole point of the command is
that a straight re-seed silently corrupts foreign keys, so the safe path has to
be the one you get by accident.

What it will never do
---------------------
Delete a row that something references. When upstream drops a place an
application still points at, the row is deactivated (`is_active=False`) and,
where a successor is known, `superseded_by` is set. Historical records keep
resolving.
"""

import json
import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from geodata.migrate import load_remap, plan_migration, render_plan

ENTITY_MODELS = ("countries", "states", "cities")


class Command(BaseCommand):
    help = "Migrate seeded geodata rows between dataset versions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--remap",
            required=True,
            help="path to data/remap/<from>-<to>.ndjson",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="actually write. Without this the command only reports.",
        )
        parser.add_argument(
            "--entity",
            action="append",
            choices=ENTITY_MODELS,
            help="limit to one entity (repeatable). Default: all.",
        )
        parser.add_argument(
            "--report",
            help="write the operator report to this path as well as stdout",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="emit the plan as JSON instead of a table",
        )

    # -- model resolution ------------------------------------------------

    def _models(self):
        from django.apps import apps

        from django.conf import settings

        configured = getattr(settings, "GEODATA", {}).get("MODELS", {})
        out = {}
        for entity, default in (
            ("countries", "geodata.Country"),
            ("states", "geodata.State"),
            ("cities", "geodata.City"),
        ):
            label = configured.get(entity[:-1], default)
            out[entity] = apps.get_model(label)
        return out

    # -- reference detection ---------------------------------------------

    def _referenced_ids(self, model):
        """Which rows of `model` are pointed at from outside geodata.

        Anything here is never deleted. If we cannot work it out, we assume
        everything is referenced -- the conservative direction.
        """
        referenced = set()
        for rel in model._meta.related_objects:
            related_model = rel.related_model
            if related_model._meta.app_label == model._meta.app_label:
                continue  # geodata's own internal FKs
            column = rel.field.name
            values = (
                related_model._default_manager.filter(**{column + "__isnull": False})
                .values_list(column, flat=True)
                .distinct()
            )
            referenced.update(values)
        return referenced

    # -- main -------------------------------------------------------------

    def handle(self, *args, **options):
        path = options["remap"]
        if not os.path.exists(path):
            raise CommandError("no remap table at {}".format(path))
        remap = load_remap(path)
        if not len(remap):
            self.stdout.write("remap table is empty -- nothing to do")
            return

        models = self._models()
        entities = options.get("entity") or list(ENTITY_MODELS)

        plans = []
        contexts = {}
        for entity in entities:
            model = models[entity]
            rows = list(
                model._default_manager.all().values_list("pk", "geodata_id", "stable_key")
            )
            local_ids = [geodata_id for _, geodata_id, _ in rows]
            pk_by_geodata_id = {geodata_id: pk for pk, geodata_id, _ in rows}

            referenced_pks = self._referenced_ids(model)
            referenced_geodata_ids = {
                geodata_id for pk, geodata_id, _ in rows if pk in referenced_pks
            }

            plan = plan_migration(entity, local_ids, remap, referenced_geodata_ids)
            plans.append(plan)
            contexts[entity] = (model, pk_by_geodata_id)

        report = render_plan(plans, remap.from_version, remap.to_version,
                             applied=options["apply"])

        if options["json"]:
            self.stdout.write(json.dumps(
                {p.entity: {k: getattr(p, k) for k in p.BUCKETS} for p in plans},
                indent=2, default=str,
            ))
        else:
            self.stdout.write(report)

        if options["report"]:
            with open(options["report"], "w", encoding="utf-8") as fh:
                fh.write(report + "\n")
            self.stdout.write("\nwrote {}".format(options["report"]))

        if not options["apply"]:
            self.stdout.write(self.style.WARNING(
                "\nDRY RUN -- nothing was written. Re-run with --apply once the "
                "plan above looks right."
            ))
            return

        with transaction.atomic():
            for plan in plans:
                model, pk_by_geodata_id = contexts[plan.entity]
                self._apply(model, pk_by_geodata_id, plan)

        self.stdout.write(self.style.SUCCESS("\nmigration applied"))

    def _apply(self, model, pk_by_geodata_id, plan):
        updated = 0

        for item in plan.remapped:
            pk = pk_by_geodata_id.get(item["old_id"])
            if pk is None:
                continue
            model._default_manager.filter(pk=pk).update(
                geodata_id=item["new_id"],
                stable_key=item.get("stable_key") or "",
            )
            updated += 1

        # Rows upstream dropped are deactivated, never deleted -- whether or
        # not we detected a reference to them. Reference detection is
        # best-effort (it cannot see raw-SQL or cross-database references), and
        # a deactivated row costs a boolean while a wrongly deleted one is
        # unrecoverable. The successor is recorded either way, so historical
        # records resolve to the replacement.
        for item in plan.orphaned + plan.retired:
            pk = pk_by_geodata_id.get(item["old_id"])
            if pk is None:
                continue
            successor_pk = None
            if item.get("successor") is not None:
                successor_pk = pk_by_geodata_id.get(item["successor"])
                if successor_pk is None:
                    successor_pk = (
                        model._default_manager.filter(geodata_id=item["successor"])
                        .values_list("pk", flat=True)
                        .first()
                    )
            model._default_manager.filter(pk=pk).update(
                is_active=False, superseded_by_id=successor_pk
            )
            updated += 1

        # `ambiguous` is deliberately untouched -- a human decides.

        self.stdout.write("  {}: {:,} rows updated, {:,} left for review".format(
            plan.entity, updated, len(plan.ambiguous)
        ))
