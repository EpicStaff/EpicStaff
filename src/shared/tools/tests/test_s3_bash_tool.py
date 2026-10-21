"""s3_bash_tool: a small bash dialect over the org's S3 storage.

Every case seeds the in-memory S3 fake, runs one or more commands through the
tool's `main()` and checks what the agent sees and what the bucket holds after.
"""

from dataclasses import dataclass, field

import pytest
from conftest import load_tool, seed

tool = load_tool("s3_bash_tool")

TWENTY_LINES = "\n".join(f"line{i}" for i in range(20))


@dataclass
class Case:
    command: str | list[str]
    files: dict[str, str] = field(default_factory=dict)
    contains: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()
    equals: str | None = None
    # Compared with runs of whitespace collapsed (wc pads its columns like coreutils).
    columns: str | None = None
    # Bucket after the command: path -> body, or None for "must not exist".
    bucket: dict[str, str | None] = field(default_factory=dict)


def _run(fake_client, case: Case) -> str:
    for path, body in case.files.items():
        seed(fake_client, path, body)
    commands = [case.command] if isinstance(case.command, str) else case.command
    for command in commands:
        result = tool.main(command=command)
    return result


def _check(fake_client, case: Case, result: str) -> None:
    for expected in case.contains:
        assert expected in result
    for unexpected in case.excludes:
        assert unexpected not in result
    if case.equals is not None:
        assert result == case.equals
    if case.columns is not None:
        assert " ".join(result.split()) == case.columns
    for path, body in case.bucket.items():
        if body is None:
            assert path not in fake_client.objects
        else:
            assert fake_client.objects[path]["Body"] == body.encode()


def cases(table: dict[str, Case]):
    return pytest.mark.parametrize("case", list(table.values()), ids=list(table))


