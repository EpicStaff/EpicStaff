"""The library refuses an operation before storage does when the run's FILES permissions
(`STORAGE_ALLOWED_ACTIONS`) don't grant its action, except inside the run's own folders
(`STORAGE_OWN_PATHS`). With the variables absent, behavior is path-allowlist only."""

from itertools import combinations

import pytest

from epicstaff_storage import StoragePermissionError

from conftest import allow_paths, restrict_actions

ALL_ACTIONS = ("read", "write", "delete")

# (operation, call, actions it needs outside the run's own folders)
OPERATIONS = [
    ("read", lambda s: s.read("docs/a.txt"), {"read"}),
    ("read_bytes", lambda s: s.read_bytes("docs/a.txt"), {"read"}),
    ("read_lines", lambda s: s.read_lines("docs/a.txt", 1), {"read"}),
    ("count_lines", lambda s: s.count_lines("docs/a.txt"), {"read"}),
    ("list", lambda s: s.list("docs/"), {"read"}),
    ("walk", lambda s: s.walk("docs/"), {"read"}),
    ("exists", lambda s: s.exists("docs/a.txt"), {"read"}),
    ("info", lambda s: s.info("docs/a.txt"), {"read"}),
    ("as_local", lambda s: s.as_local("docs/a.txt").__enter__(), {"read"}),
    ("copy", lambda s: s.copy("docs/a.txt", "docs/copy.txt"), {"read", "write"}),
    ("write", lambda s: s.write("docs/new.txt", "x"), {"write"}),
    ("write_bytes", lambda s: s.write_bytes("docs/new.bin", b"x"), {"write"}),
    ("mkdir", lambda s: s.mkdir("docs/newdir"), {"write"}),
    ("append_text", lambda s: s.append_text("docs/a.txt", "more"), {"read", "write"}),
    ("edit_line", lambda s: s.edit_line("docs/a.txt", 1, "hello", "bye"), {"read", "write"}),
    ("insert_lines", lambda s: s.insert_lines("docs/a.txt", 1, "top"), {"read", "write"}),
    ("delete", lambda s: s.delete("docs/a.txt"), {"delete"}),
    ("delete_folder", lambda s: s.delete_folder("docs/sub/"), {"delete"}),
    ("move", lambda s: s.move("docs/a.txt", "docs/moved.txt"), {"read", "write", "delete"}),
]

GRANTED_SETS = [
    set(combo) for size in range(len(ALL_ACTIONS) + 1) for combo in combinations(ALL_ACTIONS, size)
]


def seed(fake_client) -> None:
    fake_client.put_object(Bucket="b", Key="docs/a.txt", Body=b"hello")
    fake_client.put_object(Bucket="b", Key="docs/sub/x.txt", Body=b"x")


def snapshot(fake_client) -> dict[str, bytes]:
    return {key: obj["Body"] for key, obj in fake_client.objects.items()}


@pytest.mark.parametrize("granted", GRANTED_SETS, ids=lambda granted: "+".join(sorted(granted)) or "none")
@pytest.mark.parametrize(("name", "call", "required"), OPERATIONS, ids=[op[0] for op in OPERATIONS])
def test_operation_runs_only_when_every_action_it_needs_is_granted(
    monkeypatch, storage, fake_client, name, call, required, granted
):
    seed(fake_client)
    restrict_actions(monkeypatch, sorted(granted), own_paths=[])
    before = snapshot(fake_client)

    if required <= granted:
        call(storage)
    else:
        with pytest.raises(StoragePermissionError):
            call(storage)
        assert snapshot(fake_client) == before


def test_denied_message_names_operation_path_and_missing_permission(
    monkeypatch, storage, fake_client
):
    seed(fake_client)
    restrict_actions(monkeypatch, ["read", "write"], own_paths=[])

    with pytest.raises(StoragePermissionError) as exc_info:
        storage.delete("docs/a.txt")

    message = str(exc_info.value)
    assert "delete" in message
    assert "docs/a.txt" in message
    assert "deleting files needs the Files: Delete permission" in message


def test_write_denied_message_names_create_and_update(monkeypatch, storage):
    restrict_actions(monkeypatch, ["read"], own_paths=[])

    with pytest.raises(StoragePermissionError, match="Files: Create and Files: Update"):
        storage.write("docs/new.txt", "x")


@pytest.mark.parametrize(("name", "call", "required"), OPERATIONS, ids=[op[0] for op in OPERATIONS])
def test_own_path_allows_every_operation_even_with_no_actions(
    monkeypatch, storage, fake_client, name, call, required
):
    # The same calls as the table, but on a folder the run owns.
    seed_prefix = "docs/"
    own_prefix = "sessions/7/"
    for key in list(fake_client.objects):
        fake_client.objects[key.replace(seed_prefix, own_prefix, 1)] = fake_client.objects.pop(key)
    fake_client.put_object(Bucket="b", Key="sessions/7/a.txt", Body=b"hello")
    fake_client.put_object(Bucket="b", Key="sessions/7/sub/x.txt", Body=b"x")
    restrict_actions(monkeypatch, [], own_paths=["sessions/7/"])

    class OwnFolderStorage:
        def __getattr__(self, attribute):
            method = getattr(storage, attribute)

            def call_on_own_folder(*args, **kwargs):
                rewritten = [
                    arg.replace("docs/", own_prefix, 1) if isinstance(arg, str) else arg
                    for arg in args
                ]
                return method(*rewritten, **kwargs)

            return call_on_own_folder

    call(OwnFolderStorage())


