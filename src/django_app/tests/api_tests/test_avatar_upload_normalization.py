"""POST/DELETE /api/profile/avatar/: what is stored is a small, clean re-encoding of the upload.

The stored avatar is upright, fits in 512x512 without being upscaled, carries no EXIF
or comments, keeps its format, colour profile and transparency. An image that is
broken, too deep, or decodes to more pixels than the limits allow, is refused
and leaves the current avatar alone. The
previous file is deleted only once the change commits, and a failing delete never
turns the committed change into an error.
"""

import io
import struct
import zlib

import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework import status

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

AVATAR_URL = "/api/profile/avatar/"
EXIF_ORIENTATION = 0x0112
EXIF_MAKE = 0x010F


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path_factory):
    # tests/conftest.py replaces `tmp_path` with one directory shared by every test.
    settings.MEDIA_ROOT = str(tmp_path_factory.mktemp("media"))


@pytest.fixture
def uploader(client_as, member_only):
    return client_as(member_only)


def _image(format_name, size=(64, 48), mode="RGB", color=(200, 100, 50), **save_options) -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, size, color).save(buffer, format=format_name, **save_options)
    return buffer.getvalue()


def _png_with_a_broken_chunk() -> bytes:
    """A PNG whose image data continues in a chunk with an invalid id: Pillow raises SyntaxError."""
    png = _image("PNG")
    start = png.index(b"IDAT") - 4
    (length,) = struct.unpack(">I", png[start : start + 4])
    data = png[start + 8 : start + 8 + length]

    def chunk(chunk_id, payload):
        crc = zlib.crc32(chunk_id + payload)
        return struct.pack(">I", len(payload)) + chunk_id + payload + struct.pack(">I", crc)

    half = len(data) // 2
    broken = chunk(b"IDAT", data[:half]) + chunk(b"ID T", data[half:])
    return png[:start] + broken + png[start + 12 + length :]


def _upload(client, content: bytes, format_name="PNG"):
    extension = "jpg" if format_name == "JPEG" else "png"
    upload = SimpleUploadedFile(f"upload.{extension}", content, content_type=f"image/{extension}")
    return client.post(AVATAR_URL, {"avatar": upload}, format="multipart")


def _stored_bytes(user) -> bytes:
    user.refresh_from_db()
    with user.avatar.open("rb") as stored:
        return stored.read()


def _stored_image(user) -> Image.Image:
    return Image.open(io.BytesIO(_stored_bytes(user)))


def _seed_avatar(user) -> str:
    user.avatar.save("seed.png", ContentFile(_image("PNG")), save=True)
    return user.avatar.name


@pytest.mark.django_db
def test_a_phone_photo_is_rotated_upright_and_stripped_of_metadata_but_its_colour_profile(
    uploader, member_only
):
    exif = Image.Exif()
    # Orientation 6: the viewer must rotate the 80x40 sensor image upright.
    exif[EXIF_ORIENTATION] = 6
    exif[EXIF_MAKE] = "SecretCam"
    photo = _image("JPEG", size=(80, 40), exif=exif, icc_profile=b"ICC-MARKER", comment=b"COMMENT-MARKER")

    response = _upload(uploader, photo, "JPEG")

    assert response.status_code == status.HTTP_200_OK
    stored_bytes = _stored_bytes(member_only)
    stored = Image.open(io.BytesIO(stored_bytes))
    assert stored.size == (40, 80)
    assert len(stored.getexif()) == 0
    assert stored.info.get("icc_profile") == b"ICC-MARKER"
    for marker in (b"SecretCam", b"COMMENT-MARKER"):
        assert marker not in stored_bytes


@pytest.mark.django_db
def test_a_phone_jpeg_with_a_depth_map_is_stored_as_a_jpeg(uploader, member_only):
    mpo = _image("MPO", save_all=True, append_images=[Image.new("RGB", (32, 24))])

    response = _upload(uploader, mpo, "JPEG")

    assert response.status_code == status.HTTP_200_OK
    assert _stored_image(member_only).format == "JPEG"
    assert member_only.avatar.name.endswith(".jpg")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("format_name", "size", "stored_size", "extension"),
    [
        ("JPEG", (2048, 1024), (512, 256), ".jpg"),
        ("PNG", (300, 900), (171, 512), ".png"),
        ("PNG", (64, 48), (64, 48), ".png"),
    ],
    ids=["wide-jpeg", "tall-png", "small-not-upscaled"],
)
def test_the_stored_image_keeps_its_format_and_fits_512(
    uploader, member_only, format_name, size, stored_size, extension
):
    response = _upload(uploader, _image(format_name, size=size), format_name)

    assert response.status_code == status.HTTP_200_OK
    stored = _stored_image(member_only)
    assert (stored.format, stored.size) == (format_name, stored_size)
    assert member_only.avatar.name.endswith(extension)
    assert response.json()["avatar_url"].endswith(f"/media/{member_only.avatar.name}")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("content", "format_name", "mode"),
    [
        (_image("PNG", mode="RGBA", color=(10, 20, 30, 0)), "PNG", "RGBA"),
        (_image("PNG", mode="P", color=0, transparency=0), "PNG", "RGBA"),
        (_image("JPEG", mode="CMYK", color=(0, 255, 255, 0), icc_profile=b"CMYK-ICC"), "JPEG", "RGB"),
    ],
    ids=["png-rgba", "png-palette-with-transparent-index", "cmyk-jpeg"],
)
def test_transparency_is_kept_and_a_cmyk_jpeg_becomes_rgb(uploader, member_only, content, format_name, mode):
    _upload(uploader, content, format_name)

    stored = _stored_image(member_only)
    assert stored.mode == mode
    # A CMYK profile no longer describes the converted RGB pixels.
    assert "icc_profile" not in stored.info
    if mode == "RGBA":
        assert stored.getpixel((0, 0))[3] == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "content",
    [_image("PNG")[:60], _png_with_a_broken_chunk(), _image("PNG", mode="I;16", color=300), _image("BMP")],
    ids=["truncated-png", "broken-png-chunk", "16-bit-png", "bmp-disguised-as-png"],
)
def test_a_broken_or_disallowed_image_is_refused_and_the_current_avatar_kept(uploader, member_only, content):
    current = _seed_avatar(member_only)

    response = _upload(uploader, content)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "invalid_avatar"
    member_only.refresh_from_db()
    assert member_only.avatar.name == current


