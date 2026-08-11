from conftest import load_tool, seed

tool = load_tool("s3_file_delete_tool")


def test_delete_file(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello")

    result = tool.main(file_path="a.txt")

    assert "Deleted" in result
    assert "a.txt" not in fake_client.objects


def test_delete_missing_file(patched_storage, fake_client):
    result = tool.main(file_path="missing.txt")

    assert "not found" in result.lower()


def test_delete_folder_rejected(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "hello")

    result = tool.main(file_path="dir")

    assert "s3_folder_delete_tool" in result
    assert "dir/a.txt" in fake_client.objects
