"""``build_s3_manifest``: the system message telling the agent which storage paths it may use.

Pure function: one line per path with its allowed and denied operations, then a
legend explaining only the operations granted somewhere, worded per kind (file or
folder), then a closing line denying everything else.
"""

from __future__ import annotations

import pytest
from app.resources.s3_manifest import build_s3_manifest
from shared.models.agent_service import S3FileSpec

HEADER = "Files and folders you have access to:"
FOOTER = "You have no access to any other path in storage."
LEGEND = "What each permission means"


def _flags(**overrides: str) -> dict:
    return {"can_list": "unset", "can_view": "unset", "can_edit": "unset", "can_delete": "unset", **overrides}


def _manifest(*specs: tuple[str, dict]) -> str:
    attachment = build_s3_manifest(
        [S3FileSpec(id=index, path=path, metadata=metadata) for index, (path, metadata) in enumerate(specs, 1)]
    )
    assert (attachment.role, attachment.source) == ("system", "s3")
    return attachment.content


def _path_lines(content: str) -> list[str]:
    lines = content.splitlines()
    path_lines = []
    for line in lines[lines.index(HEADER) + 1 :]:
        if not line.startswith("- "):
            break
        path_lines.append(line)
    return path_lines


def test_no_paths_means_no_manifest():
    assert build_s3_manifest([]) is None


FILE = "reports/q1.pdf"


@pytest.mark.parametrize(
    ("path", "metadata", "expected_line"),
    [
        pytest.param(FILE, {"item_type": "file", "flags": _flags(can_view="allow")},
                     f"- {FILE} (file) — may: view — may not: list, edit, delete", id="one-allowed"),
        pytest.param(FILE, {"item_type": "file", "flags": _flags(can_delete="allow", can_list="allow", can_edit="allow", can_view="allow")},
                     f"- {FILE} (file) — may: list, view, edit, delete", id="all-allowed-in-fixed-order"),
        pytest.param(FILE, {"item_type": "file", "flags": _flags(can_list="allow", can_view="deny")},
                     f"- {FILE} (file) — may: list — may not: view, edit, delete", id="deny-and-unset-are-not-allowed"),
        pytest.param(FILE, {"item_type": "file", "flags": _flags()},
                     f"- {FILE} (file) — may not: list, view, edit, delete", id="nothing-allowed"),
        pytest.param("reports/archive/", {"item_type": "folder", "flags": _flags(can_list="allow")},
                     "- reports/archive/ (folder) — may: list — may not: view, edit, delete", id="folder"),
        pytest.param(FILE, {"item_type": "file", "size": 24_576, "flags": _flags(can_view="allow")},
                     f"- {FILE} (file, 24 KB) — may: view — may not: list, edit, delete", id="file-size"),
        # Metadata comes from storage; anything missing or malformed degrades, never raises.
        pytest.param("inbox/notes.txt", {}, "- inbox/notes.txt", id="no-metadata"),
        pytest.param("inbox/notes.txt", {"item_type": None, "size": None, "flags": _flags(can_view="allow")},
                     "- inbox/notes.txt — may: view — may not: list, edit, delete", id="null-type-and-size"),
        pytest.param(FILE, {"item_type": "file", "flags": "not-a-dict"}, f"- {FILE} (file)", id="malformed-flags"),
        *[
            pytest.param(FILE, {"item_type": "file", "size": size, "flags": _flags()},
                         f"- {FILE} (file, {shown}) — may not: list, view, edit, delete", id=f"size-{shown}")
            for size, shown in [
                (0, "0 B"), (1, "1 B"), (1023, "1023 B"), (1024, "1 KB"), (1536, "1.5 KB"),
                (1024 * 1024 - 1, "1024 KB"), (1024 * 1024, "1 MB"), (int(1.5 * 1024 * 1024), "1.5 MB"),
            ]
        ],
    ],
)
def test_each_path_line_states_exactly_what_is_allowed_and_denied(path, metadata, expected_line):
    assert _path_lines(_manifest((path, metadata))) == [expected_line]


