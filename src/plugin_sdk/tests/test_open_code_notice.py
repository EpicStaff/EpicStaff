import pytest

from conftest import REPO_ROOT
from epicstaff_plugin.cli.main import main
from epicstaff_plugin.notices import OPEN_CODE_NOTICE


def test_pack_prints_the_open_code_notice_once(plugin_source, tmp_path, capsys):
    source, spa = plugin_source

    main(["pack", str(source), "--spa-dir", str(spa), "--out", str(tmp_path / "weather.esplugin")])

    assert capsys.readouterr().out.count(OPEN_CODE_NOTICE) == 1


@pytest.mark.parametrize("page", ["docs/plugins/README.md", "docs/plugins/how-to/sign-and-package.md"])
def test_the_author_docs_quote_the_notice_verbatim(page):
    assert OPEN_CODE_NOTICE in (REPO_ROOT / page).read_text(encoding="utf-8")
