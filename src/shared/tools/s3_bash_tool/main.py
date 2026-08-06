from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Import-time only, for static type checkers. Runtime code never hits
    # this branch — every function below spells the annotation as the
    # string "EpicStaffStorage" so it is never evaluated eagerly. This
    # module must NOT use `from __future__ import annotations`: the sandbox
    # (`src/sandbox/dynamic_venv_executor_chain.py` ExecuteCodeHandler.wrap_code)
    # prepends its own `import sys` / `import json` / try-block header before
    # this file's body when assembling the executed `code.py`, and a
    # `from __future__` import is only legal as the first statement in a
    # module — prepending anything ahead of it is a SyntaxError at exec time.
    from epicstaff_storage import EpicStaffStorage

# =====================================================================
# Constants
# =====================================================================

_MAX_OUTPUT_CHARS = 30_000
_MAX_MATCHES = 250
_GLOB_CHARS = "*?["

_REDIRECT_ALLOWED = frozenset({"echo", "cat"})

_SUPPORTED_COMMANDS = (
    "ls",
    "cat",
    "head",
    "tail",
    "wc",
    "grep",
    "find",
    "mkdir",
    "rm",
    "mv",
    "cp",
    "touch",
    "stat",
    "du",
    "diff",
    "echo",
    "test",
)

_USAGE = (
    "s3_bash_tool: no command given. Supported commands: "
    + ", ".join(_SUPPORTED_COMMANDS)
    + ", [ (test alias). One command per call — no pipes, chaining, subshells, "
    "variables, or input redirection."
)


# =====================================================================
# Syntax rejection — pre-shlex scan of the raw command string
# =====================================================================


def _check_unsupported_syntax(command: str) -> None:
    """Reject shell metacharacters this tool cannot support, scanning the raw
    string so quoting is honored (shlex would otherwise strip the quotes that
    made a metacharacter literal, e.g. a ``|`` inside a quoted grep pattern).
    """
    in_single = False
    in_double = False
    i = 0
    n = len(command)
    while i < n:
        ch = command[i]

        if in_single:
            if ch == "'":
                in_single = False
            i += 1
            continue

        if in_double:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == '"':
                in_double = False
            i += 1
            continue

        if ch == "'":
            in_single = True
            i += 1
            continue
        if ch == '"':
            in_double = True
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            i += 2
            continue

        if ch == "|":
            if i + 1 < n and command[i + 1] == "|":
                raise ValueError(
                    "Command chaining ('||') is not supported — run one command "
                    "per call to this tool."
                )
            raise ValueError(
                "Pipes ('|') are not supported — run one command and filter "
                "with grep, or use the dedicated s3_grep_tool."
            )
        if ch == "&":
            if i + 1 < n and command[i + 1] == "&":
                raise ValueError(
                    "Command chaining ('&&') is not supported — run one command "
                    "per call to this tool."
                )
            raise ValueError(
                "Background execution ('&') is not supported — run one command "
                "per call to this tool."
            )
        if ch == ";":
            raise ValueError(
                "Command chaining (';') is not supported — run one command per "
                "call to this tool."
            )
        if ch == "`":
            raise ValueError(
                "Subshells/backticks are not supported — command substitution "
                "cannot run here; pass a literal value instead."
            )
        if ch == "$":
            if i + 1 < n and command[i + 1] == "(":
                raise ValueError(
                    "Subshells ('$(...)') are not supported — command "
                    "substitution cannot run here; pass a literal value instead."
                )
            raise ValueError(
                "Variables ('$') are not supported — pass a literal value "
                "instead of a shell variable."
            )
        if ch == "<":
            raise ValueError(
                "Input redirection ('<') is not supported — this tool has no "
                "stdin; pass file paths as arguments instead."
            )

        i += 1

    if in_single or in_double:
        raise ValueError("Unbalanced quotes in command.")


def _extract_redirect(
    tokens: list[str],
) -> tuple[list[str], str | None, str | None]:
    """Split a trailing ``> target`` / ``>> target`` off the token list."""
    if len(tokens) >= 2 and tokens[-2] in (">", ">>"):
        return tokens[:-2], tokens[-2], tokens[-1]
    return tokens, None, None


