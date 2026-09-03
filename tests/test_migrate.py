"""Migration tests (plan step 19).

The invariant that matters: **a referenced row is never deleted**. Everything
else here supports proving that.

The planner tests are framework-free. The Django tests configure a throwaway
sqlite project so the command is exercised end to end, and skip cleanly if
Django is not installed.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from geodata.migrate import (  # noqa: E402
    MigrationPlan,
    Remap,
    load_remap,
    plan_migration,
    render_plan,
)

REMAP_PATH = os.path.join(ROOT, "data", "remap", "2026.05-2026.09.ndjson")


# ===================================================================
# The planner
# ===================================================================


def remap(*entries):
    return Remap(list(entries), "old", "new")


def test_unchanged_ids_pass_through():
    plan = plan_migration("cities", [1, 2, 3], remap())
    assert plan.summary()["unchanged"] == 3
    assert [i["new_id"] for i in plan.unchanged] == [1, 2, 3]


def test_remapped_id():
    r = remap({"entity": "cities", "old_id": 10, "new_id": 99,
               "reason": "id_changed", "stable_key": "NG/iso:ngla/lagos"})
    plan = plan_migration("cities", [10], r)
    assert plan.summary()["remapped"] == 1
    assert plan.remapped[0]["new_id"] == 99
    assert plan.remapped[0]["stable_key"] == "NG/iso:ngla/lagos"


def test_reparented_keeps_its_id():
    r = remap({"entity": "cities", "old_id": 10, "new_id": 10,
               "reason": "reparented", "old_state_id": 4, "new_state_id": 7})
    plan = plan_migration("cities", [10], r)
    assert plan.summary()["reparented"] == 1
    item = plan.reparented[0]
    assert item["new_id"] == 10
    assert (item["old_state_id"], item["new_state_id"]) == (4, 7)


def test_removed_and_unreferenced_is_retired():
    r = remap({"entity": "cities", "old_id": 10, "new_id": None, "reason": "removed"})
    plan = plan_migration("cities", [10], r, referenced_ids=set())
    assert plan.summary() == {
        "unchanged": 0, "remapped": 0, "reparented": 0,
        "retired": 1, "orphaned": 0, "ambiguous": 0,
    }


def test_removed_but_referenced_is_orphaned_not_deleted():
    """The invariant. A referenced row must never land in a deletable bucket."""
    r = remap({"entity": "cities", "old_id": 10, "new_id": None,
               "reason": "removed", "name": "Somewhere"})
    plan = plan_migration("cities", [10], r, referenced_ids={10})
    assert plan.retired == []
    assert len(plan.orphaned) == 1
    assert plan.orphaned[0]["referenced"] is True


def test_referenced_defaults_to_everything():
    """When the caller does not know what is referenced, assume all of it."""
    r = remap({"entity": "cities", "old_id": 10, "new_id": None, "reason": "removed"})
    plan = plan_migration("cities", [10], r)
    assert len(plan.orphaned) == 1 and plan.retired == []


def test_ambiguous_is_never_auto_resolved():
    r = remap({"entity": "cities", "old_id": 10, "new_id": None,
               "reason": "unmatched", "name": "Carmen"})
    plan = plan_migration("cities", [10], r, referenced_ids={10})
    assert len(plan.ambiguous) == 1
    assert plan.ambiguous[0]["successor"] is None
    assert plan.orphaned == [] and plan.retired == []


def test_absent_from_new_dataset_is_caught_even_without_a_remap_entry():
    plan = plan_migration("cities", [10], remap(), referenced_ids={10}, new_ids={11, 12})
    assert len(plan.orphaned) == 1
    assert plan.orphaned[0]["reason"] == "absent_from_new_dataset"


def test_is_safe_flags_orphans_without_a_successor():
    r = remap({"entity": "cities", "old_id": 10, "new_id": None, "reason": "removed"})
    assert plan_migration("cities", [10], r, referenced_ids={10}).is_safe is False

    r2 = remap({"entity": "cities", "old_id": 10, "new_id": 55, "reason": "removed"})
    assert plan_migration("cities", [10], r2, referenced_ids={10}).is_safe is True


def test_entities_do_not_leak_into_each_other():
    r = remap({"entity": "states", "old_id": 10, "new_id": 99, "reason": "id_changed"})
    assert plan_migration("cities", [10], r).summary()["unchanged"] == 1
    assert plan_migration("states", [10], r).summary()["remapped"] == 1


def test_render_plan_mentions_the_no_delete_guarantee():
    r = remap({"entity": "cities", "old_id": 10, "new_id": None,
               "reason": "removed", "name": "Somewhere"})
    text = render_plan([plan_migration("cities", [10], r, {10})], "a", "b")
    assert "NOT deleted" in text
    assert "is_active=False" in text


# ===================================================================
# Against the real remap table
# ===================================================================


@pytest.fixture(scope="module")
def real_remap():
    if not os.path.exists(REMAP_PATH):
        pytest.skip("run scripts/churn.py to generate the remap table")
    return load_remap(REMAP_PATH)


def test_real_remap_parses(real_remap):
    assert len(real_remap) > 1000
    assert real_remap.from_version == "2026.05"
    assert real_remap.to_version == "2026.09"


def test_real_remap_covers_the_fr_reparenting(real_remap):
    """v3.2's largest documented break (issue 8)."""
    fr = [
        e for e in real_remap.entries
        if e["entity"] == "cities" and e.get("country_iso2") == "FR"
        and e["reason"] == "reparented"
    ]
    assert len(fr) > 5000, "expected the bulk FR re-parenting, got {}".format(len(fr))