def test_path_outside_own_folders_still_needs_the_action(monkeypatch, storage, fake_client):
    fake_client.put_object(Bucket="b", Key="docs/a.txt", Body=b"hello")
    restrict_actions(monkeypatch, ["read"], own_paths=["sessions/7/"])

    storage.write("sessions/7/out.txt", "x")
    with pytest.raises(StoragePermissionError):
        storage.write("docs/out.txt", "x")


def test_own_folder_is_usable_when_the_allowed_files_do_not_list_it(monkeypatch, storage):
    # A sub-flow's node: its allowed files hold only the flow's files, not the session folder.
    allow_paths(monkeypatch, ["docs/"])
    restrict_actions(monkeypatch, [], own_paths=["sessions/8/"])

    storage.write("sessions/8/out.txt", "x")

    assert storage.read("sessions/8/out.txt") == "x"
    assert [item["name"] for item in storage.list("sessions/8/")] == ["out.txt"]


def test_own_folder_does_not_open_other_paths_outside_the_allowed_files(monkeypatch, storage):
    allow_paths(monkeypatch, ["docs/"])
    restrict_actions(monkeypatch, ["read", "write", "delete"], own_paths=["sessions/8/"])

    for path in ("sessions/9/out.txt", "sessions/8-other/out.txt", "elsewhere/out.txt"):
        with pytest.raises(StoragePermissionError, match="not within this flow's allowed files"):
            storage.write(path, "x")


def test_own_folder_never_opens_the_recycle_bin(monkeypatch, storage):
    allow_paths(monkeypatch, ["docs/"])
    restrict_actions(monkeypatch, [], own_paths=[".recycle-bin/"])

    with pytest.raises(StoragePermissionError, match="holds deleted files"):
        storage.write(".recycle-bin/out.txt", "x")


def test_own_folder_still_refuses_executable_files(monkeypatch, storage):
    allow_paths(monkeypatch, ["docs/"])
    restrict_actions(monkeypatch, [], own_paths=["sessions/8/"])

    with pytest.raises(StoragePermissionError, match="executable"):
        storage.write("sessions/8/tool.exe", "x")


def test_without_the_env_vars_every_operation_keeps_its_path_only_behavior(
    monkeypatch, storage, fake_client
):
    seed(fake_client)
    allow_paths(monkeypatch, ["docs/"])

    for _name, call, _required in OPERATIONS:
        seed(fake_client)
        call(storage)

    with pytest.raises(StoragePermissionError):
        storage.write("elsewhere/f.txt", "x")


def test_move_without_delete_on_source_is_refused_before_anything_is_copied(
    monkeypatch, storage, fake_client
):
    seed(fake_client)
    restrict_actions(monkeypatch, ["read", "write"], own_paths=[])
    copy_calls = []
    real_copy = fake_client.copy_object
    monkeypatch.setattr(
        fake_client,
        "copy_object",
        lambda **kwargs: copy_calls.append(kwargs) or real_copy(**kwargs),
    )

    with pytest.raises(StoragePermissionError, match="Files: Delete"):
        storage.move("docs/a.txt", "docs/moved.txt")

    assert copy_calls == []
    assert "docs/moved.txt" not in fake_client.objects
    assert "docs/a.txt" in fake_client.objects


def test_move_without_write_on_destination_is_refused_before_anything_is_copied(
    monkeypatch, storage, fake_client
):
    seed(fake_client)
    restrict_actions(monkeypatch, ["read", "delete"], own_paths=[])
    copy_calls = []
    real_copy = fake_client.copy_object
    monkeypatch.setattr(
        fake_client,
        "copy_object",
        lambda **kwargs: copy_calls.append(kwargs) or real_copy(**kwargs),
    )

    with pytest.raises(StoragePermissionError, match="Files: Create and Files: Update"):
        storage.move("docs/a.txt", "docs/moved.txt")

    assert copy_calls == []
    assert "docs/a.txt" in fake_client.objects


def test_move_from_a_shared_path_into_an_own_folder_still_needs_delete(
    monkeypatch, storage, fake_client
):
    seed(fake_client)
    restrict_actions(monkeypatch, ["read"], own_paths=["sessions/7/"])

    with pytest.raises(StoragePermissionError, match="Files: Delete"):
        storage.move("docs/a.txt", "sessions/7/a.txt")

    assert "sessions/7/a.txt" not in fake_client.objects


def test_an_operation_without_a_permission_mapping_is_refused_when_actions_are_narrowed(monkeypatch):
    from epicstaff_storage import check_storage_permission

    allow_paths(monkeypatch, ["docs/"])
    restrict_actions(monkeypatch, list(ALL_ACTIONS), own_paths=["docs/"])

    with pytest.raises(StoragePermissionError, match="no permission mapping"):
        check_storage_permission("not_a_real_operation", "docs/a.txt")


def test_every_operation_checked_in_the_library_has_a_permission_mapping():
    """Adding a `check_storage_permission("...")` call without a `_REQUIRED_ACTIONS` entry
    would make that operation ignore the run's narrowed actions."""
    import ast
    import inspect
    import sys

    storage_module = sys.modules["epicstaff_storage.storage"]

    tree = ast.parse(inspect.getsource(storage_module))
    checked = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "check_storage_permission"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }

    assert checked, "no check_storage_permission calls found; the scan is broken"
    assert checked <= set(storage_module._REQUIRED_ACTIONS)
