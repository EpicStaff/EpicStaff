from conftest import load_tool, seed

tool = load_tool("s3_folder_create_tool")


def test_create_new_folder(patched_storage, fake_client):
    result = tool.main(folder_path="dir")

    assert "Folder created" in result
    assert "dir/.keep" in fake_client.objects


def test_create_idempotent_when_folder_exists(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "hello")

    result = tool.main(folder_path="dir")

    assert "already exists" in result
    assert "dir/.keep" not in fake_client.objects