def test_fr_cities_migrate_without_losing_a_row(real_remap):
    fr_ids = [
        e["old_id"] for e in real_remap.entries
        if e["entity"] == "cities" and e.get("country_iso2") == "FR"
    ]
    plan = plan_migration("cities", fr_ids, real_remap, referenced_ids=set(fr_ids))
    assert plan.retired == [], "a referenced FR row was marked deletable"
    assert plan.reparented, "expected re-parenting in the FR plan"
    assert sum(plan.summary().values()) == len(fr_ids)


def test_us_dedup_never_deletes_a_referenced_row(real_remap):
    """Issue 9: the US -3,104 correction, seen from an adopter's side."""
    us_ids = [
        e["old_id"] for e in real_remap.entries
        if e["entity"] == "cities" and e.get("country_iso2") == "US"
    ]
    plan = plan_migration("cities", us_ids, real_remap, referenced_ids=set(us_ids))
    assert plan.retired == []
    assert plan.orphaned, "expected the removed US county rows to be orphaned"
    assert all(i["referenced"] for i in plan.orphaned)


def test_every_planned_id_lands_in_exactly_one_bucket(real_remap):
    ids = [e["old_id"] for e in real_remap.entries if e["entity"] == "states"][:500]
    plan = plan_migration("states", ids, real_remap)
    assert sum(plan.summary().values()) == len(ids)


# ===================================================================
# Django end to end
# ===================================================================

django = pytest.importorskip("django", reason="Django not installed")


@pytest.fixture(scope="module")
def django_env():
    from django.conf import settings

    if not settings.configured:
        settings.configure(
            DEBUG=False,
            DATABASES={"default": {
                "ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"
            }},
            INSTALLED_APPS=[
                "django.contrib.contenttypes",
                "django.contrib.auth",
                "geodata.contrib.django",
            ],
            USE_TZ=True,
            DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        )
        django.setup()

    from django.core.management import call_command
    from django.db import connection

    from geodata.contrib.django.models import City, Country, State

    with connection.schema_editor() as editor:
        for model in (Country, State, City):
            editor.create_model(model)

    return {"call_command": call_command, "Country": Country, "State": State, "City": City}


@pytest.fixture
def seeded(django_env):
    Country, State, City = django_env["Country"], django_env["State"], django_env["City"]
    City.objects.all().delete()
    State.objects.all().delete()
    Country.objects.all().delete()

    fr = Country.objects.create(
        geodata_id=75, iso2="FR", stable_key="FR", name="France", normalized_name="france"
    )
    old_region = State.objects.create(
        geodata_id=4000, country=fr, stable_key="FR/iso:fr-idf",
        name="Ile-de-France", normalized_name="ile de france", depth=1,
    )
    City.objects.create(
        geodata_id=5000, country=fr, state=old_region,
        stable_key="FR/iso:fr-idf/paris", name="Paris", normalized_name="paris",
    )
    City.objects.create(
        geodata_id=5001, country=fr, state=old_region,
        stable_key="FR/iso:fr-idf/gone", name="Gone", normalized_name="gone",
    )
    return django_env


