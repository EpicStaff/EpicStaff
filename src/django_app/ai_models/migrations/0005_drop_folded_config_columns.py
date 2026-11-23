"""Drop the columns folded into `parameters` and `connection`, and protect model rows in use.

The config → model link becomes RESTRICT: deleting a model row no longer deletes every
configuration that uses it, while deleting an organization still removes its custom models
together with the configs that use them.

The fold copied a custom model row's endpoint into the configs of its organization. A row
with an endpoint and no config at all loses that endpoint here, so each such row is named
in a warning first, by id only.
"""

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q
from loguru import logger

# Model -> (its config model, the endpoint columns dropped below).
ENDPOINT_COLUMNS = {
    "LLMModel": ("LLMConfig", ("base_url", "api_version", "deployment_id")),
    "EmbeddingModel": ("EmbeddingConfig", ("base_url", "deployment")),
}


def warn_about_endpoints_no_config_took(apps, schema_editor):
    for model_name, (config_name, columns) in ENDPOINT_COLUMNS.items():
        used_model_ids = (
            apps.get_model("ai_models", config_name)
            .objects.filter(model__isnull=False)
            .values("model_id")
        )
        has_endpoint = Q()
        for column in columns:
            has_endpoint |= Q(**{f"{column}__isnull": False}) & ~Q(**{column: ""})
        model_ids = (
            apps.get_model("ai_models", model_name)
            .objects.filter(has_endpoint, org__isnull=False)
            .exclude(pk__in=used_model_ids)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        for model_id in model_ids:
            logger.warning(
                "Dropping the endpoint of custom {} id={}: no config uses the model",
                model_name,
                model_id,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("ai_models", "0004_fold_config_columns"),
    ]

    operations = [
        migrations.RunPython(warn_about_endpoints_no_config_took, migrations.RunPython.noop),
        migrations.RemoveField(model_name="embeddingconfig", name="task_type"),
        migrations.RemoveField(model_name="embeddingmodel", name="base_url"),
        migrations.RemoveField(model_name="embeddingmodel", name="deployment"),
        migrations.RemoveField(model_name="llmconfig", name="api_version"),
        migrations.RemoveField(model_name="llmconfig", name="base_url"),
        migrations.RemoveField(model_name="llmconfig", name="frequency_penalty"),
        migrations.RemoveField(model_name="llmconfig", name="logit_bias"),
        migrations.RemoveField(model_name="llmconfig", name="logprobs"),
        migrations.RemoveField(model_name="llmconfig", name="max_tokens"),
        migrations.RemoveField(model_name="llmconfig", name="presence_penalty"),
        migrations.RemoveField(model_name="llmconfig", name="reasoning_effort"),
        migrations.RemoveField(model_name="llmconfig", name="seed"),
        migrations.RemoveField(model_name="llmconfig", name="stop"),
        migrations.RemoveField(model_name="llmconfig", name="temperature"),
        migrations.RemoveField(model_name="llmconfig", name="top_logprobs"),
        migrations.RemoveField(model_name="llmconfig", name="top_p"),
        migrations.RemoveField(model_name="llmmodel", name="api_version"),
        migrations.RemoveField(model_name="llmmodel", name="base_url"),
        migrations.RemoveField(model_name="llmmodel", name="deployment_id"),
        migrations.AlterField(
            model_name="embeddingconfig",
            name="model",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.RESTRICT,
                to="ai_models.embeddingmodel",
            ),
        ),
        migrations.AlterField(
            model_name="llmconfig",
            name="model",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.RESTRICT,
                to="ai_models.llmmodel",
            ),
        ),
    ]
