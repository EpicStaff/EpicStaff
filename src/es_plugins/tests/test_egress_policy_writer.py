"""The egress proxy's policy files, as the agent writes them."""

import asyncio
import json
import os
import re
import stat
import threading

import bcrypt
import pytest
from loguru import logger

from es_plugins.egress import policy_writer
from es_plugins.egress.policy_writer import (
    HOSTS_FILE_NAME,
    PASSWORDS_FILE_NAME,
    EgressPolicyError,
    EgressPolicyWriter,
)

URL_SAFE = re.compile(r"^[A-Za-z0-9_-]+$")


@pytest.fixture
async def writer(tmp_path):
    policy = EgressPolicyWriter(tmp_path)
    await policy.start()
    return policy


def password_lines(directory) -> dict[str, str]:
    text = (directory / PASSWORDS_FILE_NAME).read_text()
    return dict(line.split(":", 1) for line in text.splitlines())


async def test_the_agent_starts_with_an_empty_policy(tmp_path):
    (tmp_path / PASSWORDS_FILE_NAME).write_text("weather:$2b$10$left-from-an-earlier-run\n")
    (tmp_path / HOSTS_FILE_NAME).write_text('{"weather": ["example.com"]}\n')

    await EgressPolicyWriter(tmp_path).start()

    assert (tmp_path / PASSWORDS_FILE_NAME).read_text() == ""
    assert json.loads((tmp_path / HOSTS_FILE_NAME).read_text()) == {}
    for name in (PASSWORDS_FILE_NAME, HOSTS_FILE_NAME):
        assert stat.S_IMODE(os.stat(tmp_path / name).st_mode) == 0o644


@pytest.mark.parametrize("problem", ["missing", "a file"])
async def test_the_agent_cannot_start_without_a_writable_policy_directory(tmp_path, problem):
    directory = tmp_path / "policy"
    if problem == "a file":
        directory.write_text("")

    with pytest.raises(EgressPolicyError, match=str(directory)):
        await EgressPolicyWriter(directory).start()


async def test_each_plugin_gets_a_url_safe_password_whose_bcrypt_hash_the_proxy_checks(writer, tmp_path):
    weather = await writer.issue_password("weather")
    probe = await writer.issue_password("probe-a")

    assert weather != probe
    for password in (weather, probe):
        assert URL_SAFE.match(password) and len(password) >= 32
    lines = password_lines(tmp_path)
    assert list(lines) == ["probe-a", "weather"]
    for identifier, password in (("weather", weather), ("probe-a", probe)):
        # bcrypt's lowest cost: the passwords are random tokens, and the proxy hashes per request.
        assert lines[identifier].startswith("$2b$04$")
        assert bcrypt.checkpw(password.encode(), lines[identifier].encode())


async def test_a_password_is_kept_until_it_is_removed_and_never_issued_again(writer, tmp_path):
    first = await writer.issue_password("weather")
    assert await writer.issue_password("weather") == first

    await writer.remove_password("weather")
    assert password_lines(tmp_path) == {}

    second = await writer.issue_password("weather")
    assert second != first
    assert bcrypt.checkpw(second.encode(), password_lines(tmp_path)["weather"].encode())


async def test_two_starts_at_once_share_one_password(writer, tmp_path):
    first, second = await asyncio.gather(writer.issue_password("weather"), writer.issue_password("weather"))

    assert first == second
    assert bcrypt.checkpw(first.encode(), password_lines(tmp_path)["weather"].encode())


async def test_hosts_list_one_sorted_key_per_placement_and_are_written_only_when_changed(writer, tmp_path):
    await writer.write_hosts(
        {"weather": ["geocoding-api.open-meteo.com", "*.wikipedia.org"], "notes": [], "alpha": ["api.example.org"]}
    )
    path = tmp_path / HOSTS_FILE_NAME
    text = path.read_text()
    inode = os.stat(path).st_ino

    assert list(json.loads(text)) == ["alpha", "notes", "weather"]
    assert json.loads(text)["weather"] == ["geocoding-api.open-meteo.com", "*.wikipedia.org"]
    assert json.loads(text)["notes"] == []

    await writer.write_hosts({"notes": [], "weather": ["geocoding-api.open-meteo.com", "*.wikipedia.org"], "alpha": ["api.example.org"]})
    assert os.stat(path).st_ino == inode


async def test_a_reader_never_sees_part_of_a_policy_file(writer, tmp_path):
    torn = []
    stop = threading.Event()

    def read_continuously():
        while not stop.is_set():
            for name in (HOSTS_FILE_NAME, PASSWORDS_FILE_NAME):
                try:
                    text = (tmp_path / name).read_text()
                except FileNotFoundError:
                    torn.append(f"{name} missing")
                    continue
                if name == HOSTS_FILE_NAME:
                    try:
                        json.loads(text)
                    except ValueError:
                        torn.append(text)
                elif text and not text.endswith("\n"):
                    torn.append(text)

    reader = threading.Thread(target=read_continuously)
    reader.start()
    try:
        for round_number in range(150):
            await writer.write_hosts({f"plugin-{index}": [f"host{round_number}.example.org"] * 20 for index in range(30)})
            if round_number % 15 == 0:
                await writer.issue_password(f"plugin-{round_number}")
    finally:
        stop.set()
        reader.join()

    assert torn == []
    assert sorted(path.name for path in tmp_path.iterdir()) == [HOSTS_FILE_NAME, PASSWORDS_FILE_NAME]


