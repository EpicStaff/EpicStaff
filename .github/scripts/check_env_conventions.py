"""Fail when environment variables are wired or parsed outside the project's conventions.

Run from the repo root: ``python3 .github/scripts/check_env_conventions.py``. CI runs it in the
``check-env-conventions`` job of ``.github/workflows/pr.yml``. Every check prints the
offending lines and what to do instead. This docstring is the one place the rules live:

1. Compose interpolation: every ``${VAR...}`` in a tracked compose file is ``${VAR:?}``.
   (``${VAR?}`` only for the few variables in ``COMPOSE_MAY_BE_EMPTY``, each with its
   reason). A default or a bare ``${VAR}`` lets a deployment run with a value nobody chose; the
   default belongs in ``src/env.yaml``. ``$${VAR}`` is escaped for the container's shell
   and is not interpolated by compose, so it is not checked.
2. Python booleans: an environment read (``os.getenv``, ``os.environ``, ``env.str``) is never
   turned into a bool by hand: compared with a quoted boolean literal (``== "true"``,
   ``in ("1", "yes")``, also after ``.lower()``), passed to ``strtobool`` or
   ``bool(int(...))``. Use ``Env.bool`` from ``src/shared/envtools.py``, which rejects
   anything that is not an explicit true or false value. Comparing with other strings
   (``== "production"``) is not boolean parsing and is allowed. Test files are not checked:
   asserting on a raw environment value there is not configuration parsing.
3. Shell booleans: an upper-case variable is never compared to a boolean literal, matched
   against one in a ``case``, or lower-cased (``tr``, ``${VAR,,}``); scripts use the
   ``env_bool`` function instead. Upper case marks an environment variable, so a
   script-local flag must be lower case (``failed=1``, not ``FAILED=1``) -- that is the way
   out of a false positive. Every copy of ``env_bool`` is identical and accepts exactly
   ``Env.BOOLEAN_TRUE_VALUES`` / ``Env.BOOLEAN_FALSE_VALUES``. Images are built from
   different contexts (``src/``, ``frontend/``) and opensearch only bind-mounts a single
   script, so the function is copied rather than shared.

Not scanned, so not covered: ``run:`` blocks in GitHub workflows, ``sh -c`` / ``command:``
strings inside compose files (only their ``${...}`` interpolation is checked), Dockerfile
``RUN`` lines, and shell code in files that do not end in ``.sh``.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

COMPOSE_FILE_RE = re.compile(r"(^|/)docker-compose[^/]*\.ya?ml$")
# ${...} and $VAR not preceded by another $ (which escapes it from compose).
COMPOSE_BRACED_RE = re.compile(r"(?<!\$)\$\{([^}]*)\}")
COMPOSE_BARE_RE = re.compile(r"(?<!\$)\$([A-Za-z_][A-Za-z0-9_]*)")
COMPOSE_REQUIRED_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(:?)\?")
# The only variables allowed to be set but empty (${VAR?} rather than ${VAR:?}), with why.
COMPOSE_MAY_BE_EMPTY = {
    # A blank host selects Django's console email backend (settings/email.py).
    "DJANGO_EMAIL_HOST",
    # A blank user and password mean an unauthenticated SMTP relay.
    "DJANGO_EMAIL_USER",
    "DJANGO_EMAIL_PASSWORD",
}

BOOL_WORD = r"(?i:true|false|yes|no|on|off|t|f|y|n|1|0)"

ENV_READ = (
    r"(?:\bos\.getenv|\bgetenv|\bos\.environ\.get|\benviron\.get|\benv\.str|\bEnv\(\)\.str)"
    r"\([^)]*\)|\bos\.environ\[[^\]]+\]"
)
# Optional .strip()/.lower()/... between the read and the comparison.
ENV_VALUE = rf"(?:{ENV_READ})(?:\.(?:strip|lower|upper|casefold)\(\))*"
QUOTED_BOOL = rf"[\"']{BOOL_WORD}[\"']"
PYTHON_AD_HOC_BOOL_RES = [
    re.compile(rf"{ENV_VALUE}\s*(?:==|!=)\s*{QUOTED_BOOL}"),
    re.compile(rf"{QUOTED_BOOL}\s*(?:==|!=)\s*{ENV_VALUE}"),
    re.compile(rf"{ENV_VALUE}\s+(?:not\s+)?in\s*[\(\[\{{][^)\]}}]*{QUOTED_BOOL}"),
    re.compile(rf"\bbool\(\s*int\(\s*(?:{ENV_READ})"),
    re.compile(rf"\bstrtobool\(\s*{ENV_VALUE}"),
    re.compile(r"\bdistutils\b.*\bstrtobool\b"),
]
PYTHON_EXEMPT = {"src/shared/envtools.py"}
PYTHON_TEST_FILE_RE = re.compile(r"(^|/)(tests?/|test_[^/]*\.py$|[^/]*_test\.py$|conftest\.py$)")

SHELL_FILE_RE = re.compile(r"\.sh$")
PYTHON_FILE_RE = re.compile(r"\.py$")
SHELL_ENV_VAR = r"\$\{?[A-Z][A-Z0-9_]*(?::?-[^}]*)?\}?"
SHELL_AD_HOC_BOOL_RES = [
    re.compile(rf"{SHELL_ENV_VAR}\"?\s*!?==?\s*[\"']?{BOOL_WORD}[\"']?(?:\s|\]|;|$)"),
    re.compile(rf"[\"']?\b{BOOL_WORD}[\"']?\s*!?==?\s*\"?{SHELL_ENV_VAR}"),
    # Lower-casing a value is how hand-rolled flag parsing starts.
    re.compile(r"\btr\s+[\"']?(?:\[:upper:\]|A-Z)[\"']?\s+[\"']?(?:\[:lower:\]|a-z)[\"']?"),
    re.compile(r"\$\{[A-Z][A-Z0-9_]*,,\}"),
]
SHELL_CASE_START_RE = re.compile(rf"^\s*case\s+\"?{SHELL_ENV_VAR}\"?\s+in\b")
SHELL_CASE_BOOL_PATTERN_RE = re.compile(rf"^\s*\(?[^)]*(?<![\w-]){BOOL_WORD}(?![\w-])[^)]*\)")
SHELL_CASE_END_RE = re.compile(r"\besac\b")
HELPER_START = "# >>> env_bool"
HELPER_END = "# <<< env_bool"
HELPER_CASE_RE = re.compile(r"^\s*([0-9a-z|]+)\)\s*return ([01])\s*;;")
HELPER_CALL_RE = re.compile(r"(^|[\s;!(])env_bool\s+[A-Z]")

Files = dict[str, list[str]]


def tracked_files() -> Files:
    output = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout
    return {
        path: (REPO_ROOT / path).read_text(encoding="utf-8", errors="replace").splitlines()
        for path in output.splitlines()
        if "/libraries/" not in f"/{path}" and (REPO_ROOT / path).is_file()
    }


def is_required_interpolation(expression: str) -> bool:
    match = COMPOSE_REQUIRED_RE.match(expression)
    if match is None:
        return False
    return match.group(2) == ":" or match.group(1) in COMPOSE_MAY_BE_EMPTY


def check_compose(files: Files) -> list[str]:
    violations = []
    for path, lines in files.items():
        for number, line in enumerate(lines, start=1):
            if line.lstrip().startswith("#"):
                continue
            expressions = COMPOSE_BRACED_RE.findall(line)
            bare = COMPOSE_BARE_RE.findall(COMPOSE_BRACED_RE.sub("", line))
            if bare or not all(map(is_required_interpolation, expressions)):
                violations.append(f"{path}:{number}: {line.strip()}")
    return violations


def check_python(files: Files) -> list[str]:
    violations = []
    for path, lines in files.items():
        if path in PYTHON_EXEMPT or PYTHON_TEST_FILE_RE.search(path):
            continue
        for number, line in enumerate(lines, start=1):
            if any(pattern.search(line) for pattern in PYTHON_AD_HOC_BOOL_RES):
                violations.append(f"{path}:{number}: {line.strip()}")
    return violations


def helper_range(lines: list[str]) -> range | None:
    stripped = [line.strip() for line in lines]
    if HELPER_START not in stripped or HELPER_END not in stripped:
        return None
    return range(stripped.index(HELPER_START), stripped.index(HELPER_END) + 1)


def unparsed_case_lines(lines: list[str], skipped: range) -> list[int]:
    """Indexes of `case "$UPPER" in` statements with a boolean word among their patterns."""
    flagged = []
    for index, line in enumerate(lines):
        if index in skipped or not SHELL_CASE_START_RE.search(line):
            continue
        for following in lines[index + 1 :]:
            if SHELL_CASE_END_RE.search(following):
                break
            if SHELL_CASE_BOOL_PATTERN_RE.search(following):
                flagged.append(index)
                break
    return flagged


def helper_values(helper: list[str]) -> dict[str, frozenset[str]]:
    values = {}
    for line in helper:
        if match := HELPER_CASE_RE.match(line):
            values["true" if match.group(2) == "0" else "false"] = frozenset(
                match.group(1).split("|")
            )
    return values


def check_shell(files: Files, true_values: frozenset, false_values: frozenset) -> list[str]:
    violations = []
    helpers: dict[str, list[str]] = {}
    for path, lines in files.items():
        block = helper_range(lines)
        if block is not None:
            helpers[path] = lines[block.start : block.stop]
        skipped = block or range(0)
        case_lines = set(unparsed_case_lines(lines, skipped))
        for index, line in enumerate(lines):
            if index in skipped or line.lstrip().startswith("#"):
                continue
            location = f"{path}:{index + 1}"
            if index in case_lines or any(p.search(line) for p in SHELL_AD_HOC_BOOL_RES):
                violations.append(f"{location}: {line.strip()}")
            # Without the function, `if env_bool X` is "command not found": silently false.
            elif block is None and HELPER_CALL_RE.search(line):
                violations.append(f"{location}: calls env_bool but has no env_bool block")

    if helpers:
        reference_path, reference = next(iter(helpers.items()))
        for path, helper in helpers.items():
            if helper != reference:
                violations.append(f"{path}: env_bool differs from the copy in {reference_path}")
        expected = {"true": true_values, "false": false_values}
        if helper_values(reference) != expected:
            violations.append(
                f"{reference_path}: env_bool accepts {helper_values(reference)}, "
                f"Env.bool accepts {expected}"
            )
    return violations


def matching(files: Files, pattern: re.Pattern) -> Files:
    return {path: lines for path, lines in files.items() if pattern.search(path)}


def report(title: str, violations: list[str], advice: str) -> bool:
    if not violations:
        return True
    print(f"ERROR: {title}")
    for violation in violations:
        print(f"  {violation}")
    print(f"  -> {advice}\n")
    return False


def main() -> int:
    sys.path.insert(0, str(REPO_ROOT))
    from src.shared.envtools import Env

    files = tracked_files()
    results = [
        report(
            "compose interpolation without :?",
            check_compose(matching(files, COMPOSE_FILE_RE)),
            "Write ${VAR:?} and put the default in src/env.yaml (then run "
            "python scripts/envtool.py --env-file .env.example).",
        ),
        report(
            "ad-hoc boolean parsing of an environment variable in Python",
            check_python(matching(files, PYTHON_FILE_RE)),
            "Read the flag with Env.bool from src/shared/envtools.py.",
        ),
        report(
            "boolean environment variable parsed outside env_bool in a shell script",
            check_shell(
                matching(files, SHELL_FILE_RE), Env.BOOLEAN_TRUE_VALUES, Env.BOOLEAN_FALSE_VALUES
            ),
            "Use `if env_bool NAME [DEFAULT]; then`; copy the env_bool block unchanged from "
            "src/auditor/entrypoint.sh and keep its values equal to Env.bool's.",
        ),
    ]
    if all(results):
        print("Environment conventions: OK")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