@pytest.mark.django_db
def test_the_size_limit_is_inclusive(uploader, settings):
    content = _image("PNG")
    settings.AVATAR_MAX_SIZE = len(content)
    assert _upload(uploader, content).status_code == status.HTTP_200_OK

    settings.AVATAR_MAX_SIZE = len(content) - 1
    response = _upload(uploader, content)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "avatar_too_large"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("format_name", "size", "accepted"),
    [
        ("PNG", (512, 512), True),
        ("PNG", (513, 512), False),
        ("JPEG", (4096, 4096), True),
        ("JPEG", (4096, 300), False),
    ],
    ids=[
        "png-at-the-limit",
        "png-one-column-over",
        "jpeg-the-decoder-shrinks-to-the-limit",
        "jpeg-the-decoder-cannot-shrink",
    ],
)
def test_an_image_decoding_to_more_pixels_than_the_limit_is_refused(
    uploader, member_only, monkeypatch, format_name, size, accepted
):
    # A few hundred KB of PNG can declare ~89 MP; the limit is on what gets decoded,
    # so a JPEG counts at the scale its decoder reads it.
    monkeypatch.setattr("rbac.profile.avatar.AVATAR_MAX_DECODED_PIXELS", 512 * 512)

    response = _upload(uploader, _image(format_name, size=size), format_name)

    assert response.status_code == (status.HTTP_200_OK if accepted else status.HTTP_400_BAD_REQUEST)
    member_only.refresh_from_db()
    assert bool(member_only.avatar) is accepted


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("size", "progressive", "accepted"),
    [((1000, 1000), True, True), ((1001, 1000), True, False), ((1001, 1000), False, True)],
    ids=["progressive-at-the-limit", "progressive-one-column-over", "baseline-not-capped"],
)
def test_a_progressive_jpeg_over_its_declared_limit_is_refused(uploader, monkeypatch, size, progressive, accepted):
    # draft() cannot shrink a progressive JPEG's decode buffers, so its declared size is bounded.
    monkeypatch.setattr("rbac.profile.avatar.AVATAR_MAX_PROGRESSIVE_PIXELS", 1000 * 1000)

    response = _upload(uploader, _image("JPEG", size=size, progressive=progressive), "JPEG")

    assert response.status_code == (status.HTTP_200_OK if accepted else status.HTTP_400_BAD_REQUEST)


@pytest.mark.django_db
def test_an_image_pillow_refuses_to_open_is_refused(uploader, member_only, monkeypatch):
    # Over twice MAX_IMAGE_PIXELS Pillow raises while reading the header, before the
    # avatar limit is checked; scale its limit down instead of building such a file.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100 * 100)

    response = _upload(uploader, _image("PNG", size=(300, 300)))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "invalid_avatar"


@pytest.mark.django_db
def test_replacing_deletes_the_previous_file_only_once_committed(
    uploader, member_only, django_capture_on_commit_callbacks
):
    previous = _seed_avatar(member_only)
    storage = member_only.avatar.storage

    with django_capture_on_commit_callbacks() as callbacks:
        response = _upload(uploader, _image("JPEG"), "JPEG")

    assert response.status_code == status.HTTP_200_OK
    assert storage.exists(previous), "deleted before the transaction committed"
    for callback in callbacks:
        callback()
    assert not storage.exists(previous)


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["replace", "clear"])
def test_a_failing_delete_of_the_previous_file_keeps_the_committed_change(
    uploader, member_only, mocker, django_capture_on_commit_callbacks, action
):
    previous = _seed_avatar(member_only)
    mocker.patch.object(member_only.avatar.storage, "delete", side_effect=OSError("bucket unavailable"))

    with django_capture_on_commit_callbacks(execute=True):
        response = _upload(uploader, _image("PNG")) if action == "replace" else uploader.delete(AVATAR_URL)

    assert response.status_code in (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT)
    member_only.refresh_from_db()
    assert member_only.avatar.name != previous
