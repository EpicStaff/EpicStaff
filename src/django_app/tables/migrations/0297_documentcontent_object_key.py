from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0296_merge_20261118_1445"),
    ]

    operations = [
        migrations.AddField(
            model_name="documentcontent",
            name="object_key",
            field=models.CharField(
                help_text="Key of the stored file in the knowledge bucket.",
                max_length=512,
                null=True,
                unique=True,
            ),
        ),
        migrations.AddField(
            model_name="documentcontent",
            name="content_hash",
            field=models.CharField(
                help_text="SHA-256 of the stored file's bytes, as hex.",
                max_length=64,
                null=True,
            ),
        ),
        # Nullable from here on, so going back past 0300 can add the column again to a
        # table that has rows; going back past this migration requires the bytes again.
        migrations.AlterField(
            model_name="documentcontent",
            name="content",
            field=models.BinaryField(help_text="Binary file content (max 12MB)", null=True),
        ),
    ]
