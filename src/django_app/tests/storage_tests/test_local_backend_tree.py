import pytest


pytestmark = pytest.mark.django_db


class TestLocalBackendTree:
    def test_tree_returns_empty_for_empty_folder(self, local_backend):
        local_backend.mkdir("empty")
        root, truncated = local_backend.list_tree("empty")
        assert root.type == "folder"
        assert root.children == []
        assert truncated is False

    def test_tree_nests_files_and_folders(self, local_backend, tmp_path):
        (tmp_path / "reports").mkdir()
        (tmp_path / "reports" / "q1.pdf").write_bytes(b"x" * 10)
        (tmp_path / "reports" / "2025").mkdir()
        (tmp_path / "reports" / "2025" / "summary.txt").write_bytes(b"s")

        root, _ = local_backend.list_tree("reports")
        names = sorted(c.name for c in root.children)
        assert names == ["2025", "q1.pdf"]
        year = next(c for c in root.children if c.name == "2025")
        assert year.children[0].name == "summary.txt"

    def test_tree_respects_max_depth(self, local_backend, tmp_path):
        (tmp_path / "a" / "b" / "c" / "d").mkdir(parents=True)
        (tmp_path / "a" / "b" / "c" / "d" / "x.txt").write_bytes(b"x")

        root, _ = local_backend.list_tree("a", max_depth=2)
        depth = 0
        cur = root
        while cur.children:
            cur = cur.children[0]
            depth += 1
        assert depth == 2

    def test_tree_sets_truncated_when_over_max_entries(self, local_backend, tmp_path):
        for i in range(10):
            (tmp_path / f"f{i}.txt").write_bytes(b"")
        root, truncated = local_backend.list_tree("", max_entries=3)
        assert truncated is True
        assert len(root.children) <= 3
