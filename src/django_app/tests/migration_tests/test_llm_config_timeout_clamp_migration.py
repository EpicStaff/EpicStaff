"""tables 0291 bounds LLMConfig.timeout and moves every stored timeout into the bounds.

Invariant: after the migration every LLM config's timeout is null or a finite number from
1 to 3600 seconds. A NaN timeout becomes the field default (120), not the maximum, even
though Postgres sorts NaN above every number. Infinity and anything above 3600 become
3600; minus infinity and anything below 1 become 1. Values already in range and null
stay as they were.
"""

import math

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("tables", "0290_systemoneconfig_openai_provider")]
AFTER = [("tables", "0291_alter_llmconfig_timeout")]

# (stored before the migration, expected after it)
TIMEOUTS = [
    (math.nan, 120.0),
    (math.inf, 3600.0),
    (-math.inf, 1.0),
    (0.0, 1.0),
    (0.5, 1.0),
    (1.0, 1.0),
    (300.0, 300.0),
    (3600.0, 3600.0),
    (5000.0, 3600.0),
    (None, None),
]


def _migrate(targets):
    MigrationExecutor(connection).migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
def test_stored_timeouts_are_moved_into_the_bounds():
    try:
        old_apps = _migrate(BEFORE)
        organization = old_apps.get_model("rbac", "Organization").objects.create(
            name="llm-config-timeout-clamp"
        )
        llm_config_model = old_apps.get_model("tables", "LLMConfig")
        config_ids = [
            llm_config_model.objects.create(
                org=organization, custom_name=f"timeout-{index}", timeout=stored
            ).pk
            for index, (stored, _expected) in enumerate(TIMEOUTS)
        ]

        new_apps = _migrate(AFTER)

        migrated = new_apps.get_model("tables", "LLMConfig").objects.in_bulk(config_ids)
        actual = [migrated[config_id].timeout for config_id in config_ids]
        assert actual == [expected for _stored, expected in TIMEOUTS]
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
