import re

from django.db import migrations
from django.db.models import Q

BATCH_SIZE = 500

# Frozen copy of display_name_from_email (tables/models/user.py) as of EST-4368.
DISPLAY_NAME_MAX_LENGTH = 255

_LOCAL_PART_SEPARATORS = re.compile(r"[._-]")


def display_name_from_email(email):
    local_part = email.rpartition("@")[0] if "@" in email else email
    untagged = local_part.split("+", 1)[0]
    pieces = [piece.strip() for piece in _LOCAL_PART_SEPARATORS.split(untagged) if piece.strip()]
    display_name = " ".join(piece[0].upper() + piece[1:] for piece in pieces)
    if not display_name:
        display_name = local_part.strip() or email.strip()
    return display_name[:DISPLAY_NAME_MAX_LENGTH].rstrip()


def backfill_display_name(apps, schema_editor):
    """Give every user without a display name one derived from their email.

    Only NULL, empty and whitespace-only names are touched; a real name is never
    overwritten. bulk_update bypasses auto_now, so updated_at is left as it was.
    """
    User = apps.get_model("tables", "User")
    users_without_name = User.objects.filter(
        Q(display_name__isnull=True) | Q(display_name__regex=r"^\s*$")
    ).only("id", "email", "display_name")

    pending = []
    for user in users_without_name.iterator(chunk_size=BATCH_SIZE):
        derived_name = display_name_from_email(user.email)
        # A blank email derives a blank name; writing it would only turn NULL into "".
        if not derived_name:
            continue
        user.display_name = derived_name
        pending.append(user)
        if len(pending) >= BATCH_SIZE:
            User.objects.bulk_update(pending, ["display_name"], batch_size=BATCH_SIZE)
            pending = []
    if pending:
        User.objects.bulk_update(pending, ["display_name"], batch_size=BATCH_SIZE)


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0255_key_value_tables"),
    ]

    operations = [
        migrations.RunPython(backfill_display_name, migrations.RunPython.noop),
    ]
