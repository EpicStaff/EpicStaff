"""Parsing of the lock file `uv pip compile --generate-hashes` writes and of uv's stderr.

Only the parsing is covered here: everything else on ``UVProvider`` shells out to uv.

The stderr samples are copied verbatim from the uv the image pins (0.11.21), box drawing
and mid-sentence wrapping included, because that is the shape the parser meets in
production. One sample from a newer uv (0.12) is kept as well: it words the same failure
differently, and a developer running the service outside the image sees that one.
"""

from manager.domain.errors import (
    UVBuildError,
    UVDependencyResolutionError,
    UVPackageNotFoundError,
    UVVersionNotFoundError,
)
from manager.infrastructure.providers import UVProvider
from manager.infrastructure.providers.uv_provider import _parse_stderr

# Modelled on uv's output, plus one name uv itself never emits: it normalizes names, so
# `zope.interface` would reach the lock as `zope-interface`. The non-normalized spelling
# is kept as a defensive case -- the parser normalizes names rather than trusting them.
LOCK_FILE = """\
litestar==2.9.1 \\
    --hash=sha256:1111111111111111111111111111111111111111111111111111111111111111 \\
    --hash=sha256:2222222222222222222222222222222222222222222222222222222222222222
Pillow==11.0.0 \\
    --hash=sha256:3333333333333333333333333333333333333333333333333333333333333333
zope.interface==7.1 ; python_version >= "3.9" \\
    --hash=sha256:4444444444444444444444444444444444444444444444444444444444444444
uvicorn[standard]==0.30.0
"""


def write_lock(venv_path, content: str):
    venv_path.mkdir(parents=True, exist_ok=True)
    lock_file = UVProvider.get_lock_file(venv_path)
    lock_file.write_text(content)
    return lock_file


def test_every_pin_resolves_to_its_version(tmp_path):
    write_lock(tmp_path / "venv-1", LOCK_FILE)

    assert UVProvider.read_resolved_versions(tmp_path / "venv-1") == {
        "litestar": "2.9.1",
        "pillow": "11.0.0",
        "zope-interface": "7.1",
        "uvicorn": "0.30.0",
    }


def test_an_environment_marker_stays_out_of_the_version(tmp_path):
    write_lock(tmp_path / "venv-1", 'httpx==0.27.0 ; python_version >= "3.9"\n')

    assert UVProvider.read_resolved_versions(tmp_path / "venv-1") == {"httpx": "0.27.0"}


def test_hash_continuation_lines_are_not_mistaken_for_pins(tmp_path):
    write_lock(
        tmp_path / "venv-1",
        "httpx==0.27.0 \\\n"
        "    --hash=sha256:5555555555555555555555555555555555555555555555555555555555555555\n",
    )

    assert UVProvider.read_resolved_versions(tmp_path / "venv-1") == {"httpx": "0.27.0"}


def test_a_venv_without_a_lock_file_resolves_nothing(tmp_path):
    (tmp_path / "venv-1").mkdir()

    assert UVProvider.read_resolved_versions(tmp_path / "venv-1") == {}


def test_a_local_version_segment_survives_parsing(tmp_path):
    write_lock(tmp_path / "venv-1", "torch==2.1.0+cu118\n")

    assert UVProvider.read_resolved_versions(tmp_path / "venv-1") == {"torch": "2.1.0+cu118"}


COMPILE_ARGS = (
    "pip",
    "compile",
    "--no-config",
    "--no-progress",
    "--generate-hashes",
    "--no-header",
    "--no-annotate",
    "--python",
    "/venv/bin/python",
    "--output-file",
    "/venv/requirements.lock",
    "-",
)
VENV_ARGS = ("venv", "--no-config", "--no-progress", "--python", "3.12", "/venv")

PACKAGE_NOT_FOUND_STDERR = (
    "  \u00d7 No solution found when resolving dependencies:\n"
    "  \u2570\u2500\u25b6 Because pydanticsdf was not found in the package registry and you\n"
    "      require pydanticsdf, we can conclude that your requirements are\n"
    "      unsatisfiable.\n"
)

NO_SUCH_VERSION_STDERR = (
    "  \u00d7 No solution found when resolving dependencies:\n"
    "  \u2570\u2500\u25b6 Because there is no version of requests==99.99.99 and you require\n"
    "      requests==99.99.99, we can conclude that your requirements are\n"
    "      unsatisfiable.\n"
)

NO_VERSION_IN_RANGE_STDERR = (
    "  \u00d7 No solution found when resolving dependencies:\n"
    "  \u2570\u2500\u25b6 Because only requests<=2.34.2 is available and you require\n"
    "      requests>=99.0, we can conclude that your requirements are\n"
    "      unsatisfiable.\n"
)