# =====================================================================
# Flag / positional argument parsing
# =====================================================================


def _parse_args(
    tokens: list[str], spec: dict[str, str]
) -> tuple[dict[str, object], list[str]]:
    """Parse ``tokens`` against a flag ``spec`` mapping flag string (e.g.
    ``"-l"``, ``"-name"``) to ``"bool"`` or ``"value"``.

    Single-character boolean flags may be combined in one token (``-lR``).
    Everything after a literal ``--`` is treated as positional, even if it
    looks like a flag — the escape hatch for a pattern/text argument that
    itself starts with ``-``.
    """
    values: dict[str, object] = {}
    positionals: list[str] = []
    i = 0
    n = len(tokens)
    literal_only = False

    while i < n:
        tok = tokens[i]

        if literal_only:
            positionals.append(tok)
            i += 1
            continue

        if tok == "--":
            literal_only = True
            i += 1
            continue

        if tok in spec:
            kind = spec[tok]
            if kind == "bool":
                values[tok] = True
                i += 1
            else:
                if i + 1 >= n:
                    raise ValueError(f"Flag '{tok}' requires a value.")
                values[tok] = tokens[i + 1]
                i += 2
            continue

        if len(tok) > 1 and tok[0] == "-":
            chars = tok[1:]
            if chars and all(
                f"-{c}" in spec and spec[f"-{c}"] == "bool" for c in chars
            ):
                for c in chars:
                    values[f"-{c}"] = True
                i += 1
                continue
            raise ValueError(
                f"Unknown flag '{tok}' for this command. Use '--' before a "
                "value that starts with '-' if it isn't meant as a flag."
            )

        positionals.append(tok)
        i += 1

    return values, positionals


# =====================================================================
# Glob expansion
# =====================================================================


def _glob_to_regex(pattern: str):
    """Translate a shell-style glob to a compiled regex where ``*`` and ``?``
    respect ``/`` as a path-segment boundary (unlike ``fnmatch``, which lets
    ``*``/``?`` match across ``/``). This mirrors real shell globbing: a bare
    ``*`` never descends into a subfolder. There is no ``**`` cross-boundary
    escape hatch here — for recursive-anywhere matching use the dedicated
    ``s3_glob_tool`` instead, which intentionally keeps the fnmatch-style
    (boundary-crossing) convention.
    """
    import re

    parts = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            parts.append("[^/]*")
            i += 1
        elif c == "?":
            parts.append("[^/]")
            i += 1
        elif c == "[":
            j = i + 1
            if j < n and pattern[j] == "!":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:
                parts.append(re.escape(c))
                i += 1
            else:
                inner = pattern[i + 1 : j]
                if inner.startswith("!"):
                    inner = "^" + inner[1:]
                parts.append(f"[{inner}]")
                i = j + 1
        else:
            parts.append(re.escape(c))
            i += 1
    return re.compile("".join(parts))


def _expand_path(token: str, storage: "EpicStaffStorage") -> list[dict]:
    """Expand a single token to matching ``walk()`` entries (dicts with at
    least ``path``, plus ``size``/``modified`` when derived from a glob).
    Tokens without glob metacharacters pass through unchanged.
    """
    if not any(c in token for c in _GLOB_CHARS):
        return [{"path": token}]

    first_meta = min(i for i, c in enumerate(token) if c in _GLOB_CHARS)
    prefix = token[:first_meta]
    scope = prefix.rsplit("/", 1)[0] if "/" in prefix else ""

    regex = _glob_to_regex(token)
    entries = storage.walk(scope)
    matched = [e for e in entries if regex.fullmatch(e["path"])]
    if not matched:
        raise ValueError(f"no matches for pattern '{token}'.")
    return sorted(matched, key=lambda e: e["path"])


def _expand_paths_only(tokens: list[str], storage: "EpicStaffStorage") -> list[str]:
    paths: list[str] = []
    for tok in tokens:
        paths.extend(e["path"] for e in _expand_path(tok, storage))
    return paths


