"""Responses of the wheel controller.

One case per status the resource can answer with. Two of them are worth more than the
number: the 400 for an upload whose bytes do not match its name, which is the one check
that happens while the body is still being parsed, and the 404 for a version addressed
through the wrong library, which is what keeps one library's versions out of another's.

The uploads are real archives, because telling a wheel from a source archive is exactly
what the schema does with them.
"""

import io
import tarfile
import zipfile

import pytest
from litestar import status_codes

from manager.domain.enums import WheelStatus
from manager.domain.models import CustomLibrary

WHEEL_NAME = "my_library-1.0.0-py3-none-any.whl"
ARCHIVE_NAME = "my-library-2.0.0.tar.gz"


def wheel_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("my_library/__init__.py", "V = 1")
    return buffer.getvalue()


def archive_bytes() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        payload = b'[project]\nname = "my-library"\n'
        info = tarfile.TarInfo("my-library-2.0.0/pyproject.toml")
        info.size = len(payload)
        bundle.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def upload(filename: str, payload: bytes) -> dict:
    return {"file": (filename, payload, "application/octet-stream")}


@pytest.fixture
def library(uow) -> CustomLibrary:
    return uow.custom_library_repo.seed(CustomLibrary(name="my-library"))[0]


@pytest.fixture
def path(library) -> str:
    return f"/custom-libraries/{library.id}/wheels"


def test_upload_of_a_wheel_answers_201_with_a_completed_version(client, path, file_storage):
    response = client.post(path, files=upload(WHEEL_NAME, wheel_bytes()))

    assert response.status_code == status_codes.HTTP_201_CREATED
    body = response.json()
    assert body["status"] == WheelStatus.COMPLETED
    assert body["version"] == "1.0.0"
    assert body["wheel_filename"] == WHEEL_NAME
    assert len(file_storage.objects) == 1


def test_upload_of_an_archive_answers_201_with_a_declared_version(client, path):
    response = client.post(path, files=upload(ARCHIVE_NAME, archive_bytes()))

    assert response.status_code == status_codes.HTTP_201_CREATED
    body = response.json()
    assert body["status"] == WheelStatus.DECLARED
    assert body["version"] is None
    assert body["source_filename"] == ARCHIVE_NAME