async def test_no_password_hash_or_host_reaches_a_log_line(writer):
    lines = []
    sink = logger.add(lines.append, format="{message}", level="DEBUG")
    try:
        password = await writer.issue_password("weather")
        await writer.write_hosts({"weather": ["geocoding-api.open-meteo.com"]})
        await writer.remove_password("weather")
    finally:
        logger.remove(sink)

    assert any(line.startswith("plugins.egress.policy_written users=1 hosts=0") for line in lines)
    assert any(line.startswith("plugins.egress.policy_written users=1 hosts=1") for line in lines)
    for secret in (password, "$2b$", "geocoding-api"):
        assert not [line for line in lines if secret in line]


class WholeSecondReader:
    """Reads the password file the way Squid's basic_ncsa_auth does: again only when the whole
    seconds of its modification time change."""

    def __init__(self, path):
        self._path = path
        self._seconds = None
        self.content = ""

    def check(self) -> str:
        seconds = int(os.stat(self._path).st_mtime)
        if seconds != self._seconds:
            self._seconds = seconds
            self.content = self._path.read_text()
        return self.content


async def test_a_password_written_within_the_same_second_still_reaches_squids_helper(writer, tmp_path):
    reader = WholeSecondReader(tmp_path / PASSWORDS_FILE_NAME)
    reader.check()

    for index in range(5):
        await writer.issue_password(f"plugin-{index}")
        assert f"plugin-{index}:" in reader.check()

    await writer.remove_password("plugin-2")
    assert "plugin-2:" not in reader.check()


async def test_a_password_whose_file_write_failed_is_not_kept(writer, tmp_path, monkeypatch):
    real_replace = policy_writer.replace_atomically

    def failing(directory, name, content, **options):
        raise OSError("No space left on device")

    monkeypatch.setattr(policy_writer, "replace_atomically", failing)
    with pytest.raises(EgressPolicyError, match="No space left on device"):
        await writer.issue_password("weather")
    monkeypatch.setattr(policy_writer, "replace_atomically", real_replace)

    assert not writer.forget_password("weather")
    password = await writer.issue_password("weather")
    assert bcrypt.checkpw(password.encode(), password_lines(tmp_path)["weather"].encode())


async def test_a_failed_rename_leaves_no_temporary_file(writer, tmp_path, monkeypatch):
    def refusing_rename(*arguments, **options):
        raise OSError("Read-only file system")

    monkeypatch.setattr(policy_writer.os, "replace", refusing_rename)
    with pytest.raises(EgressPolicyError):
        await writer.write_hosts({"weather": ["example.com"]})
    monkeypatch.undo()

    assert sorted(path.name for path in tmp_path.iterdir()) == [HOSTS_FILE_NAME, PASSWORDS_FILE_NAME]
    assert json.loads((tmp_path / HOSTS_FILE_NAME).read_text()) == {}


async def test_removing_a_plugin_drops_its_password_and_hosts_and_again_changes_nothing(writer, tmp_path):
    await writer.write_hosts({"weather": ["example.com"], "notes": ["api.example.org"]})
    await writer.issue_password("weather")
    notes_password = await writer.issue_password("notes")

    await writer.remove_plugin("weather")
    hosts_inode = os.stat(tmp_path / HOSTS_FILE_NAME).st_ino
    passwords_inode = os.stat(tmp_path / PASSWORDS_FILE_NAME).st_ino
    await writer.remove_plugin("weather")

    assert json.loads((tmp_path / HOSTS_FILE_NAME).read_text()) == {"notes": ["api.example.org"]}
    assert list(password_lines(tmp_path)) == ["notes"]
    assert bcrypt.checkpw(notes_password.encode(), password_lines(tmp_path)["notes"].encode())
    assert os.stat(tmp_path / HOSTS_FILE_NAME).st_ino == hosts_inode
    assert os.stat(tmp_path / PASSWORDS_FILE_NAME).st_ino == passwords_inode


async def test_a_removal_never_writes_back_an_older_host_list(writer, tmp_path):
    await writer.write_hosts({"weather": ["example.com"], "notes": []})

    # The newer list is being written while the removal starts: the removal must not take the
    # list it replaces from before that write.
    await asyncio.gather(
        writer.write_hosts({"notes": [], "alpha": ["api.example.org"]}),
        writer.remove_plugin("weather"),
    )

    assert json.loads((tmp_path / HOSTS_FILE_NAME).read_text()) == {"alpha": ["api.example.org"], "notes": []}
