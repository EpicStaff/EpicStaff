"""The Chat Admin sample: its Python node code, its flow, its export command and its files."""

import json
from pathlib import Path

import pytest
from django.core.management import call_command

from plugins.management.commands.plugin_export_resources import build_chat_admin_resources
from plugins.samples.chat_admin_code import append_turn, format_history
from plugins.samples.zip_builder import build_zip, sample_files
from plugins.services.install_service import PluginInstallService
from rbac.models import Organization
from tables.models import KeyValueNode, KeyValueTable, LLMConfig
from tests.plugins_tests.helpers import SECRETS, registered_ids, upload

NOW = "2026-10-07T12:00:00Z"
LATER = "2026-10-07T12:05:00Z"
CONVERSATION_ID = "c_0123456789abcdef01234567"
SAMPLE_PLUGIN_DIR = Path(__file__).resolve().parents[4] / "plugin-samples" / "chat-admin" / "plugin"


def _size(record: dict) -> int:
    return len(json.dumps(record, ensure_ascii=False).encode("utf-8"))


@pytest.fixture
def clock(monkeypatch):
    """Sets the time append_turn stamps on messages."""

    def _set(now: str):
        monkeypatch.setattr(append_turn, "_now", lambda: now)

    _set(NOW)
    yield _set


# --- append_turn --------------------------------------------------------------------


def test_the_first_turn_starts_a_record(clock):
    record = append_turn.main(CONVERSATION_ID, None, "How do I reset my password?", "Use Settings.")

    assert record == {
        "title": "How do I reset my password?",
        "turns": 1,
        "messages": [
            {"role": "user", "content": "How do I reset my password?", "at": NOW},
            {"role": "assistant", "content": "Use Settings.", "at": NOW},
        ],
        "started_at": NOW,
        "updated_at": NOW,
        "conversation_id": CONVERSATION_ID,
    }


def test_a_later_turn_appends_and_keeps_title_and_start(clock):
    first = append_turn.main(CONVERSATION_ID, None, "First question", "First answer")
    clock(LATER)

    record = append_turn.main(CONVERSATION_ID, first, "Second question", "Second answer")

    assert record["title"] == "First question"
    assert record["turns"] == 2
    assert (record["started_at"], record["updated_at"]) == (NOW, LATER)
    assert [(message["role"], message["content"]) for message in record["messages"]] == [
        ("user", "First question"),
        ("assistant", "First answer"),
        ("user", "Second question"),
        ("assistant", "Second answer"),
    ]


def test_the_title_is_the_first_question_on_one_line_and_at_most_80_characters(clock):
    question = "Why   does\nthe export " + "keep failing " * 10

    title = append_turn.main(CONVERSATION_ID, None, question, "a")["title"]

    assert len(title) == 80
    assert title.startswith("Why does the export keep failing")
    assert title.endswith("…")
    assert append_turn.main(CONVERSATION_ID, None, "  ", "a")["title"] == "New conversation"


def test_the_record_stays_under_200_000_bytes_by_dropping_the_oldest_pairs(clock):
    record = None
    for turn in range(30):
        record = append_turn.main(CONVERSATION_ID, record, f"q{turn} " + "x" * 4000, f"a{turn} " + "y" * 4000)

    assert _size(record) <= 200_000
    assert record["turns"] == 30
    labels = [message["content"].split(" ", 1)[0] for message in record["messages"]]
    # Whole pairs go, oldest first: what is left is one unbroken run up to the newest turn.
    kept = len(labels) // 2
    assert 0 < kept < 30
    assert labels == [label for turn in range(30 - kept, 30) for label in (f"q{turn}", f"a{turn}")]
    assert record["title"] == "q0 " + "x" * 76 + "…"


