from tables.services.storage_service.base import AbstractStorageBackend


_increment = AbstractStorageBackend._increment_name


def test_file_gets_suffix_one():
    assert _increment("report.txt") == "report (1).txt"


def test_file_bumps_existing_counter():
    assert _increment("report (1).txt") == "report (2).txt"


def test_file_without_extension():
    assert _increment("readme") == "readme (1)"


def test_file_without_extension_bumps_counter():
    assert _increment("readme (3)") == "readme (4)"


def test_folder_gets_suffix_one():
    assert _increment("data", is_folder=True) == "data (1)"


def test_folder_bumps_existing_counter():
    assert _increment("data (1)", is_folder=True) == "data (2)"
