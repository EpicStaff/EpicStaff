from django.db import migrations


def delete_duplicated_tools(apps, schema_editor):

    Tool = apps.get_model("tables", "Tool")
    tools = Tool.objects.all()

    tool_alias = set()

    for tool in tools:
        if tool.name_alias not in tool_alias:
            tool_alias.add(tool.name_alias)
            continue

        tool.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0034_defaultembeddingconfig_api_key_and_more"),
    ]

    operations = [
        migrations.RunPython(delete_duplicated_tools, elidable=True),
    ]
