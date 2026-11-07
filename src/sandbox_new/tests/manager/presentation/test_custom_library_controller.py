"""Responses of the custom library controller.

One case per status the resource can answer with. The statuses are the contract a
gateway in front of this service relies on, and three of them -- 400, 404, 409 -- are
produced by domain errors travelling through the registered handlers rather than by the
controller itself, so they are worth asserting over HTTP rather than in isolation.
"""

import io
import tarfile
import zipfile

from litestar import status_codes

from manager.domain.enums import WheelStatus
from manager.domain.models import CustomLibrary, Wheel

WHEEL_NAME = "My_Library-1.0.0-py3-none-any.whl"


def make_wheel(library_id: int, status: WheelStatus, error: str | None = None) -> Wheel:
    return Wheel(
        library_id=library_id,
        source_filename="my-library-1.0.0.tar.gz",
        upload_sha256=str(library_id).ljust(64, "0"),
        status=status,
        error=error,
    )


def wheel_bytes(package: str = "my_library") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(f"{package}/__init__.py", "V = 1")
    return buffer.getvalue()


def archive_bytes() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        payload = b'[project]\nname = "my-library"\n'
        info = tarfile.TarInfo("my-library-1.0.0/pyproject.toml")
        info.size = len(payload)
        bundle.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def upload(filename: str, payload: bytes) -> dict:
    return {"file": (filename, payload, "application/octet-stream")}


def test_list_returns_the_paging_envelope(client, uow):
    uow.custom_library_repo.seed(CustomLibrary(name="a"), CustomLibrary(name="b"))

    response = client.get("/custom-libraries")

    assert response.status_code == status_codes.HTTP_200_OK
    body = response.json()
    assert body["count"] == 2
    assert [library["name"] for library in body["result"]] == ["a", "b"]


def test_list_carries_the_state_of_each_librarys_versions(client, uow):
    """What a listing says about builds, so that a reader is not made to open every
    library to find the one whose version did not arrive."""
    failing, building, empty = uow.custom_library_repo.seed(
        CustomLibrary(name="a"), CustomLibrary(name="b"), CustomLibrary(name="c")
    )
    uow.wheel_repo.seed(
        make_wheel(failing.id, WheelStatus.FAILED, error="no setup.py"),
        make_wheel(building.id, WheelStatus.PROCESSING),
    )

    body = client.get("/custom-libraries").json()

    assert [(library["status"], library["error"]) for library in body["result"]] == [
        ("failed", "no setup.py"),
        ("processing", None),
        (None, None),
    ]
    assert empty.id == body["result"][2]["id"]


def test_retrieve_carries_the_state_of_the_librarys_versions(client, uow):
    stored = uow.custom_library_repo.seed(CustomLibrary(name="my-library"))[0]
    uow.wheel_repo.seed(make_wheel(stored.id, WheelStatus.FAILED, error="no setup.py"))

    body = client.get(f"/custom-libraries/{stored.id}").json()

    assert body["status"] == "failed"
    assert body["error"] == "no setup.py"


def test_list_applies_ids_limit_and_offset(client, uow):
    first, second, third = uow.custom_library_repo.seed(
        CustomLibrary(name="a"), CustomLibrary(name="b"), CustomLibrary(name="c")
    )

    response = client.get(
        "/custom-libraries",
        params={"ids": [first.id, second.id, third.id], "limit": 1, "offset": 1},
    )

    body = response.json()
    assert body["count"] == 3
    assert [library["name"] for library in body["result"]] == ["b"]


def test_create_answers_201_with_the_library_named_after_the_wheel(client, uow, file_storage):
    response = client.post("/custom-libraries", files=upload(WHEEL_NAME, wheel_bytes()))

    assert response.status_code == status_codes.HTTP_201_CREATED
    body = response.json()
    assert body["id"] in uow.custom_library_repo.rows
    assert body["name"] == "my-library"
    assert body["created_at"] is not None
    # A ready-made wheel is complete on arrival, so the library it creates is too.
    assert body["status"] == "completed"
    assert len(file_storage.objects) == 1


def test_create_answers_201_with_an_unnamed_library_for_a_source_archive(client, uow, file_storage):
    """The distribution a source archive builds is not known until it does, so the
    library it creates has no name yet, and a background build is what names it."""
    response = client.post("/custom-libraries", files=upload("archive.tar.gz", archive_bytes()))

    assert response.status_code == status_codes.HTTP_201_CREATED
    body = response.json()
    assert body["id"] in uow.custom_library_repo.rows
    assert body["name"] is None
    # The archive still has to be built, and the library says so from the start.
    assert body["status"] == "declared"
    assert len(file_storage.objects) == 1


def test_create_answers_400_for_an_upload_that_is_neither_a_wheel_nor_an_archive(client):
    response = client.post("/custom-libraries", files=upload("notes.txt", b"hello"))

    assert response.status_code == status_codes.HTTP_400_BAD_REQUEST
    assert response.json()["errors"][0]["attr"] == "file"


def test_create_answers_409_for_a_name_already_taken(client, uow):
    client.post("/custom-libraries", files=upload(WHEEL_NAME, wheel_bytes()))

    response = client.post(
        "/custom-libraries", files=upload("my_library-2.0.0-py3-none-any.whl", wheel_bytes())
    )

    assert response.status_code == status_codes.HTTP_409_CONFLICT
    assert response.json()["errors"][0]["code"] == "custom_library_name_taken"
    # Refused before the second wheel is stored, and the first library and its file
    # are untouched.
    assert len(uow.custom_library_repo.rows) == 1


def test_retrieve_answers_200(client, uow):
    stored = uow.custom_library_repo.seed(CustomLibrary(name="my-library"))[0]

    response = client.get(f"/custom-libraries/{stored.id}")

    assert response.status_code == status_codes.HTTP_200_OK
    assert response.json()["id"] == stored.id


def test_retrieve_answers_404_for_a_library_that_is_not_there(client):
    response = client.get("/custom-libraries/404")

    assert response.status_code == status_codes.HTTP_404_NOT_FOUND
    assert response.json()["errors"][0]["code"] == "custom_library_not_found"


def test_remove_answers_204_and_the_library_stops_answering(client, uow):
    stored = uow.custom_library_repo.seed(CustomLibrary(name="doomed"))[0]

    response = client.delete(f"/custom-libraries/{stored.id}")

    assert response.status_code == status_codes.HTTP_204_NO_CONTENT
    assert client.get(f"/custom-libraries/{stored.id}").status_code == (
        status_codes.HTTP_404_NOT_FOUND
    )


def test_remove_answers_404_for_a_library_that_is_not_there(client):
    assert (
        client.delete("/custom-libraries/404").status_code == status_codes.HTTP_404_NOT_FOUND
    )


def test_remove_answers_409_for_a_library_a_venv_uses(client, uow):
    from manager.domain.models import Library, Venv

    stored = uow.custom_library_repo.seed(CustomLibrary(name="acme-core"))[0]
    uow.venv_repo.seed(
        Venv(name="data", libs=[Library(name="acme-core", specification=">=1", is_custom=True)])
    )

    response = client.delete(f"/custom-libraries/{stored.id}")

    assert response.status_code == status_codes.HTTP_409_CONFLICT
    assert response.json()["errors"][0]["code"] == "custom_library_in_use"
