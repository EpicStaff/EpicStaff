from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0299_delete_unstored_document_content"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="documentcontent",
            name="content",
        ),
        migrations.AlterField(
            model_name="documentcontent",
            name="content_hash",
            field=models.CharField(
                help_text="SHA-256 of the stored file's bytes, as hex.",
                max_length=64,
            ),
        ),
        migrations.AlterField(
            model_name="documentcontent",
            name="object_key",
            field=models.CharField(
                help_text="Key of the stored file in the knowledge bucket.",
                max_length=512,
                unique=True,
            ),
        ),
    ]
