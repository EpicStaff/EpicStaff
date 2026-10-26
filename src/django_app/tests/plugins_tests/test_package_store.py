"""The package bucket is created on first use; botocore's Stubber stands in for object storage."""

import io

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber
from plugins.packages.package_store import PackageFileMissingError, PluginPackageStore, package_storage_key


@pytest.fixture
def client():
    return boto3.client(
        "s3", region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test"
    )


def test_the_storage_key_names_plugin_version_and_digest():
    assert package_storage_key("weather", "0.1.0", "ab" * 32) == f"packages/weather/0.1.0/{'ab' * 32}.esplugin"


def test_a_missing_bucket_is_created_once(client):
    store = PluginPackageStore(client, "epicstaff-plugins")
    with Stubber(client) as stubber:
        stubber.add_client_error("head_bucket", service_error_code="404", http_status_code=404)
        stubber.add_response("create_bucket", {}, {"Bucket": "epicstaff-plugins"})
        stubber.add_response("put_object", {}, None)
        stubber.add_response("put_object", {}, None)

        store.save("packages/a", io.BytesIO(b"a"))
        store.save("packages/b", io.BytesIO(b"b"))

        stubber.assert_no_pending_responses()


def test_an_existing_bucket_is_not_created_again(client):
    store = PluginPackageStore(client, "epicstaff-plugins")
    with Stubber(client) as stubber:
        stubber.add_response("head_bucket", {}, {"Bucket": "epicstaff-plugins"})
        stubber.add_response("put_object", {}, None)

        store.save("packages/a", io.BytesIO(b"a"))

        stubber.assert_no_pending_responses()


def test_a_bucket_created_by_another_worker_meanwhile_is_fine(client):
    store = PluginPackageStore(client, "epicstaff-plugins")
    with Stubber(client) as stubber:
        stubber.add_client_error("head_bucket", service_error_code="NoSuchBucket", http_status_code=404)
        stubber.add_client_error("create_bucket", service_error_code="BucketAlreadyOwnedByYou", http_status_code=409)
        stubber.add_response("put_object", {}, None)

        store.save("packages/a", io.BytesIO(b"a"))

        stubber.assert_no_pending_responses()


def test_other_storage_errors_are_raised(client):
    store = PluginPackageStore(client, "epicstaff-plugins")
    with Stubber(client) as stubber:
        stubber.add_client_error("head_bucket", service_error_code="403", http_status_code=403)

        with pytest.raises(ClientError):
            store.save("packages/a", io.BytesIO(b"a"))


def test_delete_removes_the_object(client):
    store = PluginPackageStore(client, "epicstaff-plugins")
    with Stubber(client) as stubber:
        stubber.add_response("delete_object", {}, {"Bucket": "epicstaff-plugins", "Key": "packages/a"})

        store.delete("packages/a")

        stubber.assert_no_pending_responses()


@pytest.mark.parametrize("code", ["404", "NoSuchKey"])
def test_downloading_a_missing_object_says_so(client, code):
    store = PluginPackageStore(client, "epicstaff-plugins")
    with Stubber(client) as stubber:
        stubber.add_client_error("head_object", service_error_code=code, http_status_code=404)

        with pytest.raises(PackageFileMissingError):
            store.download("packages/a", io.BytesIO())


def test_other_download_errors_are_raised(client):
    store = PluginPackageStore(client, "epicstaff-plugins")
    with Stubber(client) as stubber:
        stubber.add_client_error("head_object", service_error_code="AccessDenied", http_status_code=403)

        with pytest.raises(ClientError):
            store.download("packages/a", io.BytesIO())



def test_a_package_is_opened_as_a_stream_with_its_size(client):
    store = PluginPackageStore(client, "epicstaff-plugins")
    body = io.BytesIO(b"package bytes")
    with Stubber(client) as stubber:
        stubber.add_response(
            "get_object",
            {"Body": body, "ContentLength": 13},
            {"Bucket": "epicstaff-plugins", "Key": "packages/a"},
        )

        stream, size = store.open("packages/a")

    assert (stream.read(), size) == (b"package bytes", 13)


def test_opening_a_missing_package_says_so(client):
    store = PluginPackageStore(client, "epicstaff-plugins")
    with Stubber(client) as stubber:
        stubber.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)

        with pytest.raises(PackageFileMissingError):
            store.open("packages/missing")