CONFLICT_STDERR = (
    "  \u00d7 No solution found when resolving dependencies:\n"
    "  \u2570\u2500\u25b6 Because requests==2.31.0 depends on urllib3>=1.21.1,<3 and you require\n"
    "      requests==2.31.0, we can conclude that you require urllib3>=1.21.1,<3.\n"
    "      And because you require urllib3==1.0, we can conclude that your\n"
    "      requirements are unsatisfiable.\n"
)

UNPARSEABLE_REQUIREMENT_STDERR = (
    "error: Couldn't parse requirement in `-` at position 0\n"
    "  Caused by: Expected one of `@`, `(`, `<`, `=`, `>`, `~`, `!`, `;`, found `i`\n"
    "this is not a requirement!!\n"
    "     ^\n"
)

NEWER_UV_PACKAGE_NOT_FOUND_STDERR = (
    "error: No solution found when resolving dependencies\n"
    "  cause: Because pydanticsdf was not found in the package registry and you "
    "require pydanticsdf, we can conclude that your requirements are unsatisfiable.\n"
)


def test_a_missing_package_names_the_package():
    error = _parse_stderr(COMPILE_ARGS, PACKAGE_NOT_FOUND_STDERR)

    assert isinstance(error, UVPackageNotFoundError)
    assert str(error) == "Package 'pydanticsdf' does not exist."


def test_a_missing_package_is_named_whichever_way_uv_words_it():
    error = _parse_stderr(COMPILE_ARGS, NEWER_UV_PACKAGE_NOT_FOUND_STDERR)

    assert isinstance(error, UVPackageNotFoundError)
    assert str(error) == "Package 'pydanticsdf' does not exist."


def test_a_pinned_version_that_does_not_exist_names_package_and_pin():
    error = _parse_stderr(COMPILE_ARGS, NO_SUCH_VERSION_STDERR)

    assert isinstance(error, UVVersionNotFoundError)
    assert str(error) == "Package 'requests' has no version matching '==99.99.99'."


def test_a_range_no_release_satisfies_names_package_and_range():
    error = _parse_stderr(COMPILE_ARGS, NO_VERSION_IN_RANGE_STDERR)

    assert isinstance(error, UVVersionNotFoundError)
    assert str(error) == "Package 'requests' has no version matching '>=99.0'."


def test_conflicting_requirements_name_the_package_whose_dependencies_clash():
    error = _parse_stderr(COMPILE_ARGS, CONFLICT_STDERR)

    assert isinstance(error, UVDependencyResolutionError)
    assert "requests" in str(error)


def test_a_failure_that_is_not_a_resolution_failure_falls_back_to_the_build_error():
    error = _parse_stderr(COMPILE_ARGS, UNPARSEABLE_REQUIREMENT_STDERR)

    assert type(error) is UVBuildError


def test_a_resolution_failure_uv_words_differently_falls_back_to_the_build_error():
    error = _parse_stderr(
        COMPILE_ARGS,
        "  \u00d7 No solution found when resolving dependencies:\n"
        "  \u2570\u2500\u25b6 Because the moon is in the wrong phase, we can conclude that\n"
        "      your requirements are unsatisfiable.\n",
    )

    assert type(error) is UVBuildError


def test_the_fallback_message_does_not_send_the_user_to_the_logs():
    """The message reaches the venv list in the UI, where no log is in reach."""
    message = str(_parse_stderr(COMPILE_ARGS, UNPARSEABLE_REQUIREMENT_STDERR))

    assert "log" not in message.lower()


def test_a_command_other_than_pip_compile_or_sync_is_not_parsed():
    error = _parse_stderr(VENV_ARGS, PACKAGE_NOT_FOUND_STDERR)

    assert type(error) is UVBuildError
    assert "pydanticsdf" not in str(error)


def test_pip_sync_is_parsed_like_pip_compile():
    error = _parse_stderr(
        ("pip", "sync", "--no-config", "/venv/requirements.lock"),
        PACKAGE_NOT_FOUND_STDERR,
    )

    assert isinstance(error, UVPackageNotFoundError)
    assert "pydanticsdf" in str(error)


def test_a_package_name_is_normalized():
    error = _parse_stderr(
        COMPILE_ARGS,
        "  \u00d7 No solution found when resolving dependencies:\n"
        "  \u2570\u2500\u25b6 Because there is no version of Zope.Interface==99.0 and you\n"
        "      require Zope.Interface==99.0, we can conclude that your requirements\n"
        "      are unsatisfiable.\n",
    )

    assert isinstance(error, UVVersionNotFoundError)
    assert str(error) == "Package 'zope-interface' has no version matching '==99.0'."
