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
    assert "may: list" in line
    assert "view" not in line.split("may:")[1]
    assert "edit" not in line.split("may:")[1]


def test_all_flags_non_allow_omits_may_fragment():
    spec = _spec(metadata={"item_type": "file", "flags": _flags()})

    attachment = build_s3_manifest([spec])

    line = [ln for ln in attachment.content.splitlines() if ln.startswith("- ")][0]
    assert "may:" not in line


def test_folder_item_type_renders_without_size():
    spec = _spec(
        path="reports/archive/",
        metadata={"item_type": "folder", "flags": _flags(can_list="allow")},
    )

    attachment = build_s3_manifest([spec])

    line = [ln for ln in attachment.content.splitlines() if ln.startswith("- ")][0]
    assert line == "- reports/archive/ (folder) — may: list"


def test_file_with_missing_size_omits_parenthetical_size():
    spec = _spec(
        path="reports/q1.pdf",
        metadata={"item_type": "file", "flags": _flags(can_view="allow")},
    )

    attachment = build_s3_manifest([spec])

    line = [ln for ln in attachment.content.splitlines() if ln.startswith("- ")][0]
    assert line == "- reports/q1.pdf (file) — may: view"


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
    assert line == "- reports/q1.pdf (file, 24 KB) — may: view"


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
    assert line == "- inbox/notes.txt — may: view"


def test_malformed_flags_value_does_not_raise():
    spec = _spec(metadata={"item_type": "file", "flags": "not-a-dict"})

    attachment = build_s3_manifest([spec])

    line = [ln for ln in attachment.content.splitlines() if ln.startswith("- ")][0]
    assert "may:" not in line


def test_content_ends_with_no_other_access_footer():
    spec = _spec(metadata={"item_type": "file", "flags": _flags(can_view="allow")})

    attachment = build_s3_manifest([spec])

    assert attachment.content.startswith("Files and folders you have access to:")
    assert attachment.content.endswith(
        "You have no access to any other path in storage."
    )


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


def test_legend_contains_non_implication_and_delete_clarification_sentences():
    spec = _spec(metadata={"item_type": "file", "flags": _flags(can_view="allow")})

    attachment = build_s3_manifest([spec])

    assert (
        "each is granted independently — having one does NOT imply any other"
        in attachment.content
    )
    assert "being able to edit a file does not let you delete it" in attachment.content


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


def test_no_scratch_path_output_unchanged_from_before():
    spec = _spec(metadata={"item_type": "file", "flags": _flags(can_view="allow")})

    attachment = build_s3_manifest([spec])
    attachment_with_explicit_none = build_s3_manifest([spec], scratch_path=None)

    assert attachment.content == attachment_with_explicit_none.content


def test_scratch_path_only_manifest_is_not_none():
    attachment = build_s3_manifest([], scratch_path="sessions/42/")

    assert attachment is not None


def test_scratch_path_line_rendered_after_granted_paths_before_legend():
    spec = _spec(
        path="reports/q1.pdf",
        metadata={"item_type": "file", "flags": _flags(can_view="allow")},
    )

    attachment = build_s3_manifest([spec], scratch_path="sessions/42/")

    content = attachment.content
    scratch_line = (
        "You may create and manage your own files under: sessions/42/ "
        "— you have full access there (list, view, edit, delete)."
    )
    assert scratch_line in content

    spec_line_index = content.index("- reports/q1.pdf")
    scratch_line_index = content.index(scratch_line)
    legend_index = content.index("What each permission means")
    assert spec_line_index < scratch_line_index < legend_index


def test_scratch_only_manifest_explains_all_four_ops():
    attachment = build_s3_manifest([], scratch_path="sessions/42/")

    content = attachment.content
    assert "- list:" in content
    assert "- view:" in content
    assert "- edit:" in content
    assert "- delete:" in content


def test_scratch_only_manifest_ends_with_no_other_access_footer():
    attachment = build_s3_manifest([], scratch_path="sessions/42/")

    assert attachment.content.endswith(
        "You have no access to any other path in storage."
    )


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
        "- reports/q1.pdf (file, 24 KB) — may: view, edit",
        "- reports/archive/ (folder) — may: list",
        "- inbox/notes.txt — may: view",
    ]
