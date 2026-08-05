"""The one thing to get right. PythonCodeData is nested in GraphData, and
session.graph_schema = session_data.graph.model_dump(mode="json").

`secret_names` is excluded because it is *derived* state — scan_secret_names()
reads it back out of `code` on demand, so persisting it would duplicate a fact
that can go stale. It is NOT a confidentiality measure: the names are string
literals in `code`, which graph_schema stores in full, so they are visible there
either way. Only the plaintext is secret.

`secrets` is deliberately NOT excluded: it is the only way the plaintext
crosses the django->crew Redis boundary (redis_service publishes
`resolved.model_dump_json()`), and a field-level exclude cannot be switched
back on for that one dump. What keeps `graph_schema` free of plaintext is not
an exclude flag on this field — it is that SecretResolver.resolve_payload()
only ever fills `secrets` on a deep copy, never on the caller's object, and
`graph_schema` is built from that original, unresolved object. So on the
object that gets persisted, `secrets` is always `{}`.

CodeTaskData is the crew->sandbox message and is never persisted, so its
`secrets` field is also a plain field, for the same delivery reason.

Getting either CodeTaskData.secrets or PythonCodeData.secrets backwards
(excluded) silently delivers no plaintext to the sandbox.
"""

from src.shared.models import CodeTaskData, PythonCodeData


class TestPythonCodeDataIsCarrierOnly:
    def test_only_secret_names_is_excluded(self):
        assert PythonCodeData.model_fields["secret_names"].exclude is True
        assert PythonCodeData.model_fields["secrets"].exclude is not True

    def test_unresolved_payload_dump_carries_no_names_and_no_plaintext(self):
        data = PythonCodeData(
            venv_name="default",
            code='def main(): return get_secret("STRIPE_KEY")',
            entrypoint="main",
            libraries=[],
            secret_names=["STRIPE_KEY"],
        )

        dumped = data.model_dump(mode="json")
        assert "secret_names" not in dumped
        # The name itself is NOT hidden — it is a literal in `code`, which is
        # dumped in full. Excluding the carrier avoids duplicating derived state,
        # nothing more.
        assert "STRIPE_KEY" in dumped["code"]
        # secrets is present but empty until resolved — this emptiness, not an
        # exclude flag, is what keeps graph_schema free of plaintext.
        assert dumped["secrets"] == {}

    def test_resolved_payload_dump_does_carry_the_plaintext(self):
        """This is the crew-delivery requirement: once `secrets` is filled (as
        SecretResolver.resolve_payload does on its returned copy), the value
        must actually appear on the wire."""
        data = PythonCodeData(
            venv_name="default",
            code="def main(): return 1",
            entrypoint="main",
            libraries=[],
            secret_names=["STRIPE_KEY"],
        )
        data.secrets = {"STRIPE_KEY": "sk-live-for-the-sandbox"}

        dumped_json = data.model_dump_json()
        assert "sk-live-for-the-sandbox" in dumped_json
        assert data.model_dump(mode="json")["secrets"] == {
            "STRIPE_KEY": "sk-live-for-the-sandbox"
        }
        # The name carrier stays excluded regardless of resolution state.
        assert "secret_names" not in dumped_json

    def test_fields_are_readable_in_process(self):
        data = PythonCodeData(
            venv_name="default",
            code="def main(): return 1",
            entrypoint="main",
            libraries=[],
            secret_names=["STRIPE_KEY"],
        )
        data.secrets = {"A": "b"}

        assert data.secret_names == ["STRIPE_KEY"]
        assert data.secrets == {"A": "b"}

    def test_defaults_are_empty(self):
        data = PythonCodeData(
            venv_name="default",
            code="def main(): return 1",
            entrypoint="main",
            libraries=[],
        )

        assert data.secret_names == []
        assert data.secrets == {}


class TestCodeTaskDataSerializesSecrets:
    def test_secrets_reach_the_wire(self):
        task = CodeTaskData(
            venv_name="default",
            libraries=[],
            code="def main(): return 1",
            execution_id="exec-1",
            entrypoint="main",
            secrets={"STRIPE_KEY": "sk-live-for-the-sandbox"},
        )

        assert CodeTaskData.model_fields["secrets"].exclude is not True
        assert "sk-live-for-the-sandbox" in task.model_dump_json()
        assert task.model_dump()["secrets"] == {"STRIPE_KEY": "sk-live-for-the-sandbox"}

    def test_defaults_to_empty(self):
        task = CodeTaskData(
            venv_name="default",
            libraries=[],
            code="def main(): return 1",
            execution_id="exec-1",
            entrypoint="main",
        )

        assert task.secrets == {}


class TestLogSummaryIsSafe:
    """The sandbox logs every task it receives. From the moment secrets travel in
    that message, logging it raw writes credentials into the log stream — so the
    sandbox logs this projection instead."""

    def _task(self):
        return CodeTaskData(
            venv_name="venv_9",
            libraries=["requests"],
            code="def main(): return 1",
            execution_id="exec-42",
            entrypoint="main",
            secrets={"STRIPE_KEY": "sk-live-must-not-be-logged"},
        )

    def test_summary_names_no_secret_and_shows_no_value(self):
        summary = self._task().log_summary()

        assert "sk-live-must-not-be-logged" not in summary
        # Not even the name: a secret's name is a weaker disclosure than its
        # value, but it is still the caller's data and the count is what you
        # actually need when debugging.
        assert "STRIPE_KEY" not in summary

    def test_summary_keeps_what_debugging_needs(self):
        summary = self._task().log_summary()

        assert "exec-42" in summary
        assert "venv_9" in summary
        assert "main" in summary
        # "Did the node receive its declarations?" answered without disclosure.
        assert "secrets=1" in summary

    def test_summary_of_a_task_with_no_secrets(self):
        task = CodeTaskData(
            venv_name="default",
            libraries=[],
            code="def main(): return 1",
            execution_id="exec-0",
            entrypoint="main",
        )

        assert "secrets=0" in task.log_summary()