def _expand_single_path(token: str, storage: "EpicStaffStorage") -> str:
    entries = _expand_path(token, storage)
    if len(entries) > 1:
        raise ValueError(
            f"glob '{token}' matched {len(entries)} files — this command takes "
            "a single path; narrow the pattern."
        )
    return entries[0]["path"]


# =====================================================================
# Shared read / folder-guard helpers
# =====================================================================


def _is_folder(path: str, storage: "EpicStaffStorage") -> bool:
    if path == "" or path.endswith("/"):
        return True
    try:
        storage.info(path)
        return False
    except FileNotFoundError:
        return storage.exists(path)


def _guarded_read(path: str, storage: "EpicStaffStorage") -> tuple[str, int]:
    """Read a file's text content, enforcing the folder-vs-file guard and the
    storage read-size limit. Returns ``(content, size_in_bytes)``.
    """
    from epicstaff_storage.storage import MAX_LINE_READ_BYTES

    if path == "" or path.endswith("/"):
        raise ValueError(f"'{path}' is a folder — this command only operates on files.")
    try:
        info = storage.info(path)
    except FileNotFoundError:
        raise FileNotFoundError(f"File not found: {path}.") from None
    if info["size"] > MAX_LINE_READ_BYTES:
        raise RuntimeError(
            f"File '{path}' is {info['size']} bytes, exceeding the "
            f"{MAX_LINE_READ_BYTES // (1024 * 1024)} MB read limit."
        )
    return storage.read(path), info["size"]


def _cap_output(text: str) -> str:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    return (
        text[:_MAX_OUTPUT_CHARS]
        + "\n... output truncated — narrow the path/pattern or use the "
        "dedicated s3_* tools."
    )


def _skip_note(skipped_large: int, skipped_binary: int) -> str:
    parts = []
    if skipped_large:
        parts.append(f"{skipped_large} file(s) skipped (exceeds size limit)")
    if skipped_binary:
        parts.append(f"{skipped_binary} file(s) skipped (binary/non-utf8)")
    if not parts:
        return ""
    return " (" + "; ".join(parts) + ")"


# =====================================================================
# Per-command implementations
# =====================================================================


def _format_ls_flat(entry: dict, long: bool) -> str:
    marker = "/" if entry["type"] == "folder" else ""
    if not long:
        return f"{entry['name']}{marker}"
    modified = entry["modified"] or "-"
    return f"{entry['size']:>12}  {modified:<26}  {entry['name']}{marker}"


def _format_ls_recursive(entry: dict, long: bool) -> str:
    if not long:
        return entry["path"]
    modified = entry.get("modified") or "-"
    size = entry.get("size", 0)
    return f"{size:>12}  {modified:<26}  {entry['path']}"


def _cmd_ls(args: list[str], storage: "EpicStaffStorage") -> str:
    values, positionals = _parse_args(args, {"-l": "bool", "-R": "bool"})
    if len(positionals) > 1:
        raise ValueError("ls: usage: ls [-l] [-R] [path]")

    long = "-l" in values
    recursive = "-R" in values
    token = positionals[0] if positionals else ""

    if any(c in token for c in _GLOB_CHARS):
        entries = _expand_path(token, storage)
        entries.sort(key=lambda e: e["path"])
        lines = [_format_ls_recursive(e, long) for e in entries]
        return "\n".join(lines)

    try:
        entries = storage.walk(token) if recursive else storage.list(token)
    except FileNotFoundError:
        raise FileNotFoundError(f"Path not found: {token or '/'}.") from None

    if not entries:
        return f"No files or folders found under '{token or '/'}'."

    if recursive:
        entries = sorted(entries, key=lambda e: e["path"])
        lines = [_format_ls_recursive(e, long) for e in entries]
    else:
        entries = sorted(entries, key=lambda e: (e["type"] != "folder", e["name"]))
        lines = [_format_ls_flat(e, long) for e in entries]
    return "\n".join(lines)


