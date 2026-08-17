"""
Unit tests for ``build_s3_manifest``.

Pure function, no I/O — covers flag rendering, malformed/missing metadata,
and human-readable size formatting.
"""

from __future__ import annotations

from app.resources.s3_manifest import build_s3_manifest
from shared.models.agent_service import S3FileSpec


def _spec(
    file_id: int = 1,
    path: str = "reports/q1.pdf",
    metadata: dict | None = None,
) -> S3FileSpec:
    return S3FileSpec(id=file_id, path=path, metadata=metadata or {})


def _flags(**overrides: str) -> dict:
    base = {
        "can_list": "unset",
        "can_view": "unset",
        "can_edit": "unset",
        "can_delete": "unset",
    }
    base.update(overrides)
    return base


def test_empty_spec_list_returns_none():
    assert build_s3_manifest([]) is None


def test_single_allowed_flag_renders_may_fragment():
    spec = _spec(
        path="inbox/notes.txt",
        metadata={"item_type": "file", "flags": _flags(can_view="allow")},
    )

    attachment = build_s3_manifest([spec])

    assert attachment is not None
    assert attachment.role == "system"
    assert attachment.source == "s3"
    assert "- inbox/notes.txt" in attachment.content
    assert "may: view" in attachment.content


def test_flags_rendered_in_fixed_order_list_view_edit_delete():
    spec = _spec(
        metadata={
            "item_type": "file",
            "flags": _flags(
                can_delete="allow", can_list="allow", can_edit="allow", can_view="allow"
            ),
        }
    )

    attachment = build_s3_manifest([spec])

    assert "may: list, view, edit, delete" in attachment.content


def test_unset_and_deny_flags_are_omitted():
    spec = _spec(
        metadata={
            "item_type": "file",
            "flags": _flags(can_list="allow", can_view="deny", can_edit="unset"),
        }
    )

    attachment = build_s3_manifest([spec])

    line = [ln for ln in attachment.content.splitlines() if ln.startswith("- ")][0]
    may_segment = line.split("may:")[1].split("may not:")[0]
    assert "list" in may_segment
    assert "view" not in may_segment
    assert "edit" not in may_segment


def test_all_flags_non_allow_omits_may_fragment():
    spec = _spec(metadata={"item_type": "file", "flags": _flags()})

    attachment = build_s3_manifest([spec])

    line = [ln for ln in attachment.content.splitlines() if ln.startswith("- ")][0]
    assert "may:" not in line
    assert "may not: list, view, edit, delete" in line


def test_folder_item_type_renders_without_size():
    spec = _spec(
        path="reports/archive/",
        metadata={"item_type": "folder", "flags": _flags(can_list="allow")},
    )

    attachment = build_s3_manifest([spec])

    line = [ln for ln in attachment.content.splitlines() if ln.startswith("- ")][0]
    assert line == (
        "- reports/archive/ (folder) — may: list — may not: view, edit, delete"
    )


def test_file_with_missing_size_omits_parenthetical_size():
    spec = _spec(
        path="reports/q1.pdf",
        metadata={"item_type": "file", "flags": _flags(can_view="allow")},
    )

    attachment = build_s3_manifest([spec])

    line = [ln for ln in attachment.content.splitlines() if ln.startswith("- ")][0]
    assert line == ("- reports/q1.pdf (file) — may: view — may not: list, edit, delete")


def test_file_with_size_renders_parenthetical():
    spec = _spec(
        path="reports/q1.pdf",
        metadata={
            "item_type": "file",
            "size": 24_576,
            "flags": _flags(can_view="allow"),
        },
    )

    attachment = build_s3_manifest([spec])

    line = [ln for ln in attachment.content.splitlines() if ln.startswith("- ")][0]
    assert line == (
        "- reports/q1.pdf (file, 24 KB) — may: view — may not: list, edit, delete"
    )