def write_remap(tmp_path, entries):
    import json

    path = tmp_path / "2026.05-2026.09.ndjson"
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
    )
    return str(path)


def test_dry_run_is_the_default_and_writes_nothing(seeded, tmp_path, capsys):
    path = write_remap(tmp_path, [
        {"entity": "cities", "old_id": 5000, "new_id": 6000,
         "reason": "id_changed", "stable_key": "FR/iso:fr-75/paris"},
    ])
    seeded["call_command"]("geodata_migrate", remap=path)
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert seeded["City"].objects.get(name="Paris").geodata_id == 5000


def test_apply_updates_a_remapped_id(seeded, tmp_path):
    path = write_remap(tmp_path, [
        {"entity": "cities", "old_id": 5000, "new_id": 6000,
         "reason": "id_changed", "stable_key": "FR/iso:fr-75/paris"},
    ])
    seeded["call_command"]("geodata_migrate", remap=path, apply=True)
    paris = seeded["City"].objects.get(name="Paris")
    assert paris.geodata_id == 6000
    assert paris.stable_key == "FR/iso:fr-75/paris"
    assert paris.is_active is True


def test_removed_row_is_deactivated_not_deleted(seeded, tmp_path):
    path = write_remap(tmp_path, [
        {"entity": "cities", "old_id": 5001, "new_id": None,
         "reason": "removed", "name": "Gone", "country_iso2": "FR"},
    ])
    before = seeded["City"].objects.count()
    seeded["call_command"]("geodata_migrate", remap=path, apply=True)

    assert seeded["City"].objects.count() == before, "a row was deleted"
    gone = seeded["City"].objects.get(geodata_id=5001)
    assert gone.is_active is False
    assert seeded["City"].objects.active().count() == before - 1


def test_removed_row_records_its_successor(seeded, tmp_path):
    """So historical records resolve to the replacement, not to nothing."""
    City = seeded["City"]
    paris = City.objects.get(geodata_id=5000)
    path = write_remap(tmp_path, [
        {"entity": "cities", "old_id": 5001, "new_id": 5000,
         "reason": "removed", "name": "Gone", "country_iso2": "FR"},
    ])
    seeded["call_command"]("geodata_migrate", remap=path, apply=True)
    gone = City.objects.get(geodata_id=5001)
    assert gone.is_active is False
    assert gone.superseded_by_id == paris.pk
    assert paris.supersedes.count() == 1


def test_reparented_city_keeps_its_row(seeded, tmp_path):
    """The FR/INSEE case: the FK stays valid, the parent changed upstream."""
    path = write_remap(tmp_path, [
        {"entity": "cities", "old_id": 5000, "new_id": 5000, "reason": "reparented",
         "old_state_id": 4000, "new_state_id": 4100, "country_iso2": "FR"},
    ])
    seeded["call_command"]("geodata_migrate", remap=path, apply=True)
    paris = seeded["City"].objects.get(geodata_id=5000)
    assert paris.is_active is True
    assert paris.geodata_id == 5000


def test_ambiguous_rows_are_left_alone(seeded, tmp_path):
    path = write_remap(tmp_path, [
        {"entity": "cities", "old_id": 5001, "new_id": None,
         "reason": "unmatched", "name": "Gone", "country_iso2": "FR"},
    ])
    seeded["call_command"]("geodata_migrate", remap=path, apply=True)
    row = seeded["City"].objects.get(geodata_id=5001)
    assert row.is_active is True, "an ambiguous row must not be touched"


def test_report_is_written_when_asked(seeded, tmp_path):
    path = write_remap(tmp_path, [
        {"entity": "cities", "old_id": 5000, "new_id": 6000, "reason": "id_changed"},
    ])
    report = tmp_path / "report.txt"
    seeded["call_command"]("geodata_migrate", remap=path, report=str(report))
    assert report.exists() and "Planned migration" in report.read_text()