def _cmd_cat(args: list[str], storage: "EpicStaffStorage") -> str:
    values, positionals = _parse_args(args, {"-n": "bool"})
    if not positionals:
        raise ValueError("cat: missing file operand.")

    show_numbers = "-n" in values
    paths = _expand_paths_only(positionals, storage)
    multi = len(paths) > 1

    parts: list[str] = []
    for path in paths:
        content, _ = _guarded_read(path, storage)
        if show_numbers:
            lines = content.split("\n")
            content = "\n".join(
                f"{i:>6}\t{line}" for i, line in enumerate(lines, start=1)
            )
        parts.append(f"==> {path} <==\n{content}" if multi else content)

    return "\n".join(parts)


def _head_or_tail(args: list[str], storage: "EpicStaffStorage", mode: str) -> str:
    values, positionals = _parse_args(args, {"-n": "value"})
    if len(positionals) != 1:
        raise ValueError(f"{mode}: usage: {mode} [-n N] <file>")

    n_str = str(values.get("-n", "10"))
    try:
        n = int(n_str)
    except ValueError:
        raise ValueError(f"{mode}: -n expects an integer, got '{n_str}'.") from None
    if n < 1:
        raise ValueError(f"{mode}: -n must be >= 1, got {n}.")

    path = _expand_single_path(positionals[0], storage)
    content, _ = _guarded_read(path, storage)

    from epicstaff_storage.storage import split_lines

    # split_lines drops the phantom trailing empty line that a plain
    # content.split("\n") would produce for a trailing-newline-terminated
    # file — without it `tail -n 1` on "a\nb\n" would return "" instead of
    # the real last line "b".
    lines = split_lines(content)
    selected = lines[:n] if mode == "head" else lines[-n:]
    return "\n".join(selected)


def _cmd_head(args: list[str], storage: "EpicStaffStorage") -> str:
    return _head_or_tail(args, storage, "head")


def _cmd_tail(args: list[str], storage: "EpicStaffStorage") -> str:
    return _head_or_tail(args, storage, "tail")


def _cmd_wc(args: list[str], storage: "EpicStaffStorage") -> str:
    values, positionals = _parse_args(args, {"-l": "bool", "-w": "bool", "-c": "bool"})
    if not positionals:
        raise ValueError("wc: missing file operand.")

    show_l = "-l" in values
    show_w = "-w" in values
    show_c = "-c" in values
    if not (show_l or show_w or show_c):
        show_l = show_w = show_c = True

    paths = _expand_paths_only(positionals, storage)

    rows: list[tuple[int, int, int, str]] = []
    for path in paths:
        content, size = _guarded_read(path, storage)
        lines = content.count("\n")
        words = len(content.split())
        rows.append((lines, words, size, path))

    def _fmt(lines: int, words: int, size: int, name: str) -> str:
        cols = []
        if show_l:
            cols.append(f"{lines:>7}")
        if show_w:
            cols.append(f"{words:>7}")
        if show_c:
            cols.append(f"{size:>7}")
        return " ".join(cols) + f" {name}"

    out = [_fmt(*row) for row in rows]
    if len(rows) > 1:
        total_l = sum(r[0] for r in rows)
        total_w = sum(r[1] for r in rows)
        total_c = sum(r[2] for r in rows)
        out.append(_fmt(total_l, total_w, total_c, "total"))
    return "\n".join(out)


