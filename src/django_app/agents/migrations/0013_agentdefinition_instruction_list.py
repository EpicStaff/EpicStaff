from django.db import migrations, models

BATCH_SIZE = 500
LEGACY_INSTRUCTION_NAME = "Instruction_1.md"


def convert_to_instruction_list(agent_definition) -> None:
    if agent_definition.instructions.strip():
        agent_definition.instruction_list = [
            {"name": LEGACY_INSTRUCTION_NAME, "content": agent_definition.instructions}
        ]
    # The frontend no longer reads the editor format flag.
    if isinstance(agent_definition.metadata, dict):
        agent_definition.metadata.pop("instructions_format", None)


def compile_instructions(instruction_list: list[dict]) -> str:
    return "\n\n".join(
        instruction["content"] for instruction in instruction_list if instruction["content"].strip()
    )


def instructions_to_instruction_list(apps, schema_editor):
    AgentDefinition = apps.get_model("agents", "AgentDefinition")
    batch = []
    for agent_definition in AgentDefinition.objects.only(
        "id", "instructions", "instruction_list", "metadata"
    ).iterator(chunk_size=BATCH_SIZE):
        convert_to_instruction_list(agent_definition)
        batch.append(agent_definition)
        if len(batch) >= BATCH_SIZE:
            AgentDefinition.objects.bulk_update(batch, ["instruction_list", "metadata"])
            batch = []
    if batch:
        AgentDefinition.objects.bulk_update(batch, ["instruction_list", "metadata"])


def instruction_list_to_instructions(apps, schema_editor):
    AgentDefinition = apps.get_model("agents", "AgentDefinition")
    batch = []
    for agent_definition in AgentDefinition.objects.only(
        "id", "instructions", "instruction_list"
    ).iterator(chunk_size=BATCH_SIZE):
        agent_definition.instructions = compile_instructions(agent_definition.instruction_list)
        batch.append(agent_definition)
        if len(batch) >= BATCH_SIZE:
            AgentDefinition.objects.bulk_update(batch, ["instructions"])
            batch = []
    if batch:
        AgentDefinition.objects.bulk_update(batch, ["instructions"])


class Migration(migrations.Migration):

    dependencies = [
        ("agents", "0012_surface_search_config_non_finite_floats"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentdefinition",
            name="instruction_list",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='Ordered list of named prompt instructions, each {"name": str, "content": str}. Applied to the agent in list order; put behavior, goals, tone, and constraints here.',
            ),
        ),
        migrations.RunPython(
            instructions_to_instruction_list,
            instruction_list_to_instructions,
        ),
        migrations.RemoveField(
            model_name="agentdefinition",
            name="instructions",
        ),
    ]