def test_paths_are_listed_in_order_between_header_and_footer():
    content = _manifest(
        (FILE, {"item_type": "file", "size": 24_576, "flags": _flags(can_view="allow", can_edit="allow")}),
        ("reports/archive/", {"item_type": "folder", "flags": _flags(can_list="allow")}),
        ("inbox/notes.txt", {"flags": _flags(can_view="allow")}),
    )

    assert content.startswith(HEADER)
    assert _path_lines(content) == [
        f"- {FILE} (file, 24 KB) — may: view, edit — may not: list, delete",
        "- reports/archive/ (folder) — may: list — may not: view, edit, delete",
        "- inbox/notes.txt — may: view — may not: list, edit, delete",
    ]
    assert content.index(LEGEND) < content.index(FOOTER)
    assert content.endswith(FOOTER)


FOLDER_EDIT = "create new entries inside it"
FILE_EDIT = "modify or overwrite the contents"


@pytest.mark.parametrize(
    ("specs", "present", "absent"),
    [
        pytest.param(
            [("test/", {"item_type": "folder", "flags": _flags(can_edit="allow")})],
            ["Folders:", FOLDER_EDIT], ["Files:", FILE_EDIT], id="folder-edit",
        ),
        pytest.param(
            [(FILE, {"item_type": "file", "flags": _flags(can_edit="allow")})],
            ["Files:", FILE_EDIT], ["Folders:", FOLDER_EDIT], id="file-edit",
        ),
        pytest.param(
            # Without an item type, a trailing slash decides folder vs file.
            [("test/", {"flags": _flags(can_edit="allow")})], [FOLDER_EDIT], [FILE_EDIT], id="untyped-folder",
        ),
        pytest.param([(FILE, {"flags": _flags(can_edit="allow")})], [FILE_EDIT], [FOLDER_EDIT], id="untyped-file"),
        pytest.param(
            [(FILE, {"item_type": "file", "flags": _flags(can_list="allow")})],
            ["list: see this file in directory listings"], ["entries inside this folder"], id="file-list",
        ),
        pytest.param(
            # Each kind's section explains only the operations granted on that kind.
            [
                ("test/", {"item_type": "folder", "flags": _flags(can_list="allow", can_edit="allow")}),
                (FILE, {"item_type": "file", "flags": _flags(can_view="allow", can_delete="allow")}),
            ],
            ["Folders:", "Files:", FOLDER_EDIT, "read the contents", "remove it permanently"],
            [FILE_EDIT, "read the contents of entries inside it", "remove the folder itself once empty"],
            id="mixed-kinds",
        ),
        pytest.param(
            [
                (FILE, {"item_type": "file", "flags": _flags(can_view="allow")}),
                ("inbox/notes.txt", {"item_type": "file", "flags": _flags(can_edit="allow")}),
            ],
            ["- view: read the contents", "- edit: modify or overwrite the contents"],
            ["- list:", "- delete:"], id="only-granted-operations",
        ),
        pytest.param(
            [(FILE, {"item_type": "file", "flags": _flags()})], [], [LEGEND], id="nothing-granted-no-legend",
        ),
    ],
)
def test_legend_explains_only_granted_operations_in_the_wording_of_their_kind(specs, present, absent):
    content = _manifest(*specs)

    assert [fragment for fragment in present if fragment not in content] == []
    assert [fragment for fragment in absent if fragment in content] == []


def test_legend_lists_operations_in_the_order_list_view_edit_delete():
    content = _manifest(
        (FILE, {"item_type": "file", "flags": _flags(can_delete="allow", can_list="allow", can_edit="allow", can_view="allow")})
    )

    positions = [content.index(f"- {operation}:") for operation in ("list", "view", "edit", "delete")]
    assert positions == sorted(positions)