def _cmd_grep(args: list[str], storage: "EpicStaffStorage") -> str:
    values, positionals = _parse_args(
        args, {"-r": "bool", "-i": "bool", "-n": "bool", "-l": "bool"}
    )
    if not positionals:
        raise ValueError("grep: usage: grep [-r] [-i] [-n] [-l] PATTERN [path]")
    if len(positionals) > 2:
        raise ValueError(
            "grep: too many arguments — usage: grep [-r] [-i] [-n] [-l] PATTERN [path]"
        )

    pattern = positionals[0]
    path = positionals[1] if len(positionals) > 1 else ""

    recursive = "-r" in values
    ignore_case = "-i" in values
    show_line_numbers = "-n" in values
    files_with_matches = "-l" in values

    import re

    try:
        regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as e:
        raise ValueError(f"Invalid regex pattern '{pattern}': {e}") from None

    is_probably_folder = path == "" or path.endswith("/")
    candidates: list[dict] | None = None
    if not is_probably_folder:
        try:
            info = storage.info(path)
            candidates = [{"path": path, "size": info["size"]}]
        except FileNotFoundError:
            candidates = None

    if candidates is None:
        if recursive:
            candidates = [
                {"path": e["path"], "size": e["size"]} for e in storage.walk(path)
            ]
        else:
            prefix = path.rstrip("/")
            candidates = [
                {
                    "path": f"{prefix}/{e['name']}" if prefix else e["name"],
                    "size": e["size"],
                }
                for e in storage.list(path)
                if e["type"] == "file"
            ]

    if not candidates:
        return f"No files found under '{path or '/'}'."

    from epicstaff_storage.storage import MAX_LINE_READ_BYTES

    matches: list[str] = []
    matched_files: set[str] = set()
    skipped_large = 0
    skipped_binary = 0
    match_cap_hit = False

    for entry in candidates:
        if entry["size"] > MAX_LINE_READ_BYTES:
            skipped_large += 1
            continue
        try:
            content = storage.read(entry["path"])
        except FileNotFoundError:
            continue
        except UnicodeDecodeError:
            skipped_binary += 1
            continue

        if files_with_matches:
            if regex.search(content):
                matched_files.add(entry["path"])
            continue

        for line_number, line in enumerate(content.split("\n"), start=1):
            if len(matches) >= _MAX_MATCHES:
                match_cap_hit = True
                break
            if regex.search(line):
                if show_line_numbers:
                    matches.append(f"{entry['path']}:{line_number}: {line}")
                else:
                    matches.append(f"{entry['path']}: {line}")
        if match_cap_hit:
            break

    skip_note = _skip_note(skipped_large, skipped_binary)

    if files_with_matches:
        if not matched_files:
            return f"No matches for pattern '{pattern}'.{skip_note}"
        return "\n".join(sorted(matched_files)) + skip_note

    if not matches:
        return f"No matches for pattern '{pattern}'.{skip_note}"

    text = "\n".join(matches)
    if match_cap_hit:
        text += (
            f"\n... showing partial results (cap {_MAX_MATCHES} matches) — "
            "narrow path or pattern to see more."
        )
    return text + skip_note


def _cmd_find(args: list[str], storage: "EpicStaffStorage") -> str:
    values, positionals = _parse_args(args, {"-name": "value", "-type": "value"})
    if len(positionals) > 1:
        raise ValueError("find: usage: find [path] [-name PATTERN] [-type f|d]")

    path = positionals[0] if positionals else ""
    name_pattern = values.get("-name")
    type_filter = values.get("-type")
    if type_filter not in (None, "f", "d"):
        raise ValueError(f"find: -type must be 'f' or 'd', got '{type_filter}'.")

    entries = storage.walk(path)
    if not entries and path and not storage.exists(path):
        raise FileNotFoundError(f"Path not found: {path}.")

    prefix = path.rstrip("/") + "/" if path else ""
    files = {e["path"] for e in entries}
    folders: set[str] = set()
    for e in entries:
        rel = (
            e["path"][len(prefix) :]
            if prefix and e["path"].startswith(prefix)
            else e["path"]
        )
        parts = rel.split("/")[:-1]
        acc = prefix
        for part in parts:
            acc = f"{acc}{part}/"
            folders.add(acc.rstrip("/"))

    results: set[str] = set()
    if type_filter in (None, "f"):
        results.update(files)
    if type_filter in (None, "d"):
        results.update(folders)

    if name_pattern:
        import fnmatch

        results = {
            p
            for p in results
            if fnmatch.fnmatchcase(p.rsplit("/", 1)[-1], name_pattern)
        }

    if not results:
        return f"No files matching under '{path or '/'}'."

    return "\n".join(sorted(results))