def test_a_single_turn_too_big_for_the_table_is_shortened_to_fit(clock):
    previous = append_turn.main(CONVERSATION_ID, None, "small", "small")

    record = append_turn.main(CONVERSATION_ID, previous, "Q" * 50_000, "é" * 150_000)

    assert 199_000 < _size(record) <= 200_000
    assert [message["role"] for message in record["messages"]] == ["user", "assistant"]
    assert record["messages"][0]["content"] == "Q" * 50_000
    answer = record["messages"][1]["content"]
    assert answer.endswith("…")
    assert set(answer[:-1]) == {"é"}


def test_a_record_of_another_shape_is_treated_as_new(clock):
    record = append_turn.main(CONVERSATION_ID, "not a record", "q", "a")

    assert (record["turns"], len(record["messages"])) == (1, 2)


# --- format_history -----------------------------------------------------------------


def test_a_new_conversation_has_no_history():
    assert format_history.main(None) == "(This is the start of the conversation.)"
    assert format_history.main({"messages": []}) == "(This is the start of the conversation.)"


def test_history_is_plain_text_of_the_latest_messages(clock):
    record = None
    for turn in range(12):
        record = append_turn.main(CONVERSATION_ID, record, f"question {turn}", f"answer {turn}")

    history = format_history.main(record)

    assert history.startswith("User: question 2\n\nAssistant: answer 2\n\n")
    assert history.endswith("User: question 11\n\nAssistant: answer 11")
    assert history.count("User: ") == 10


# --- the code as the sandbox runs it ------------------------------------------------


def _run_like_the_sandbox(source, **kwargs):
    """Indent the file into a `try:` block and call `main`, the way the sandbox wraps node code."""
    code = Path(source.__file__).read_text(encoding="utf-8")
    body = "\n".join("    " + line for line in code.split("\n"))
    # One namespace, as in a script: the sandbox runs the wrapped file as a whole program.
    namespace = {"kwargs": kwargs, "__name__": "__main__"}
    exec(  # noqa: S102 -- runs this repo's own sample code, as the sandbox would
        f"try:\n{body}\n    result = main(**kwargs)\nexcept Exception:\n    raise\n",
        namespace,
    )
    return namespace["result"]


def test_both_nodes_run_inside_the_sandbox_wrapper():
    record = _run_like_the_sandbox(
        append_turn, conversation_id=CONVERSATION_ID, conversation=None, question="q", answer="a"
    )
    history = _run_like_the_sandbox(format_history, conversation=record)

    assert record["turns"] == 1
    assert history == "User: q\n\nAssistant: a"
    assert json.loads(json.dumps(record)) == record


# --- the flow and the export command ------------------------------------------------


def _nodes_by_name(flow: dict) -> dict[str, dict]:
    return {node.get("node_name") or node["node_type"]: node for node in flow["nodes"]}


@pytest.mark.django_db
def test_the_export_holds_the_chat_flow_wired_in_order():
    data, refs = build_chat_admin_resources()

    assert set(refs) == {"Flow", "LLMConfig", "KeyValueTable"}
    assert data["KeyValueTable"] == [
        {"id": refs["KeyValueTable"], "name": "conversations", "description": "One entry per chat conversation."}
    ]
    [flow] = data["Flow"]
    assert flow["id"] == refs["Flow"]
    nodes = _nodes_by_name(flow)
    by_id = {node["id"]: name for name, node in nodes.items()}
    edges = {by_id[edge["start_node_id"]]: by_id[edge["end_node_id"]] for edge in flow["edge_list"]}
    assert edges == {
        "StartNode": "Load conversation",
        "Load conversation": "Format history",
        "Format history": "Answer",
        "Answer": "Append turn",
        "Append turn": "Save conversation",
        "Save conversation": "EndNode",
    }
    assert nodes["StartNode"]["variables"] == {"variables": {"conversation_id": "", "question": ""}}
    assert nodes["Load conversation"]["entries"] == [
        {"key": "{variables.conversation_id}", "value": "variables.conversation"}
    ]
    assert nodes["Save conversation"]["mode"] == "write"
    assert nodes["Save conversation"]["entries"] == [
        {"key": "{variables.conversation_id}", "value": "variables.record"}
    ]
    for name in ("Load conversation", "Save conversation"):
        assert nodes[name]["key_value_table"] == refs["KeyValueTable"]
    assert nodes["Append turn"]["python_code"]["code"] == Path(append_turn.__file__).read_text()
    assert nodes["Format history"]["output_variable_path"] == "variables.history"
    assert nodes["Answer"]["input_map"] == {"question": "variables.question", "history": "variables.history"}
    assert nodes["EndNode"]["output_map"] == {
        "answer": "variables.answer",
        "conversation_id": "variables.conversation_id",
    }
    assert data["LLMConfig"][0]["id"] == refs["LLMConfig"]


