"""POST/DELETE /api/profile/avatar/: what is stored is a small, clean re-encoding of the upload.

The stored avatar is upright (EXIF orientation applied), fits in 512x512 without
being upscaled, carries no metadata (EXIF, GPS, ICC, comments), keeps its format and
its transparency. Anything that is not a JPEG or PNG within the size and pixel limits
is refused and leaves the current avatar alone. Replacing or clearing an avatar
deletes the previous object only once the change is committed, and a failing delete
never turns the committed change into an error.
"""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from rest_framework import status

from tests.avatar_helpers import avatar_storage, image_bytes, read_stored_avatar, store_avatar
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

AVATAR_URL = "/api/profile/avatar/"
EXIF_ORIENTATION = 0x0112
EXIF_MAKE = 0x010F
GPS_IFD = 0x8825


def _upload(client, content: bytes, name="upload.png", content_type="image/png"):
    return client.post(
        AVATAR_URL, {"avatar": SimpleUploadedFile(name, content, content_type=content_type)}, format="multipart"
    )


def _stored_image(user) -> Image.Image:
    return Image.open(io.BytesIO(read_stored_avatar(user)))


def _photo_with_metadata(size=(80, 40), orientation=1) -> bytes:
    """A JPEG as a phone writes it: orientation, camera make, GPS position, ICC profile, comment."""
    exif = Image.Exif()
    exif[EXIF_ORIENTATION] = orientation
    exif[EXIF_MAKE] = "SecretCam"
    gps = exif.get_ifd(GPS_IFD)
    gps[1] = "N"
    gps[2] = (50.0, 27.0, 0.0)
    return image_bytes("JPEG", size=size, exif=exif, icc_profile=b"ICC-MARKER", comment=b"COMMENT-MARKER")


@pytest.fixture
def uploader(client_as, member_only):
    return client_as(member_only)


# ---- re-encoding ----


@pytest.mark.django_db
def test_the_exif_orientation_is_applied_and_dropped(uploader, member_only):
    # Orientation 6: the camera was turned, the viewer must rotate the 80x40 sensor image upright.
    response = _upload(uploader, _photo_with_metadata(size=(80, 40), orientation=6), "photo.jpg", "image/jpeg")

    assert response.status_code == status.HTTP_200_OK
    stored = _stored_image(member_only)
    assert stored.size == (40, 80)
    assert EXIF_ORIENTATION not in stored.getexif()


@pytest.mark.django_db
def test_every_metadata_block_of_a_jpeg_is_stripped(uploader, member_only):
    _upload(uploader, _photo_with_metadata(), "photo.jpg", "image/jpeg")

    stored_bytes = read_stored_avatar(member_only)
    stored = Image.open(io.BytesIO(stored_bytes))
    assert len(stored.getexif()) == 0
    assert stored.getexif().get_ifd(GPS_IFD) == {}
    assert "icc_profile" not in stored.info and "comment" not in stored.info
    for marker in (b"SecretCam", b"ICC-MARKER", b"COMMENT-MARKER"):
        assert marker not in stored_bytes


@pytest.mark.django_db
def test_png_text_and_exif_chunks_are_stripped(uploader, member_only):
    text = PngInfo()
    text.add_text("Comment", "PNG-TEXT-MARKER")
    exif = Image.Exif()
    exif[EXIF_MAKE] = "SecretCam"

    _upload(uploader, image_bytes("PNG", pnginfo=text, exif=exif))

    stored_bytes = read_stored_avatar(member_only)
    assert Image.open(io.BytesIO(stored_bytes)).text == {}
    assert b"PNG-TEXT-MARKER" not in stored_bytes and b"SecretCam" not in stored_bytes


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("format_name", "content_type", "size", "stored_size"),
    [
        ("PNG", "image/png", (2000, 1000), (512, 256)),
        ("JPEG", "image/jpeg", (2048, 1024), (512, 256)),
        ("PNG", "image/png", (300, 900), (171, 512)),
        ("PNG", "image/png", (512, 512), (512, 512)),
        ("PNG", "image/png", (64, 48), (64, 48)),
    ],
    ids=["wide-png", "wide-jpeg", "tall-png", "exactly-512", "small-not-upscaled"],
)
def test_the_stored_image_fits_512_and_is_never_upscaled(
    uploader, member_only, format_name, content_type, size, stored_size
):
    response = _upload(uploader, image_bytes(format_name, size=size), f"in.{format_name.lower()}", content_type)

    assert response.status_code == status.HTTP_200_OK
    assert _stored_image(member_only).size == stored_size


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("format_name", "content_type", "extension"),
    [("JPEG", "image/jpeg", ".jpg"), ("PNG", "image/png", ".png")],
)
def test_the_format_is_kept(uploader, member_only, format_name, content_type, extension):
    _upload(uploader, image_bytes(format_name), "upload.bin", content_type)

    member_only.refresh_from_db()
    assert member_only.avatar.name.endswith(extension)
    assert _stored_image(member_only).format == format_name