def _cmd_mkdir(args: list[str], storage: "EpicStaffStorage") -> str:
    values, positionals = _parse_args(args, {"-p": "bool"})
    if not positionals:
        raise ValueError("mkdir: missing operand.")

    parents = "-p" in values
    results = []
    for path in positionals:
        if storage.exists(path):
            results.append(f"mkdir: '{path}' already exists.")
            continue
        if not parents:
            stripped = path.rstrip("/")
            parent = stripped.rsplit("/", 1)[0] if "/" in stripped else ""
            if parent and not storage.exists(parent):
                results.append(
                    f"mkdir: cannot create '{path}': parent folder '{parent}' "
                    "does not exist (use -p to create intermediate folders)."
                )
                continue
        storage.mkdir(path)
        results.append(f"Folder created: {path}.")
    return "\n".join(results)


def _rm_one(
    path: str, storage: "EpicStaffStorage", recursive: bool, force: bool
) -> str:
    normalized = path.strip("/")
    if normalized in ("", "."):
        return f"rm: refusing to remove root path '{path}'."

    try:
        storage.info(path)
        is_file = True
    except FileNotFoundError:
        is_file = False

    if is_file:
        storage.delete(path)
        return f"Deleted {path}."

    if storage.exists(path):
        if not recursive:
            return f"rm: '{path}' is a folder — pass -r to delete it (e.g. 'rm -r {path}')."
        try:
            storage.delete_folder(path)
        except FileNotFoundError:
            if force:
                return f"rm: '{path}' not found (ignored, -f)."
            return f"rm: cannot remove '{path}': not found."
        return f"Deleted folder {path}."

    if force:
        return f"rm: '{path}' not found (ignored, -f)."
    return f"rm: cannot remove '{path}': not found."


def _cmd_rm(args: list[str], storage: "EpicStaffStorage") -> str:
    values, positionals = _parse_args(args, {"-r": "bool", "-f": "bool"})
    if not positionals:
        raise ValueError("rm: missing operand.")

    recursive = "-r" in values
    force = "-f" in values
    results: list[str] = []

    for token in positionals:
        try:
            expanded = _expand_path(token, storage)
        except ValueError as e:
            if force:
                continue
            results.append(f"rm: {e}")
            continue
        for entry in expanded:
            results.append(_rm_one(entry["path"], storage, recursive, force))

    return "\n".join(results) if results else "Nothing to remove."


def _cmd_cp(args: list[str], storage: "EpicStaffStorage") -> str:
    values, positionals = _parse_args(args, {"-r": "bool"})
    if len(positionals) < 2:
        raise ValueError("cp: usage: cp [-r] src... dst")

    *src_tokens, dst = positionals
    recursive = "-r" in values

    if (
        len(src_tokens) == 1
        and not any(c in src_tokens[0] for c in _GLOB_CHARS)
        and _is_folder(src_tokens[0], storage)
    ):
        if not recursive:
            raise ValueError(
                f"cp: -r not specified; omitting folder '{src_tokens[0]}' "
                "(use cp -r to copy a folder)."
            )
        src_folder = src_tokens[0]
        entries = storage.walk(src_folder)
        if not entries:
            raise FileNotFoundError(f"No such folder: {src_folder}.")
        src_prefix = src_folder.rstrip("/") + "/"
        dst_prefix = dst.rstrip("/") + "/"
        for e in entries:
            rel = (
                e["path"][len(src_prefix) :]
                if e["path"].startswith(src_prefix)
                else e["path"]
            )
            storage.copy(e["path"], dst_prefix + rel)
        return f"Copied folder {src_folder} to {dst} ({len(entries)} file(s))."

    sources = _expand_paths_only(src_tokens, storage)

    if len(sources) == 1 and not _is_folder(dst, storage):
        storage.copy(sources[0], dst)
        return f"Copied {sources[0]} to {dst}."

    dst_prefix = dst.rstrip("/") + "/"
    for src in sources:
        name = src.rsplit("/", 1)[-1]
        storage.copy(src, dst_prefix + name)
    return f"Copied {len(sources)} file(s) to {dst}."


