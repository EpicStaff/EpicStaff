"""Approval checks the stored package again and publishes only once it commits; reject unpublishes."""

import hashlib
import os

import pytest
from plugins.exceptions import UntrustedNotAcknowledgedError
from plugins.lifecycle.installation_service import PluginInstallationService
from plugins.models import (
    Plugin,
    PluginPackage,
    PluginPackageNavigationIcon,
    PluginState,
    ReviewState,
    SignatureStatus,
    Trust,
)
from plugins.packages.spa_publisher import SpaPublisher

from tests.plugins_tests.conftest import InMemoryPackageStore, upload_file
from tests.plugins_tests.package_builder import (
    INDEX_HTML,
    MENU_ICON_PNG,
    MENU_ICON_SVG,
    build_package,
    menu_manifest,
    sample_manifest,
)

pytestmark = pytest.mark.django_db

PACKAGES_URL = "/api/admin/plugins/packages/"


def _upload(installation, user, data=None):
    data = data or build_package()
    return installation.upload(upload_file(data), len(data), user)


def test_a_key_removed_since_the_upload_makes_the_package_untrusted_at_approval(
    installation, superadmin, settings, trusts_release_key
):
    package = _upload(installation, superadmin, build_package(signed_with=trusts_release_key))
    assert package.trust == Trust.TRUSTED
    settings.PLUGINS_TRUSTED_SIGNING_KEYS = []

    with pytest.raises(UntrustedNotAcknowledgedError):
        installation.approve(package.pk, superadmin, untrusted_acknowledged=False)

    package.refresh_from_db()
    assert (package.trust, package.signature_status, package.review_state) == (
        Trust.UNTRUSTED,
        SignatureStatus.UNKNOWN_KEY,
        ReviewState.PENDING,
    )
    assert package.signer_key_id == trusts_release_key.public_key.display_id
    assert package.signer_key_name is None

    plugin = installation.approve(package.pk, superadmin, untrusted_acknowledged=True)

    assert plugin.state == PluginState.RUNNING
    assert plugin.current_package.trust == Trust.UNTRUSTED


@pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")
def test_the_api_asks_for_the_acknowledgement_once_the_key_is_gone(superadmin_client, settings, trusts_release_key):
    review = superadmin_client.post(
        PACKAGES_URL, {"file": upload_file(build_package(signed_with=trusts_release_key))}, format="multipart"
    ).json()
    settings.PLUGINS_TRUSTED_SIGNING_KEYS = []

    response = superadmin_client.post(f"{PACKAGES_URL}{review['id']}/approve/", {}, format="json")

    assert response.status_code == 400
    assert response.json()["code"] == "untrusted_not_acknowledged"
    again = superadmin_client.get(f"{PACKAGES_URL}{review['id']}/review/").json()
    assert (again["trust"], again["signature"]) == ("untrusted", "unknown_key")
    assert [warning["code"] for warning in again["warnings"]] == ["untrusted_package"]


def test_a_key_listed_since_the_upload_makes_the_package_trusted_at_approval(
    installation, superadmin, settings, release_key
):
    package = _upload(installation, superadmin, build_package(signed_with=release_key))
    assert package.trust == Trust.UNTRUSTED
    settings.PLUGINS_TRUSTED_SIGNING_KEYS = [f"release:{release_key.public_key.to_text()}"]

    plugin = installation.approve(package.pk, superadmin, untrusted_acknowledged=False)

    approved = plugin.current_package
    approved.refresh_from_db()
    assert (approved.trust, approved.signature_status, approved.signer_key_name) == (
        Trust.TRUSTED,
        SignatureStatus.VALID,
        "release",
    )


@pytest.mark.usefixtures("plugins_enabled", "spa_root")
@pytest.mark.parametrize("change", ["missing", "replaced"])
def test_a_stored_file_that_is_gone_or_changed_is_a_conflict(superadmin_client, package_store, mocker, change):
    logger = mocker.patch("plugins.lifecycle.installation_service.logger")
    review = superadmin_client.post(PACKAGES_URL, {"file": upload_file(build_package())}, format="multipart").json()
    [storage_key] = package_store.objects
    other_package = build_package(manifest=sample_manifest(name="Not the reviewed one"))
    if change == "missing":
        package_store.objects.clear()
    else:
        package_store.objects[storage_key] = other_package

    response = superadmin_client.post(
        f"{PACKAGES_URL}{review['id']}/approve/", {"untrusted_acknowledged": True}, format="json"
    )

    assert response.status_code == 409
    assert response.json()["code"] == "package_file_mismatch"
    assert PluginPackage.objects.get().review_state == ReviewState.PENDING
    logged = logger.error.call_args.kwargs
    assert logged["package_id"] == review["id"]
    assert logged["storage_key"] == storage_key
    assert logged["expected"] == review["sha256"]
    expected_found = "nothing" if change == "missing" else hashlib.sha256(other_package).hexdigest()
    assert logged["found"] == expected_found


