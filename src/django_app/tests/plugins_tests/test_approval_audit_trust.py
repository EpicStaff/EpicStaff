"""The approval's audit line names the trust and the signer the package was approved with, as
the approval judged them, not as they were at upload."""

import pytest
from plugins.models import Trust

from tests.plugins_tests.conftest import upload_file
from tests.plugins_tests.package_builder import build_package

pytestmark = pytest.mark.django_db


def _approval_line(log_messages) -> str:
    [line] = [message for message in log_messages if message.startswith("PluginInstallationService.approve actor=")]
    return line


def test_a_key_removed_since_the_upload_is_logged_untrusted_without_a_signer(
    installation, superadmin, settings, trusts_release_key, log_messages
):
    data = build_package(signed_with=trusts_release_key)
    package = installation.upload(upload_file(data), len(data), superadmin)
    assert (package.trust, package.signer_key_name) == (Trust.TRUSTED, "release")
    settings.PLUGINS_TRUSTED_SIGNING_KEYS = []

    installation.approve(package.pk, superadmin, untrusted_acknowledged=True)

    line = _approval_line(log_messages)
    assert " trust=untrusted signer=none " in line, line


def test_a_package_still_trusted_is_logged_with_its_signer(installation, superadmin, trusts_release_key, log_messages):
    data = build_package(signed_with=trusts_release_key)
    package = installation.upload(upload_file(data), len(data), superadmin)

    installation.approve(package.pk, superadmin)

    assert " trust=trusted signer=release " in _approval_line(log_messages)
