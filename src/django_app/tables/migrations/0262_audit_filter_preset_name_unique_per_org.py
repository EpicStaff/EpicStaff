import re

from django.db import migrations, models

# Frozen copies of the preset naming rule (tables/services/copy_services/
# audit_filter_preset_copy_service.py) and the name column length, so later
# edits there cannot change what this migration did.
NAME_MAX_LENGTH = 150
NUMBER_SUFFIX = re.compile(r"^(?P<base>.+) \((?P<number>\d+)\)$")


def _next_free_name(name, taken):
    match = NUMBER_SUFFIX.match(name)
    base = match.group("base") if match else name
    number = 2
    while True:
        suffix = f" ({number})"
        candidate = f"{base[: NAME_MAX_LENGTH - len(suffix)]}{suffix}"
        if candidate not in taken:
            return candidate
        number += 1


def dedupe_preset_names_per_org(preset_model):
    """Rename presets whose name repeats in their org; the oldest row keeps the name."""
    rows = list(
        preset_model.objects.order_by("org_id", "id").values_list("id", "org_id", "name")
    )
    # every original name counts as taken up front, so a rename never lands on a later row's name
    taken_by_org = {}
    for _, org_id, name in rows:
        taken_by_org.setdefault(org_id, set()).add(name)
    kept_by_org = {}
    for preset_id, org_id, name in rows:
        kept = kept_by_org.setdefault(org_id, set())
        if name not in kept:
            kept.add(name)
            continue
        new_name = _next_free_name(name, taken_by_org[org_id])
        taken_by_org[org_id].add(new_name)
        kept.add(new_name)
        preset_model.objects.filter(pk=preset_id).update(name=new_name)


def forwards(apps, schema_editor):
    dedupe_preset_names_per_org(apps.get_model("tables", "AuditFilterPreset"))


class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0261_merge_20261007_1300"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="auditfilterpreset",
            name="unique_audit_filter_preset_name_per_user",
        ),
        migrations.AddConstraint(
            model_name="auditfilterpreset",
            constraint=models.UniqueConstraint(
                fields=("org", "name"), name="unique_audit_filter_preset_name_per_org"
            ),
        ),
    ]
