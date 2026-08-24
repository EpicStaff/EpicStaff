import shutil

import pytest

from conftest import load_tool_main

diagnostics_main = load_tool_main("diagnostics_tool").main

RUFF_MISSING = shutil.which("ruff") is None


@pytest.mark.skipif(
    RUFF_MISSING, reason="ruff is not installed in this test environment"
)
class TestDiagnosticsToolPython:
    def test_known_ruff_violation_reported(self, sandbox_dir):
        (sandbox_dir / "bad.py").write_text("import os\n\n\ndef f():\n    return 1\n")

        result = diagnostics_main(path="bad.py")

        assert "bad.py:1" in result
        assert result.startswith("error ")
        # F401: `os` imported but unused
        assert "F401" in result

    def test_no_issues_returns_friendly_message(self, sandbox_dir):
        (sandbox_dir / "good.py").write_text("def f() -> int:\n    return 1\n")

        result = diagnostics_main(path="good.py")

        assert result == "No diagnostics found in good.py"

    def test_directory_auto_detects_python(self, sandbox_dir):
        (sandbox_dir / "pkg").mkdir()
        (sandbox_dir / "pkg" / "bad.py").write_text("import sys\n")

        result = diagnostics_main(path="pkg")

        assert "bad.py" in result
        assert "F401" in result

    def test_cap_announced_when_many_diagnostics(self, sandbox_dir, monkeypatch):
        tool_module = load_tool_main("diagnostics_tool")
        monkeypatch.setattr(tool_module, "MAX_DIAGNOSTIC_LINES", 2)

        lines = "\n".join(f"import unused_module_{i}" for i in range(5))
        (sandbox_dir / "many.py").write_text(lines + "\n")

        result = tool_module.main(path="many.py")

        assert "showing first 2 of" in result


class TestDiagnosticsToolJsTs:
    def test_javascript_without_eslint_returns_clear_error(
        self, sandbox_dir, monkeypatch
    ):
        (sandbox_dir / "app.js").write_text("console.log('hi')\n")
        monkeypatch.setattr(shutil, "which", lambda name: None)

        result = diagnostics_main(path="app.js", language="javascript")

        assert result.startswith("Error:")
        assert "node tooling" in result
        assert "eslint" in result

    def test_typescript_without_tsc_returns_clear_error(self, sandbox_dir, monkeypatch):
        (sandbox_dir / "app.ts").write_text("const x: number = 1;\n")
        monkeypatch.setattr(shutil, "which", lambda name: None)

        result = diagnostics_main(path="app.ts", language="typescript")

        assert result.startswith("Error:")
        assert "node tooling" in result
        assert "tsc" in result


class TestDiagnosticsToolEdgeCases:
    def test_invalid_language_returns_error(self, sandbox_dir):
        result = diagnostics_main(path=".", language="rust")

        assert result.startswith("Error:")
        assert "invalid language" in result

    def test_missing_path_returns_error(self, sandbox_dir):
        result = diagnostics_main(path="does_not_exist.py")

        assert result.startswith("Error:")
        assert "does not exist" in result

    def test_path_escape_returns_permission_error(self, sandbox_dir):
        result = diagnostics_main(path="../../etc")

        assert result.startswith("Error:")
        assert "outside the allowed directory" in result

    def test_defaults_to_working_root_when_path_omitted(self, sandbox_dir):
        (sandbox_dir / "clean.py").write_text("def f() -> int:\n    return 1\n")

        result = diagnostics_main()

        assert result == "No diagnostics found in ."
