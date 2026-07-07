from conftest import load_tool, seed

tool = load_tool("s3_file_exists_tool")


def test_exists_file(patched_storage, fake_client):
    seed(fake_client, "a.txt", "hello")

    result = tool.main(path="a.txt")

    assert "exists (file)" in result


def test_exists_folder(patched_storage, fake_client):
    seed(fake_client, "dir/a.txt", "hello")

    result = tool.main(path="dir")

    assert "exists (folder)" in result


def test_does_not_exist(patched_storage, fake_client):
    result = tool.main(path="missing.txt")

    assert "does not exist" in result
