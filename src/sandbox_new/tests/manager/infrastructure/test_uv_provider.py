"""Parsing of the lock file `uv pip compile --generate-hashes` writes.

Only the parsing is covered here: everything else on ``UVProvider`` shells out to uv.
"""

from manager.infrastructure.providers import UVProvider

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
