from conftest import load_tool, seed

tool = load_tool("s3_folder_delete_tool")


def test_delete_folder_removes_all_objects(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "x")
    seed(fake_client, "dir/sub/b.txt", "y")

    result = tool.main(folder_path="dir")

    assert "2 object(s) removed" in result
    assert "dir/a.txt" not in fake_client.objects
    assert "dir/sub/b.txt" not in fake_client.objects


def test_delete_missing_folder(patched_storage, fake_client):
    result = tool.main(folder_path="missing")

    assert "no such folder" in result.lower()


def test_delete_root_refused(patched_storage, fake_client):
    seed(fake_client, "a.txt", "x")

    result = tool.main(folder_path="")

    assert "refusing" in result.lower()
    assert "a.txt" in fake_client.objects