def test_approving_a_package_with_a_menu_checks_the_stored_file_again_and_keeps_its_icons(installation, superadmin):
    package = _upload(installation, superadmin, build_package(manifest=menu_manifest()))

    plugin = installation.approve(package.pk, superadmin, untrusted_acknowledged=True)

    assert (plugin.state, plugin.current_package_id) == (PluginState.RUNNING, package.pk)
    assert [
        (icon.package_id, icon.path, icon.media_type, bytes(icon.icon_bytes))
        for icon in PluginPackageNavigationIcon.objects.order_by("path")
    ] == [
        (package.pk, "icons/forecast.svg", "image/svg+xml", MENU_ICON_SVG),
        (package.pk, "icons/places.png", "image/png", MENU_ICON_PNG),
    ]


def test_the_spa_is_served_only_once_the_approval_commits(
    installation, superadmin, spa_root, django_capture_on_commit_callbacks
):
    package = _upload(installation, superadmin)

    with django_capture_on_commit_callbacks() as callbacks:
        installation.approve(package.pk, superadmin, untrusted_acknowledged=True)

    assert (spa_root / "weather" / "0.1.0" / "index.html").read_bytes() == INDEX_HTML
    assert not (spa_root / "weather" / "current").exists()

    for callback in callbacks:
        callback()

    assert os.readlink(spa_root / "weather" / "current") == "0.1.0"


def test_a_failed_approval_serves_nothing_and_leaves_no_files(installation, superadmin, spa_root, monkeypatch):
    package = _upload(installation, superadmin)

    def fail(*arguments, **keywords):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(Plugin, "save", fail)

    with pytest.raises(RuntimeError, match="went away"):
        installation.approve(package.pk, superadmin, untrusted_acknowledged=True)

    assert not (spa_root / "weather" / "0.1.0").exists()
    assert not (spa_root / "weather" / "current").exists()
    package.refresh_from_db()
    assert package.review_state == ReviewState.PENDING


def test_rejecting_a_never_approved_plugin_removes_its_files(
    installation, superadmin, spa_root, django_capture_on_commit_callbacks
):
    package = _upload(installation, superadmin)
    leftover = spa_root / "weather" / "0.1.0"
    leftover.mkdir(parents=True)
    (leftover / "index.html").write_bytes(INDEX_HTML)

    with django_capture_on_commit_callbacks(execute=True):
        installation.reject(package.pk, superadmin)

    assert not (spa_root / "weather").exists()
    assert not Plugin.objects.exists()


class FailingDeleteStore(InMemoryPackageStore):
    def delete(self, key):
        raise RuntimeError("storage is down")


def test_a_failing_cleanup_does_not_hide_why_the_upload_failed(superadmin, spa_root, monkeypatch, mocker):
    logger = mocker.patch("plugins.lifecycle.installation_service.logger")
    installation = PluginInstallationService(store=FailingDeleteStore(), publisher=SpaPublisher(spa_root))

    def fail(*arguments, **keywords):
        raise ValueError("registration failed")

    monkeypatch.setattr(installation, "_register_pending_package", fail)

    with pytest.raises(ValueError, match="registration failed"):
        _upload(installation, superadmin)

    assert logger.exception.called


def test_a_cleanup_that_fails_after_a_reject_commits_leaves_the_reject_done(
    superadmin, spa_root, django_capture_on_commit_callbacks
):
    installation = PluginInstallationService(store=FailingDeleteStore(), publisher=SpaPublisher(spa_root))
    package = _upload(installation, superadmin)

    with django_capture_on_commit_callbacks(execute=True):
        installation.reject(package.pk, superadmin)

    assert not PluginPackage.objects.filter(pk=package.pk).exists()
    assert not Plugin.objects.exists()


def test_a_cleanup_that_fails_after_a_replacing_upload_leaves_the_new_package(
    superadmin, spa_root, django_capture_on_commit_callbacks
):
    installation = PluginInstallationService(store=FailingDeleteStore(), publisher=SpaPublisher(spa_root))
    first = _upload(installation, superadmin)
    data = build_package(manifest=sample_manifest(description="A newer description."))

    with django_capture_on_commit_callbacks(execute=True):
        replacing = installation.upload(upload_file(data), len(data), superadmin)

    assert list(PluginPackage.objects.values_list("pk", flat=True)) == [replacing.pk]
    assert replacing.pk != first.pk