def test_spec_with_empty_metadata_degrades_to_bare_path_line():
    spec = _spec(path="inbox/notes.txt", metadata={})

    attachment = build_s3_manifest([spec])

    line = [ln for ln in attachment.content.splitlines() if ln.startswith("- ")][0]
    assert line == "- inbox/notes.txt"


def test_spec_with_none_item_type_and_size_degrades_gracefully():
    spec = _spec(
        path="inbox/notes.txt",
        metadata={"item_type": None, "size": None, "flags": _flags(can_view="allow")},
    )

    attachment = build_s3_manifest([spec])

    line = [ln for ln in attachment.content.splitlines() if ln.startswith("- ")][0]
    assert line == "- inbox/notes.txt — may: view — may not: list, edit, delete"


def test_malformed_flags_value_does_not_raise():
    spec = _spec(metadata={"item_type": "file", "flags": "not-a-dict"})

    attachment = build_s3_manifest([spec])

    line = [ln for ln in attachment.content.splitlines() if ln.startswith("- ")][0]
    assert "may:" not in line
    assert "may not:" not in line


def test_content_ends_with_no_other_access_footer():
    spec = _spec(metadata={"item_type": "file", "flags": _flags(can_view="allow")})

    attachment = build_s3_manifest([spec])

    assert attachment.content.startswith("Files and folders you have access to:")
    assert attachment.content.endswith(
        "You have no access to any other path in storage."
    )


def test_folder_edit_renders_create_wording_not_file_wording():
    spec = _spec(
        path="test/",
        metadata={"item_type": "folder", "flags": _flags(can_edit="allow")},
    )

    attachment = build_s3_manifest([spec])

    assert "create new entries inside it" in attachment.content
    assert "modify or overwrite the contents" not in attachment.content


def test_file_edit_still_renders_modify_or_overwrite_wording():
    spec = _spec(
        path="reports/q1.pdf",
        metadata={"item_type": "file", "flags": _flags(can_edit="allow")},
    )

    attachment = build_s3_manifest([spec])

    assert "modify or overwrite the contents" in attachment.content
    assert "create new entries inside it" not in attachment.content


def test_mixed_pool_renders_both_sections_with_only_their_own_verbs():
    folder_spec = _spec(
        file_id=1,
        path="test/",
        metadata={
            "item_type": "folder",
            "flags": _flags(can_list="allow", can_edit="allow"),
        },
    )
    file_spec = _spec(
        file_id=2,
        path="reports/q1.pdf",
        metadata={
            "item_type": "file",
            "flags": _flags(can_view="allow", can_delete="allow"),
        },
    )

    attachment = build_s3_manifest([folder_spec, file_spec])
    content = attachment.content

    assert "Folders:" in content
    assert "Files:" in content
    assert "create new entries inside it" in content
    assert "read the contents" in content
    assert "remove it permanently" in content
    assert "modify or overwrite the contents" not in content
    assert "read the contents of entries inside it" not in content
    assert "remove the folder itself once empty" not in content


def test_folder_only_pool_omits_files_section():
    spec = _spec(
        path="test/",
        metadata={"item_type": "folder", "flags": _flags(can_list="allow")},
    )

    attachment = build_s3_manifest([spec])

    assert "Folders:" in attachment.content
    assert "Files:" not in attachment.content


def test_file_only_pool_omits_folders_section():
    spec = _spec(
        path="reports/q1.pdf",
        metadata={"item_type": "file", "flags": _flags(can_view="allow")},
    )

    attachment = build_s3_manifest([spec])

    assert "Files:" in attachment.content
    assert "Folders:" not in attachment.content


def test_missing_item_type_falls_back_to_trailing_slash_for_folder_classification():
    spec = _spec(
        path="test/",
        metadata={"flags": _flags(can_edit="allow")},
    )

    attachment = build_s3_manifest([spec])

    assert "create new entries inside it" in attachment.content
    assert "modify or overwrite the contents" not in attachment.content