@pytest.mark.parametrize(
    ("filename", "payload", "says"),
    [
        ("notes.txt", b"plain text", "neither a wheel"),
        (WHEEL_NAME, b"not a zip at all", "not a zip archive"),
        (ARCHIVE_NAME, b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03", "not a tar archive"),
    ],
    ids=["unsupported suffix", "wheel name over other bytes", "truncated archive"],
)
def test_upload_answers_400_when_the_file_is_not_what_its_name_says(
    client, path, filename, payload, says
):
    """The wording separates the two mistakes a client can make -- sending a kind of
    file this resource does not take, and sending the right kind under the wrong name --
    and only the first can say what would be accepted instead.

    A corrupt archive makes the format check raise rather than answer, and that is still
    the caller's mistake: without it the upload would be a 500.
    """
    response = client.post(path, files=upload(filename, payload))

    assert response.status_code == status_codes.HTTP_400_BAD_REQUEST
    assert response.json()["errors"][0]["attr"] == "file"
    assert says in response.json()["errors"][0]["detail"]


def test_upload_answers_400_for_a_wheel_built_for_another_distribution(client, path):
    response = client.post(
        path, files=upload("other_lib-1.0.0-py3-none-any.whl", wheel_bytes())
    )

    assert response.status_code == status_codes.HTTP_400_BAD_REQUEST
    assert response.json()["errors"][0]["code"] == "bad_request"


def test_upload_answers_404_for_a_library_that_is_not_there(client):
    response = client.post(
        "/custom-libraries/404/wheels", files=upload(WHEEL_NAME, wheel_bytes())
    )

    assert response.status_code == status_codes.HTTP_404_NOT_FOUND


def test_upload_answers_409_for_a_file_this_library_already_holds(client, path):
    """Renamed to a version that is free, so only the content can refuse it."""
    payload = wheel_bytes()
    client.post(path, files=upload(WHEEL_NAME, payload))

    response = client.post(
        path, files=upload("my_library-9.9.9-py3-none-any.whl", payload)
    )

    assert response.status_code == status_codes.HTTP_409_CONFLICT


def test_upload_answers_409_for_a_version_this_library_already_published(client, path):
    client.post(path, files=upload(WHEEL_NAME, wheel_bytes()))

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("my_library/__init__.py", "V = 2")
    response = client.post(path, files=upload(WHEEL_NAME, buffer.getvalue()))

    assert response.status_code == status_codes.HTTP_409_CONFLICT


def test_list_returns_every_version_of_the_library(client, path):
    client.post(path, files=upload(WHEEL_NAME, wheel_bytes()))
    client.post(path, files=upload(ARCHIVE_NAME, archive_bytes()))

    response = client.get(path)

    assert response.status_code == status_codes.HTTP_200_OK
    assert [version["status"] for version in response.json()] == ["completed", "declared"]


def test_retrieve_answers_200(client, path):
    created = client.post(path, files=upload(WHEEL_NAME, wheel_bytes())).json()

    response = client.get(f"{path}/{created['id']}")

    assert response.status_code == status_codes.HTTP_200_OK
    assert response.json()["id"] == created["id"]


def test_retrieve_answers_404_for_a_version_that_is_not_there(client, path):
    assert client.get(f"{path}/404").status_code == status_codes.HTTP_404_NOT_FOUND


@pytest.mark.parametrize("suffix", ["", "/file"])
def test_a_version_answers_404_when_addressed_through_another_library(client, path, uow, suffix):
    """The library is part of the lookup, so an id guessed from another one answers as
    if the version did not exist rather than handing it over."""
    created = client.post(path, files=upload(WHEEL_NAME, wheel_bytes())).json()
    other = uow.custom_library_repo.seed(CustomLibrary(name="other-library"))[0]

    response = client.get(f"/custom-libraries/{other.id}/wheels/{created['id']}{suffix}")

    assert response.status_code == status_codes.HTTP_404_NOT_FOUND


def test_download_answers_200_with_the_wheel_as_an_attachment(client, path):
    payload = wheel_bytes()
    created = client.post(path, files=upload(WHEEL_NAME, payload)).json()

    response = client.get(f"{path}/{created['id']}/file")

    assert response.status_code == status_codes.HTTP_200_OK
    assert response.content == payload
    assert response.headers["content-disposition"] == f'attachment; filename="{WHEEL_NAME}"'
    assert response.headers["content-type"] == "application/octet-stream"


def test_download_answers_409_for_a_version_that_has_no_wheel_yet(client, path):
    created = client.post(path, files=upload(ARCHIVE_NAME, archive_bytes())).json()

    response = client.get(f"{path}/{created['id']}/file")

    assert response.status_code == status_codes.HTTP_409_CONFLICT
    assert response.json()["errors"][0]["code"] == "conflict"


def test_remove_answers_204_and_the_version_stops_answering(client, path):
    created = client.post(path, files=upload(WHEEL_NAME, wheel_bytes())).json()

    response = client.delete(f"{path}/{created['id']}")

    assert response.status_code == status_codes.HTTP_204_NO_CONTENT
    assert client.get(f"{path}/{created['id']}").status_code == status_codes.HTTP_404_NOT_FOUND


def test_remove_answers_404_for_a_version_that_is_not_there(client, path):
    assert client.delete(f"{path}/404").status_code == status_codes.HTTP_404_NOT_FOUND


def test_a_version_removed_through_the_api_is_only_marked(client, path, uow, library, file_storage):
    """What the gateway in front of this must not assume: a 204 does not mean the files
    are gone, only that nothing answers for them any more."""
    created = client.post(path, files=upload(WHEEL_NAME, wheel_bytes())).json()

    client.delete(f"{path}/{created['id']}")

    assert len(uow.wheel_repo.rows) == 1
    assert len(file_storage.objects) == 1