READING = {
    # ls
    "ls-flat": Case("ls dir", {"dir/a.txt": "x", "dir/sub/b.txt": "y"}, contains=("a.txt", "sub/"), excludes=("b.txt",)),
    "ls-recursive": Case("ls -R dir", {"dir/a.txt": "x", "dir/sub/b.txt": "y"}, contains=("dir/a.txt", "dir/sub/b.txt")),
    "ls-long-shows-size": Case("ls -l dir", {"dir/a.txt": "hello"}, contains=("5",)),
    "ls-combined-flags": Case("ls -lR dir", {"dir/a.txt": "hello"}, contains=("dir/a.txt", "5")),
    "ls-missing": Case("ls nowhere", contains=("No files or folders found",)),
    "ls-glob": Case("ls dir/*.txt", {"dir/a.txt": "x", "dir/b.log": "y"}, contains=("dir/a.txt",), excludes=("dir/b.log",)),
    "glob-star-stays-in-folder": Case("ls dir/*.txt", {"dir/a.txt": "x", "dir/sub/b.txt": "y"}, contains=("dir/a.txt",), excludes=("dir/sub/b.txt",)),
    "glob-top-level-star": Case("ls *.txt", {"a.txt": "x", "dir/b.txt": "y"}, contains=("a.txt",), excludes=("dir/b.txt",)),
    "glob-question-mark-not-slash": Case("ls dir?file.txt", {"dir/file.txt": "x", "dirXfile.txt": "y"}, contains=("dirXfile.txt",), excludes=("dir/file.txt",)),
    # cat
    "cat": Case("cat a.txt", {"a.txt": "hello\nworld"}, equals="hello\nworld"),
    "cat-line-numbers": Case("cat -n a.txt", {"a.txt": "hello\nworld"}, contains=("1\thello", "2\tworld")),
    "cat-several-with-headers": Case("cat a.txt b.txt", {"a.txt": "AAA", "b.txt": "BBB"}, contains=("==> a.txt <==", "==> b.txt <==", "AAA", "BBB")),
    "cat-missing": Case("cat missing.txt", contains=("File not found",)),
    "cat-glob": Case("cat logs/*.log", {"logs/a.log": "AAA", "logs/b.log": "BBB"}, contains=("AAA", "BBB")),
    "cat-glob-no-match": Case("cat missing*.txt", {"a.txt": "x"}, contains=("no matches for pattern",)),
    "cat-folder": Case("cat dir/", {"dir/a.txt": "x"}, contains=("folder",)),
    "cat-quoted-path-with-space": Case('cat "my file.txt"', {"my file.txt": "hello there"}, equals="hello there"),
    # head / tail
    "head-default-ten": Case("head a.txt", {"a.txt": TWENTY_LINES}, contains=("line0", "line9"), excludes=("line10",)),
    "head-n": Case("head -n 3 a.txt", {"a.txt": TWENTY_LINES}, equals="line0\nline1\nline2"),
    "tail-n": Case("tail -n 2 a.txt", {"a.txt": TWENTY_LINES}, equals="line18\nline19"),
    "head-needs-one-path": Case("head *.txt", {"a.txt": "x", "b.txt": "y"}, contains=("single path",)),
    "head-n-not-integer": Case("head -n abc a.txt", {"a.txt": "x"}, contains=("integer",)),
    # "a\nb\n" has two lines; a naive split would add a phantom "" line.
    "tail-trailing-newline": Case("tail -n 1 a.txt", {"a.txt": "a\nb\n"}, equals="b"),
    "head-trailing-newline": Case("head -n 2 a.txt", {"a.txt": "a\nb\n"}, equals="a\nb"),
    # wc
    "wc": Case("wc a.txt", {"a.txt": "hello world\nfoo"}, columns="1 3 15 a.txt"),
    "wc-lines": Case("wc -l a.txt", {"a.txt": "a\nb\nc"}, columns="2 a.txt"),
    "wc-several-with-total": Case("wc -w a.txt b.txt", {"a.txt": "one two", "b.txt": "three"}, contains=("total",)),
    # grep
    "grep": Case("grep hello a.txt", {"a.txt": "hello\nworld"}, contains=("a.txt: hello",), excludes=("a.txt:1:",)),
    "grep-line-numbers": Case("grep -n hello a.txt", {"a.txt": "hello\nworld\nhello again"}, contains=("a.txt:1: hello", "a.txt:3: hello again")),
    "grep-ignore-case": Case("grep -i hello a.txt", {"a.txt": "Hello World"}, contains=("Hello World",)),
    "grep-files-with-matches": Case("grep -l target", {"a.txt": "target", "b.txt": "nope"}, equals="a.txt"),
    "grep-not-recursive-by-default": Case("grep target", {"a.txt": "target", "dir/b.txt": "target"}, contains=("a.txt",), excludes=("dir/b.txt",)),
    "grep-recursive": Case("grep -r target", {"a.txt": "target", "dir/b.txt": "target"}, contains=("a.txt", "dir/b.txt")),
    "grep-combined-flags": Case("grep -rin target dir", {"dir/a.txt": "Target here"}, contains=("dir/a.txt:1: Target here",)),
    "grep-quoted-pipe-is-a-pattern": Case('grep "(abc|def)" a.txt', {"a.txt": "abc\ndef\nxyz"}, contains=("abc", "def"), excludes=("xyz",)),
    "grep-invalid-regex": Case("grep [unclosed a.txt", contains=("Invalid regex",)),
    # find
    "find": Case("find", {"dir/a.py": "x", "dir/sub/b.txt": "y"}, contains=("dir/a.py", "dir/sub/b.txt", "dir\n", "dir/sub\n")),
    "find-folders": Case("find -type d", {"dir/a.py": "x", "dir/sub/b.txt": "y"}, contains=("dir", "dir/sub"), excludes=("dir/a.py",)),
    "find-name": Case("find dir -name *.py", {"dir/a.py": "x", "dir/b.txt": "y"}, contains=("dir/a.py",), excludes=("dir/b.txt",)),
    "find-bad-type": Case("find -type x", {"a.py": "x"}, contains=("must be 'f' or 'd'",)),
    # stat / du / diff / test
    "stat-file": Case("stat a.txt", {"a.txt": "hello"}, contains=("type: file", "size: 5 bytes")),
    "stat-folder": Case("stat dir", {"dir/a.txt": "x"}, contains=("type: folder", "entries: 1")),
    "stat-missing": Case("stat missing.txt", contains=("File not found",)),
    "du-total": Case("du", {"a.txt": "hello", "dir/b.txt": "abc"}, contains=("8", "(total)")),
    "du-summary": Case("du -s", {"a.txt": "hello", "dir/b.txt": "abc"}, contains=("8",), excludes=("(total)",)),
    "du-missing": Case("du missing", contains=("No such file or folder",)),
    "du-empty-folder": Case("du emptydir", {"emptydir/.keep": ""}, contains=("0",)),
    "diff": Case("diff a.txt b.txt", {"a.txt": "line1\nline2\n", "b.txt": "line1\nlineX\n"}, contains=("-line2", "+lineX")),
    "diff-identical": Case("diff a.txt b.txt", {"a.txt": "same content", "b.txt": "same content"}, contains=("identical",)),
    "test-exists": Case("test -e a.txt", {"a.txt": "x"}, equals="true"),
    "test-missing": Case("test -e missing.txt", equals="false"),
    "bracket-form": Case("[ -e a.txt ]", {"a.txt": "x"}, equals="true"),
    "bracket-unclosed": Case("[ -e a.txt", contains=("missing closing",)),
    # echo
    "echo": Case("echo hello world", equals="hello world"),
    "echo-no-trailing-newline": Case("echo hi", equals="hi"),
    "quoted-dollar-is-literal": Case("echo '$HOME'", equals="$HOME"),
    # parsing
    "empty-command": Case("", contains=("no command given",)),
    "unknown-command-points-to-tools": Case("foobar something", contains=("Unknown command 'foobar'", "s3_grep_tool")),
}