@pytest.mark.django_db
@pytest.mark.parametrize(
    "content",
    [
        image_bytes("PNG", mode="RGBA", color=(10, 20, 30, 0)),
        image_bytes("PNG", mode="P", color=0, transparency=0),
    ],
    ids=["rgba", "palette-with-transparent-index"],
)
def test_png_transparency_is_kept(uploader, member_only, content):
    _upload(uploader, content)

    stored = _stored_image(member_only)
    assert stored.mode == "RGBA"
    assert stored.getpixel((0, 0))[3] == 0


@pytest.mark.django_db
def test_a_cmyk_jpeg_is_stored_as_rgb(uploader, member_only):
    _upload(uploader, image_bytes("JPEG", mode="CMYK", color=(0, 255, 255, 0)), "print.jpg", "image/jpeg")

    stored = _stored_image(member_only)
    assert (stored.format, stored.mode) == ("JPEG", "RGB")


@pytest.mark.django_db
def test_the_returned_avatar_url_serves_the_stored_image(uploader, member_only):
    response = _upload(uploader, image_bytes("PNG", size=(1024, 1024)))

    served = uploader.get(response.json()["avatar_url"])

    assert served.status_code == status.HTTP_200_OK
    assert served.content == read_stored_avatar(member_only)
    assert Image.open(io.BytesIO(served.content)).size == (512, 512)


# ---- refusals ----


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("content", "name", "content_type"),
    [
        (image_bytes("GIF"), "anim.gif", "image/gif"),
        (b"this is not an image, just some text\n", "evil.png", "image/png"),
        (image_bytes("PNG")[:60], "truncated.png", "image/png"),
        (image_bytes("BMP"), "bitmap.png", "image/png"),
    ],
    ids=["gif", "text-disguised-as-png", "truncated-png", "bmp-disguised-as-png"],
)
def test_anything_but_a_jpeg_or_png_is_refused_and_the_current_avatar_kept(
    uploader, member_only, content, name, content_type
):
    current = store_avatar(member_only, image_bytes("PNG"), "a" * 32)

    response = _upload(uploader, content, name, content_type)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "invalid_avatar"
    member_only.refresh_from_db()
    assert member_only.avatar.name == current
    assert avatar_storage().listdir(f"avatars/{member_only.id}")[1] == [current.rsplit("/", 1)[-1]]


@pytest.mark.django_db
def test_the_size_limit_is_inclusive(uploader, member_only, settings):
    content = image_bytes("PNG")
    settings.AVATAR_MAX_SIZE = len(content)
    assert _upload(uploader, content).status_code == status.HTTP_200_OK

    settings.AVATAR_MAX_SIZE = len(content) - 1
    response = _upload(uploader, content)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "avatar_too_large"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("size", "accepted"),
    [((100, 100), True), ((101, 100), False), ((300, 300), False)],
    ids=["at-the-limit", "over-the-limit-only-warned-by-pillow", "over-twice-the-limit"],
)
def test_more_pixels_than_pillow_allows_is_refused(uploader, member_only, monkeypatch, size, accepted):
    # A small file can declare a huge canvas; scale the limit down instead of building one.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100 * 100)

    response = _upload(uploader, image_bytes("PNG", size=size))

    if accepted:
        assert response.status_code == status.HTTP_200_OK
    else:
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "invalid_avatar"
        member_only.refresh_from_db()
        assert not member_only.avatar


# ---- the previous object ----


@pytest.mark.django_db
def test_replacing_deletes_the_previous_object_only_once_committed(
    uploader, member_only, django_capture_on_commit_callbacks
):
    previous = store_avatar(member_only, image_bytes("PNG"), "b" * 32)

    with django_capture_on_commit_callbacks() as callbacks:
        response = _upload(uploader, image_bytes("JPEG"), "new.jpg", "image/jpeg")
    member_only.refresh_from_db()

    assert response.status_code == status.HTTP_200_OK
    assert avatar_storage().exists(previous), "deleted before the transaction committed"
    for callback in callbacks:
        callback()
    assert not avatar_storage().exists(previous)
    assert avatar_storage().exists(member_only.avatar.name)


@pytest.mark.django_db
def test_clearing_deletes_the_object_once_committed(uploader, member_only, django_capture_on_commit_callbacks):
    previous = store_avatar(member_only, image_bytes("PNG"), "c" * 32)

    with django_capture_on_commit_callbacks(execute=True):
        response = uploader.delete(AVATAR_URL)

    assert response.status_code == status.HTTP_204_NO_CONTENT
    member_only.refresh_from_db()
    assert not member_only.avatar
    assert not avatar_storage().exists(previous)


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["replace", "clear"])
def test_a_failing_delete_of_the_previous_object_keeps_the_committed_change(
    uploader, member_only, mocker, django_capture_on_commit_callbacks, action
):
    previous = store_avatar(member_only, image_bytes("PNG"), "d" * 32)
    mocker.patch.object(avatar_storage(), "delete", side_effect=OSError("bucket unavailable"))

    with django_capture_on_commit_callbacks(execute=True):
        response = _upload(uploader, image_bytes("PNG")) if action == "replace" else uploader.delete(AVATAR_URL)

    assert response.status_code in (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT)
    member_only.refresh_from_db()
    assert member_only.avatar.name != previous