@pytest.mark.django_db
def test_the_command_writes_the_export_and_leaves_the_database_alone(tmp_path_factory, capsys):
    # tests/conftest.py points `tmp_path` at a fixed folder inside the repo.
    output = tmp_path_factory.mktemp("chat-admin") / "plugin" / "resources.json"

    call_command("plugin_export_resources", "--sample", "chat-admin", "--output", str(output))

    data = json.loads(output.read_text())
    printed = capsys.readouterr().out
    assert data["main_entity"] == "Flow"
    assert f"  KeyValueTable: {data['KeyValueTable'][0]['id']}" in printed
    assert f"  Flow: {data['Flow'][0]['id']}" in printed
    assert not Organization.objects.filter(name="plugin-sample-export").exists()


needs_sample_files = pytest.mark.skipif(
    not (SAMPLE_PLUGIN_DIR / "plugin.json").exists(),
    reason="the plugin-samples folder is not part of this checkout",
)


@needs_sample_files
def test_the_committed_sample_runs_the_current_python_node_code():
    """resources.json embeds the node code; regenerate it whenever a source file changes."""
    resources = json.loads((SAMPLE_PLUGIN_DIR / "resources.json").read_text(encoding="utf-8"))
    [flow] = resources["Flow"]
    sources = {"Format history": format_history, "Append turn": append_turn}

    python_nodes = {
        node["node_name"]: node["python_code"]["code"]
        for node in flow["nodes"]
        if node["node_type"] == "PythonNode"
    }

    assert set(python_nodes) == set(sources)
    for name, source in sources.items():
        assert python_nodes[name] == Path(source.__file__).read_text(encoding="utf-8"), (
            f"'{name}' in resources.json is stale: run plugin_export_resources --sample chat-admin"
        )


@pytest.mark.django_db
@needs_sample_files
def test_the_committed_sample_installs(admin_acme, acme, openai_catalog):
    """plugin.json's refs must name entities in the generated resources.json, and it must install."""
    page = sample_files()
    files = {
        "plugin.json": (SAMPLE_PLUGIN_DIR / "plugin.json").read_bytes(),
        "resources.json": (SAMPLE_PLUGIN_DIR / "resources.json").read_bytes(),
        "ui/index.html": page["ui/index.html"],
        "ui/icon.svg": page["ui/icon.svg"],
    }

    plugin = PluginInstallService().install(
        upload(build_zip(files), "chat-admin.zip"), secrets=SECRETS, user=admin_acme, org_id=acme.pk
    )

    assert (plugin.plugin_id, plugin.bridge_version, plugin.state) == ("chat-admin", 2, "ready")
    assert [(entry["alias"], entry["type"]) for entry in plugin.access] == [
        ("chat", "flow"),
        ("conversations", "key_value_table"),
    ]
    table = KeyValueTable.objects.get(org=acme, name="chat_admin__conversations")
    [flow_id] = registered_ids(plugin, "flow")
    assert set(
        KeyValueNode.objects.filter(graph_id=flow_id).values_list("key_value_table_id", flat=True)
    ) == {table.pk}
    [llm_config_id] = registered_ids(plugin, "llm_config")
    assert LLMConfig.objects.get(pk=llm_config_id).api_key_secret.name == "CHAT_ADMIN__OPENAI_API_KEY"
