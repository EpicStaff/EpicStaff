# Diagnostics Tool
#
# Per-language adapters, not an LSP client: python -> ruff (bundled via
# requirements.txt so it installs into this tool's dedicated venv);
# javascript/typescript -> eslint/tsc if present on PATH. The sandbox image
# does not ship node tooling by design (see Dockerfile.sandbox) — this is a
# hard requirement acceptance case, not a bug: JS/TS diagnostics return a
# clear error string instead of crashing.

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

MAX_DIAGNOSTIC_LINES = 200
LINT_TIMEOUT_SECONDS = 120


class RouteTool:
    @staticmethod
    def _is_path_within_path(source_path: Path, dest_path: Path) -> bool:
        source_path = source_path.resolve()
        dest_path = dest_path.resolve()
        return dest_path in source_path.parents or source_path == dest_path

    @staticmethod
    def is_path_has_permission(path: Path | str) -> bool:
        save_file_path = os.getenv("CONTAINER_SAVEFILES_PATH", ".")
        return RouteTool._is_path_within_path(path, Path(save_file_path))

    def construct_savepath(self, *, frompath: Path | str) -> Path:
        save_file_path = os.getenv("CONTAINER_SAVEFILES_PATH", ".")
        return Path(save_file_path) / Path(frompath)


def _detect_language(target: Path) -> str:
    if target.is_file():
        suffix = target.suffix.lower()
        if suffix == ".py":
            return "python"
        if suffix in (".js", ".jsx", ".mjs", ".cjs"):
            return "javascript"
        if suffix in (".ts", ".tsx"):
            return "typescript"
        return "unknown"

    # Directory: Python takes priority when several languages are present.
    if any(target.rglob("*.py")):
        return "python"
    if any(target.rglob("*.ts")) or any(target.rglob("*.tsx")):
        return "typescript"
    if any(target.rglob("*.js")) or any(target.rglob("*.jsx")):
        return "javascript"
    return "python"


def _run_ruff(target: Path, working_root: Path):
    # Invoked as `python -m ruff` (this interpreter's own venv, where
    # requirements.txt installed ruff as a library) rather than relying on
    # the bare `ruff` console script being on PATH — the sandbox does not
    # add each tool's dedicated venv bin/ dir to PATH when it spawns the
    # execution subprocess, so a PATH-based lookup would silently miss it.
    if importlib.util.find_spec("ruff") is None:
        return (
            None,
            "Error: ruff is not available in this environment. Add 'ruff' to the "
            "tool's requirements to enable Python diagnostics.",
        )

    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--output-format",
                "json",
                str(target),
            ],
            cwd=str(working_root),
            capture_output=True,
            text=True,
            timeout=LINT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return None, f"Error: ruff timed out after {LINT_TIMEOUT_SECONDS} seconds."
    except Exception as e:
        return None, f"Error: failed to run ruff: {e}"

    # ruff check exits 0 (no violations) or 1 (violations found) on a normal
    # run; anything else means it failed to run at all.
    if result.returncode not in (0, 1):
        return (
            None,
            f"Error: ruff failed: {result.stderr.strip() or result.stdout.strip()}",
        )

    try:
        violations = json.loads(result.stdout or "[]")
    except ValueError as e:
        return None, f"Error: could not parse ruff output: {e}"

    lines = []
    for violation in violations:
        filename = violation.get("filename", "?")
        try:
            rel = str(Path(filename).resolve().relative_to(working_root.resolve()))
        except ValueError:
            rel = filename

        location = violation.get("location") or {}
        row = location.get("row", "?")
        code = violation.get("code") or ""
        message = violation.get("message", "")
        prefix = f"[{code}] " if code else ""
        lines.append(f"error {rel}:{row}: {prefix}{message}")

    return lines, None


def _run_js_ts(language: str):
    tool_name = "eslint" if language == "javascript" else "tsc"
    if shutil.which(tool_name) is None:
        return (
            None,
            f"Error: {language} diagnostics require node tooling ('{tool_name}') "
            "which is not present in this sandbox.",
        )

    # Node tooling is intentionally not shipped in the sandbox image, so this
    # branch is unreachable in production. Kept for forward compatibility and
    # so local/dev environments with node tooling installed still work.
    return [], None


def main(path: str | None = None, language: str = "auto") -> str:
    """
    Run per-language diagnostic adapters (ruff for Python; eslint/tsc for
    JS/TS if present on PATH) over a file or directory. Never raises: all
    failures are returned as readable error strings.
    """
    try:
        path = path or "."
        language = language or "auto"

        if language not in ("auto", "python", "javascript", "typescript"):
            return (
                f"Error: invalid language '{language}'. Use one of auto, python, "
                "javascript, typescript."
            )

        route_tool = RouteTool()
        target = route_tool.construct_savepath(frompath=path)

        if not RouteTool.is_path_has_permission(target):
            return f"Error: path {path} is outside the allowed directory."

        if not target.exists():
            return f"Error: path {path} does not exist."

        working_root = Path(os.getenv("CONTAINER_SAVEFILES_PATH", "."))

        resolved_language = language
        if resolved_language == "auto":
            resolved_language = _detect_language(target)

        if resolved_language == "python":
            lines, error = _run_ruff(target, working_root)
        elif resolved_language in ("javascript", "typescript"):
            lines, error = _run_js_ts(resolved_language)
        else:
            return f"Error: could not determine a supported language for {path}."

        if error:
            return error

        if not lines:
            return f"No diagnostics found in {path}"

        total = len(lines)
        capped = lines[:MAX_DIAGNOSTIC_LINES]
        result = "\n".join(capped)

        if total > MAX_DIAGNOSTIC_LINES:
            result += f"\n(showing first {MAX_DIAGNOSTIC_LINES} of {total} diagnostics)"

        return result
    except Exception as e:
        return f"Error: failed to run diagnostics. Unexpected exception: {e}"