def _cmd_mv(args: list[str], storage: "EpicStaffStorage") -> str:
    _values, positionals = _parse_args(args, {})
    if len(positionals) != 2:
        raise ValueError("mv: usage: mv src dst")

    src_token, dst = positionals
    if any(c in src_token for c in _GLOB_CHARS):
        matches = _expand_path(src_token, storage)
        if len(matches) > 1:
            raise ValueError(
                f"mv: glob '{src_token}' matched {len(matches)} files — mv "
                "moves a single source; narrow the pattern, or use cp -r + "
                "rm -r for a whole folder."
            )
        src = matches[0]["path"]
    else:
        src = src_token

    if _is_folder(src, storage):
        raise ValueError(
            f"mv: '{src}' is a folder — moving folders isn't supported directly "
            "(the storage backend moves single objects). Move files "
            "individually, or use cp -r then rm -r to relocate the whole folder."
        )

    dst_final = (
        dst.rstrip("/") + "/" + src.rsplit("/", 1)[-1]
        if _is_folder(dst, storage)
        else dst
    )
    storage.move(src, dst_final)
    return f"Moved {src} to {dst_final}."


def _cmd_touch(args: list[str], storage: "EpicStaffStorage") -> str:
    _values, positionals = _parse_args(args, {})
    if not positionals:
        raise ValueError("touch: missing operand.")

    results = []
    for path in positionals:
        try:
            storage.info(path)
            results.append(
                f"touch: '{path}' already exists (no-op — object storage has "
                "no separate timestamp update)."
            )
            continue
        except FileNotFoundError:
            pass
        if storage.exists(path):
            results.append(
                f"touch: '{path}' is a folder — cannot touch a folder as a file."
            )
            continue
        storage.write(path, "")
        results.append(f"Created empty file: {path}.")
    return "\n".join(results)


def _cmd_stat(args: list[str], storage: "EpicStaffStorage") -> str:
    _values, positionals = _parse_args(args, {})
    if len(positionals) != 1:
        raise ValueError("stat: usage: stat <path>")

    path = _expand_single_path(positionals[0], storage)
    if _is_folder(path, storage):
        entries = storage.list(path)
        return f"{path or '/'}\n  type: folder\n  entries: {len(entries)}"

    try:
        info = storage.info(path)
    except FileNotFoundError:
        raise FileNotFoundError(f"File not found: {path}.") from None
    return (
        f"{path}\n"
        f"  type: file\n"
        f"  size: {info['size']} bytes\n"
        f"  content_type: {info['content_type']}\n"
        f"  modified: {info['modified']}"
    )


def _cmd_du(args: list[str], storage: "EpicStaffStorage") -> str:
    values, positionals = _parse_args(args, {"-s": "bool"})
    if len(positionals) > 1:
        raise ValueError("du: usage: du [-s] [path]")

    path = positionals[0] if positionals else ""
    entries = storage.walk(path)
    label = path or "/"

    if not entries:
        if path == "" or storage.exists(path):
            return f"{0:>12}  {label}"
        raise FileNotFoundError(f"No such file or folder: {label}.")

    grand_total = sum(e["size"] for e in entries)
    if "-s" in values:
        return f"{grand_total:>12}  {label}"

    prefix = path.rstrip("/") + "/" if path else ""
    groups: dict[str, int] = {}
    for e in entries:
        rel = (
            e["path"][len(prefix) :]
            if prefix and e["path"].startswith(prefix)
            else e["path"]
        )
        top = rel.split("/", 1)[0]
        groups[top] = groups.get(top, 0) + e["size"]

    lines = [f"{size:>12}  {prefix}{name}" for name, size in sorted(groups.items())]
    lines.append(f"{grand_total:>12}  {label} (total)")
    return "\n".join(lines)


def _cmd_diff(args: list[str], storage: "EpicStaffStorage") -> str:
    _values, positionals = _parse_args(args, {"-u": "bool"})
    if len(positionals) != 2:
        raise ValueError("diff: usage: diff [-u] a b")

    path_a = _expand_single_path(positionals[0], storage)
    path_b = _expand_single_path(positionals[1], storage)
    content_a, _ = _guarded_read(path_a, storage)
    content_b, _ = _guarded_read(path_b, storage)

    import difflib

    diff_lines = list(
        difflib.unified_diff(
            content_a.splitlines(keepends=True),
            content_b.splitlines(keepends=True),
            fromfile=path_a,
            tofile=path_b,
        )
    )
    if not diff_lines:
        return f"'{path_a}' and '{path_b}' are identical."
    return "".join(diff_lines)