@cases(READING)
def test_reading_commands(patched_storage, fake_client, case):
    _check(fake_client, case, _run(fake_client, case))


WRITING = {
    "mkdir": Case("mkdir newdir", contains=("Folder created: newdir.",), bucket={"newdir/.keep": ""}),
    "mkdir-existing": Case("mkdir existing", {"existing/file.txt": "x"}, contains=("already exists",)),
    "mkdir-missing-parent": Case("mkdir a/b/c", contains=("parent folder", "does not exist"), bucket={"a/b/c/.keep": None}),
    "mkdir-p": Case("mkdir -p a/b/c", contains=("Folder created: a/b/c.",)),
    "rm": Case("rm a.txt", {"a.txt": "x"}, contains=("Deleted a.txt.",), bucket={"a.txt": None}),
    "rm-folder-needs-r": Case("rm dir", {"dir/a.txt": "x"}, contains=("pass -r",), bucket={"dir/a.txt": "x"}),
    "rm-r": Case("rm -r dir", {"dir/a.txt": "x", "dir/b.txt": "y"}, contains=("Deleted folder dir",), bucket={"dir/a.txt": None, "dir/b.txt": None}),
    "rm-root-empty": Case("rm ''", {"a.txt": "x"}, contains=("refusing to remove root",), bucket={"a.txt": "x"}),
    "rm-root-slash": Case("rm /", {"a.txt": "x"}, contains=("refusing to remove root",), bucket={"a.txt": "x"}),
    "rm-root-dot": Case("rm .", {"a.txt": "x"}, contains=("refusing to remove root",), bucket={"a.txt": "x"}),
    "rm-missing": Case("rm missing.txt", contains=("cannot remove",)),
    "rm-f-missing": Case("rm -f missing.txt", contains=("ignored",), excludes=("cannot remove",)),
    "rm-several": Case("rm a.txt b.txt", {"a.txt": "x", "b.txt": "y"}, contains=("Deleted a.txt.", "Deleted b.txt."), bucket={"a.txt": None, "b.txt": None}),
    "rm-glob-no-match": Case("rm missing*.txt", contains=("no matches for pattern",)),
    "rm-f-glob-no-match": Case("rm -f missing*.txt", equals="Nothing to remove."),
    "mv": Case("mv a.txt b.txt", {"a.txt": "hello"}, contains=("Moved a.txt to b.txt.",), bucket={"a.txt": None, "b.txt": "hello"}),
    "mv-folder-refused": Case("mv dir otherdir", {"dir/a.txt": "x"}, contains=("folder", "cp -r"), bucket={"dir/a.txt": "x"}),
    "cp": Case("cp a.txt b.txt", {"a.txt": "hello"}, contains=("Copied a.txt to b.txt.",), bucket={"a.txt": "hello", "b.txt": "hello"}),
    "cp-folder-needs-r": Case("cp srcdir dstdir", {"srcdir/a.txt": "x"}, contains=("use cp -r",)),
    "cp-r": Case(
        "cp -r srcdir dstdir", {"srcdir/a.txt": "AAA", "srcdir/sub/b.txt": "BBB"}, contains=("2 file(s)",),
        bucket={"dstdir/a.txt": "AAA", "dstdir/sub/b.txt": "BBB", "srcdir/a.txt": "AAA"},
    ),
    "cp-glob-into-folder": Case(
        "cp logs/*.log archive/", {"logs/a.log": "AAA", "logs/b.log": "BBB"}, contains=("2 file(s)",),
        bucket={"archive/a.log": "AAA", "archive/b.log": "BBB"},
    ),
    "touch": Case("touch newfile.txt", contains=("Created empty file: newfile.txt.",), bucket={"newfile.txt": ""}),
    "touch-existing-keeps-content": Case("touch a.txt", {"a.txt": "hello"}, contains=("already exists",), bucket={"a.txt": "hello"}),
    "touch-folder": Case("touch dir", {"dir/a.txt": "x"}, contains=("is a folder",)),
    "echo-redirect-creates": Case("echo hi > out.txt", contains=("Wrote",), bucket={"out.txt": "hi\n"}),
    "echo-redirect-overwrites": Case("echo new > out.txt", {"out.txt": "old content here"}, bucket={"out.txt": "new\n"}),
    "echo-append": Case("echo def >> out.txt", {"out.txt": "abc"}, contains=("Appended",), bucket={"out.txt": "abcdef\n"}),
    "echo-append-twice-separate-lines": Case(["echo a >> out.txt", "echo b >> out.txt"], bucket={"out.txt": "a\nb\n"}),
    "cat-redirect-writes-rendered-output": Case("cat -n a.txt > out.txt", {"a.txt": "hello"}, contains=("Wrote",), bucket={"out.txt": "     1\thello"}),
    "redirect-only-for-echo-and-cat": Case("ls dir > out.txt", {"dir/a.txt": "x"}, contains=("not supported",), bucket={"out.txt": None}),
}


@cases(WRITING)
def test_writing_commands(patched_storage, fake_client, case):
    _check(fake_client, case, _run(fake_client, case))


@pytest.mark.parametrize(
    ("command", "message"),
    [
        ("cat a.txt | grep foo", "Pipes"),
        ("cat a.txt && echo hi", "chaining"),
        ("cat a.txt || echo hi", "chaining"),
        ("cat a.txt; echo hi", "chaining"),
        ("echo $HOME", "Variables"),
        ("echo `whoami`", "backticks"),
        ("echo $(whoami)", "Subshells"),
        ("cat < a.txt", "Input redirection"),
    ],
)
def test_shell_features_outside_the_dialect_are_refused(patched_storage, fake_client, command, message):
    seed(fake_client, "a.txt", "foo")

    result = tool.main(command=command)

    assert message.lower() in result.lower()
    assert set(fake_client.objects) == {"a.txt"}


def test_output_is_capped(patched_storage, fake_client, monkeypatch):
    monkeypatch.setattr(tool, "_MAX_OUTPUT_CHARS", 20)
    seed(fake_client, "a.txt", "x" * 200)

    result = tool.main(command="cat a.txt")

    assert "output truncated" in result
