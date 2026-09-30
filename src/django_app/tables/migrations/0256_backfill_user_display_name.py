import re

from django.db import migrations
from django.db.models import Q

BATCH_SIZE = 500

# Frozen copy of tables.models.user.display_name_from_email; do not sync it with the live helper.
DISPLAY_NAME_MAX_LENGTH = 255

_DIGITS = re.compile(r"\d")

# Any character that is not a letter or an apostrophe starts a new word.
_WORD_SEPARATORS = re.compile(r"[^\w']|_")

# "JohnSmith" / "johnSmith": letters, then one or more capitalized lowercase runs.
_CAMEL_CASE_WORD = re.compile(r"[A-Za-z][a-z]+(?:[A-Z][a-z]+)+")

_CAMEL_CASE_PART = re.compile(r"[A-Z]?[a-z]+")

_REPEATED_LETTER_RUN = re.compile(r"(.)\1{5,}")

_MAX_REPEATED_LETTERS = 5


def display_name_from_email(email):
    local_part = email.rpartition("@")[0] if "@" in email else email
    pieces = _WORD_SEPARATORS.split(_DIGITS.sub("", local_part))
    words = []
    for piece in filter(None, (piece.strip("'") for piece in pieces)):
        words.extend(
            _CAMEL_CASE_PART.findall(piece) if _CAMEL_CASE_WORD.fullmatch(piece) else [piece]
        )
    display_name = " ".join(
        _REPEATED_LETTER_RUN.sub(
            lambda run: run.group(1) * _MAX_REPEATED_LETTERS, word.lower()
        ).capitalize()
        for word in words
    )
    if not display_name:
        display_name = local_part.strip() or email.strip()
    return display_name[:DISPLAY_NAME_MAX_LENGTH].rstrip()


def backfill_display_name(apps, schema_editor):
    """Give every user with a NULL or whitespace-only display name one derived from their email.

    bulk_update bypasses auto_now, so updated_at is left as it was.
    Batches bound memory only; the migration is one transaction, so rows stay locked until commit.
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
