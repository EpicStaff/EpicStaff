from dataclasses import replace

import pytest
from ai_models.domain.catalog import Catalog
from ai_models.management.commands import build_model_catalog
from django.core.management import call_command


def test_committed_catalog_is_complete_and_current():
    with pytest.raises(SystemExit) as exit_info:
        call_command("build_model_catalog", "--check")
    assert exit_info.value.code in (None, 0)


def test_check_fails_on_a_stale_catalog_and_leaves_it_as_it_is(tmp_path, monkeypatch, capsys):
    committed = Catalog.from_json(build_model_catalog.CATALOG_PATH.read_text())
    stale_text = replace(committed, litellm_version="0.0.1").to_json() + "\n"
    stale_path = tmp_path / "catalog.json"
    stale_path.write_text(stale_text)
    monkeypatch.setattr(build_model_catalog, "CATALOG_PATH", stale_path)

    with pytest.raises(SystemExit) as exit_info:
        call_command("build_model_catalog", "--check")

    assert exit_info.value.code == 1
    assert "CatalogUpToDateRule" in capsys.readouterr().err
    assert stale_path.read_text() == stale_text