def test_missing_item_type_without_trailing_slash_classified_as_file():
    spec = _spec(
        path="reports/q1.pdf",
        metadata={"flags": _flags(can_edit="allow")},
    )

    attachment = build_s3_manifest([spec])

    assert "modify or overwrite the contents" in attachment.content
    assert "create new entries inside it" not in attachment.content


def test_file_only_pool_list_renders_file_wording_not_folder_wording():
    spec = _spec(
        path="reports/q1.pdf",
        metadata={"item_type": "file", "flags": _flags(can_list="allow")},
    )

    attachment = build_s3_manifest([spec])

    assert "list: see this file in directory listings" in attachment.content
    assert "entries inside this folder" not in attachment.content


def test_size_formatting_boundaries():
    cases = [
        (0, "0 B"),
        (1, "1 B"),
        (1023, "1023 B"),
        (1024, "1 KB"),
        (1536, "1.5 KB"),
        (1024 * 1024 - 1, "1024 KB"),
        (1024 * 1024, "1 MB"),
        (int(1.5 * 1024 * 1024), "1.5 MB"),
    ]

    for size, expected in cases:
        spec = _spec(metadata={"item_type": "file", "size": size, "flags": _flags()})
        attachment = build_s3_manifest([spec])
        line = [ln for ln in attachment.content.splitlines() if ln.startswith("- ")][0]
        assert expected in line, f"size={size} expected {expected!r} in {line!r}"


def test_all_flags_allowed_omits_may_not_fragment():
    spec = _spec(
        path="test/Notes.txt",
        metadata={
            "item_type": "file",
            "flags": _flags(
                can_list="allow", can_view="allow", can_edit="allow", can_delete="allow"
            ),
        },
    )

    attachment = build_s3_manifest([spec])

    line = [ln for ln in attachment.content.splitlines() if ln.startswith("- ")][0]
    assert "may: list, view, edit, delete" in line
    assert "may not:" not in line


def test_no_flags_allowed_lists_path_with_may_not_only():
    spec = _spec(
        path="test/Locked.txt",
        metadata={"item_type": "file", "flags": _flags()},
    )

    attachment = build_s3_manifest([spec])

    line = [ln for ln in attachment.content.splitlines() if ln.startswith("- ")][0]
    assert "- test/Locked.txt" in line
    assert "may:" not in line
    assert "may not: list, view, edit, delete" in line


def test_mixed_pool_denial_wording_matches_actual_permissions_not_inverted():
    notes_spec = _spec(
        file_id=1,
        path="test/Notes.txt",
        metadata={
            "item_type": "file",
            "flags": _flags(
                can_list="allow", can_view="allow", can_edit="allow", can_delete="allow"
            ),
        },
    )
    plan_spec = _spec(
        file_id=2,
        path="test/Plan.txt",
        metadata={
            "item_type": "file",
            "flags": _flags(can_list="allow", can_view="allow", can_edit="allow"),
        },
    )
    faq_spec = _spec(
        file_id=3,
        path="test/Solar System FAQ.txt",
        metadata={
            "item_type": "file",
            "flags": _flags(can_list="allow", can_view="allow", can_edit="allow"),
        },
    )

    attachment = build_s3_manifest([notes_spec, plan_spec, faq_spec])
    all_lines = attachment.content.splitlines()
    header_index = all_lines.index("Files and folders you have access to:")
    lines = []

    for line in all_lines[header_index + 1 :]:
        if not line.startswith("- "):
            break
        lines.append(line)

    notes_line, plan_line, faq_line = lines

    assert "may: list, view, edit, delete" in notes_line
    assert "may not:" not in notes_line

    assert "delete" in plan_line.split("may not:")[1]
    assert "delete" not in plan_line.split("may:")[1].split("may not:")[0]

    assert "delete" in faq_line.split("may not:")[1]
    assert "delete" not in faq_line.split("may:")[1].split("may not:")[0]