def _cmd_echo(args: list[str], _storage: "EpicStaffStorage") -> str:
    return " ".join(args)


def _cmd_test(args: list[str], storage: "EpicStaffStorage") -> str:
    if len(args) != 2 or args[0] != "-e":
        raise ValueError("test: usage: test -e <path>  (or: [ -e <path> ])")

    path = args[1]
    try:
        storage.info(path)
        exists = True
    except FileNotFoundError:
        exists = storage.exists(path)
    return "true" if exists else "false"


def _cmd_bracket(args: list[str], storage: "EpicStaffStorage") -> str:
    if not args or args[-1] != "]":
        raise ValueError("test: missing closing ']' — usage: [ -e <path> ]")
    return _cmd_test(args[:-1], storage)


# =====================================================================
# Command registry
# =====================================================================

_COMMANDS = {
    "ls": _cmd_ls,
    "cat": _cmd_cat,
    "head": _cmd_head,
    "tail": _cmd_tail,
    "wc": _cmd_wc,
    "grep": _cmd_grep,
    "find": _cmd_find,
    "mkdir": _cmd_mkdir,
    "rm": _cmd_rm,
    "mv": _cmd_mv,
    "cp": _cmd_cp,
    "touch": _cmd_touch,
    "stat": _cmd_stat,
    "du": _cmd_du,
    "diff": _cmd_diff,
    "echo": _cmd_echo,
    "test": _cmd_test,
    "[": _cmd_bracket,
}


def _unknown_command_error(name: str) -> str:
    return (
        f"Unknown command '{name}'. Supported commands: "
        + ", ".join(_SUPPORTED_COMMANDS)
        + ", [ (test alias). For pattern search across many files use the "
        "dedicated s3_grep_tool; for path globbing use s3_glob_tool; for a "
        "single well-tested operation see the other s3_* tools."
    )


# =====================================================================
# Entry point
# =====================================================================


def main(command: str) -> str:
    import shlex

    try:
        _check_unsupported_syntax(command)
    except ValueError as e:
        return str(e)

    try:
        tokens = shlex.split(command, posix=True)
    except ValueError as e:
        return f"Could not parse command: {e}"

    if not tokens:
        return _USAGE

    tokens, redirect_op, redirect_target = _extract_redirect(tokens)
    if not tokens:
        return _USAGE

    cmd_name, *cmd_args = tokens
    handler = _COMMANDS.get(cmd_name)
    if handler is None:
        return _unknown_command_error(cmd_name)

    if redirect_op is not None and cmd_name not in _REDIRECT_ALLOWED:
        return (
            f"Output redirection ('{redirect_op}') is not supported for "
            f"'{cmd_name}' — only 'echo' and 'cat' can write their output "
            "this way."
        )

    from epicstaff_storage import EpicStaffStorage

    storage = EpicStaffStorage()

    try:
        output = handler(cmd_args, storage)
    except FileNotFoundError as e:
        return str(e)
    except PermissionError as e:
        return str(e)
    except ValueError as e:
        return str(e)
    except RuntimeError as e:
        return str(e)

    if redirect_op is not None:
        # Real bash's `echo` always terminates its output with a newline,
        # including when redirected to a file — `echo a >> f; echo b >> f`
        # must land as "a\nb\n", not "ab". `cat`'s redirected output is the
        # rendered content verbatim (no newline injected), matching real
        # `cat > file` semantics.
        payload = output + "\n" if cmd_name == "echo" else output
        try:
            if redirect_op == ">":
                storage.write(redirect_target, payload)
                return f"Wrote {len(payload)} character(s) to {redirect_target}."
            storage.append_text(redirect_target, payload)
            return f"Appended {len(payload)} character(s) to {redirect_target}."
        except FileNotFoundError as e:
            return str(e)
        except PermissionError as e:
            return str(e)
        except ValueError as e:
            return str(e)
        except RuntimeError as e:
            return str(e)

    return _cap_output(output)