def test_legend_lists_only_ops_present_across_specs():
    spec_a = _spec(
        file_id=1,
        path="reports/q1.pdf",
        metadata={"item_type": "file", "flags": _flags(can_view="allow")},
    )
    spec_b = _spec(
        file_id=2,
        path="inbox/notes.txt",
        metadata={"item_type": "file", "flags": _flags(can_edit="allow")},
    )

    attachment = build_s3_manifest([spec_a, spec_b])

    assert "- list:" not in attachment.content
    assert "- view: read the contents" in attachment.content
    assert "- edit: modify or overwrite the contents" in attachment.content
    assert "- delete:" not in attachment.content


def test_legend_line_order_is_list_view_edit_delete():
    spec = _spec(
        metadata={
            "item_type": "file",
            "flags": _flags(
                can_delete="allow", can_list="allow", can_edit="allow", can_view="allow"
            ),
        }
    )

    attachment = build_s3_manifest([spec])

    content = attachment.content
    indices = [
        content.index("- list:"),
        content.index("- view:"),
        content.index("- edit:"),
        content.index("- delete:"),
    ]
    assert indices == sorted(indices)


def test_legend_contains_non_implication_sentence():
    spec = _spec(metadata={"item_type": "file", "flags": _flags(can_view="allow")})

    attachment = build_s3_manifest([spec])

    assert (
        "each is granted independently — having one does NOT imply any other"
        in attachment.content
    )


def test_misleading_delete_example_sentence_is_removed():
    spec = _spec(metadata={"item_type": "file", "flags": _flags(can_view="allow")})

    attachment = build_s3_manifest([spec])

    assert "does not let you delete it" not in attachment.content


def test_legend_contains_act_dont_prejudge_closing_paragraph():
    spec = _spec(metadata={"item_type": "file", "flags": _flags(can_view="allow")})

    attachment = build_s3_manifest([spec])

    assert (
        "Each path above lists exactly what you may and may not do with it. "
        "Treat that per-path list as authoritative — do not generalise a "
        "restriction on one path to another path, or from one operation to "
        "another. If an operation is listed as allowed for a path, perform "
        "it with your tools when asked; do not refuse it or ask for "
        "confirmation first."
    ) in attachment.content


def test_no_legend_when_no_path_has_any_allowed_op():
    spec = _spec(metadata={"item_type": "file", "flags": _flags()})

    attachment = build_s3_manifest([spec])

    assert "What each permission means" not in attachment.content
    assert attachment.content.endswith(
        "You have no access to any other path in storage."
    )


def test_legend_appears_before_closing_footer_line():
    spec = _spec(metadata={"item_type": "file", "flags": _flags(can_view="allow")})

    attachment = build_s3_manifest([spec])

    legend_index = attachment.content.index("What each permission means")
    footer_index = attachment.content.index(
        "You have no access to any other path in storage."
    )
    assert legend_index < footer_index


def test_multiple_specs_render_multiple_lines():
    spec_a = _spec(
        file_id=1,
        path="reports/q1.pdf",
        metadata={
            "item_type": "file",
            "size": 24_576,
            "flags": _flags(can_view="allow", can_edit="allow"),
        },
    )
    spec_b = _spec(
        file_id=2,
        path="reports/archive/",
        metadata={"item_type": "folder", "flags": _flags(can_list="allow")},
    )
    spec_c = _spec(
        file_id=3, path="inbox/notes.txt", metadata={"flags": _flags(can_view="allow")}
    )

    attachment = build_s3_manifest([spec_a, spec_b, spec_c])

    all_lines = attachment.content.splitlines()
    header_index = all_lines.index("Files and folders you have access to:")
    lines = []

    for line in all_lines[header_index + 1 :]:
        if not line.startswith("- "):
            break
        lines.append(line)

    assert lines == [
        "- reports/q1.pdf (file, 24 KB) — may: view, edit — may not: list, delete",
        "- reports/archive/ (folder) — may: list — may not: view, edit, delete",
        "- inbox/notes.txt — may: view — may not: list, edit, delete",
    ]
