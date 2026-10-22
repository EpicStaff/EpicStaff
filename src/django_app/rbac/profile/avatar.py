import io
import threading

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError

from rbac.exceptions import (
    AvatarTooLargeError,
    InvalidAvatarError,
)

# Largest side of a stored avatar: covers the biggest rendering on a high-DPI screen.
AVATAR_MAX_DIMENSION = 512
# Largest image decoded to build an avatar, checked after draft(): a PNG is decoded
# in full, and a few hundred KB of it can declare ~89 MP.
AVATAR_MAX_DECODED_PIXELS = 2048 * 2048
# Largest progressive JPEG: draft() does not shrink its decoder's buffers, which hold
# every coefficient at full size. A baseline JPEG needs no such cap: draft() makes
# its decoder scale down by up to 8x while reading, and the decoded cap still applies.
AVATAR_MAX_PROGRESSIVE_PIXELS = 16_000_000
# Within the caps above one decode still takes up to ~55 MB: at most this many run at
# once per process, so parallel uploads queue instead of stacking that memory.
_DECODE_SLOTS = threading.BoundedSemaphore(2)

# Every Pillow failure on a hostile or broken upload: a bad header, truncated data,
# a broken PNG chunk (SyntaxError), an unsupported mode, or more pixels than
# Image.MAX_IMAGE_PIXELS.
_IMAGE_ERRORS = (
    UnidentifiedImageError,
    OSError,
    ValueError,
    SyntaxError,
    Image.DecompressionBombError,
)
# 16/32-bit integer and float pixels: converting them to 8 bits clips most values to white.
_HIGH_DEPTH_MODES = ("I", "F")


def build_avatar_url(user, request) -> str | None:
    """Return the URL of the user's avatar, or None when unset or unresolvable.

    Absolute when a request is given, otherwise the storage-relative URL.
    """
    if not user.avatar:
        return None
    try:
        return (
            request.build_absolute_uri(user.avatar.url) if request is not None else user.avatar.url
        )
    except ValueError:
        return None


class UserAvatarStorageService:
    """Re-encode, store, and atomically replace a user's avatar.

    An upload is decoded and re-encoded, never stored as sent: the stored file is
    at most AVATAR_MAX_DIMENSION on a side, upright, and free of EXIF (with GPS) and
    comments; only its colour profile is kept. The previous file is deleted on commit, so storage never
    gets ahead of the database.
    """

    _FORMAT_TO_EXT = {
        "JPEG": ".jpg",
        "PNG": ".png",
    }

    def store(self, user, uploaded_file: UploadedFile):
        """Replace the user's avatar with a normalized copy of `uploaded_file`.

        Raises:
            AvatarTooLargeError: The upload exceeds AVATAR_MAX_SIZE.
            InvalidAvatarError: Not a decodable image in an allowed format, or too many pixels.
        """
        content, format_name = self._normalize(uploaded_file)

        with transaction.atomic():
            old_storage = user.avatar.storage if user.avatar else None
            old_name = user.avatar.name if user.avatar else None

            # The model's callable upload_to renames the file to
            # avatars/<user_id>/<uuid_hex>.<ext>; this name only carries the extension.
            user.avatar.save(f"avatar{self._FORMAT_TO_EXT[format_name]}", content, save=False)
            user.save(update_fields=["avatar", "updated_at"])

            if old_name:
                # robust: the delete is a bucket call; its failure is logged and
                # never turns the committed avatar change into an error response.
                transaction.on_commit(lambda: old_storage.delete(old_name), robust=True)

        return user

    def clear(self, user):
        if not user.avatar:
            return user
        with transaction.atomic():
            old_storage = user.avatar.storage
            old_name = user.avatar.name
            user.avatar = None
            user.save(update_fields=["avatar", "updated_at"])
            # robust: see store().
            transaction.on_commit(lambda: old_storage.delete(old_name), robust=True)
        return user

    # ---- private ----

    def _normalize(self, uploaded_file: UploadedFile) -> tuple[ContentFile, str]:
        size = getattr(uploaded_file, "size", None)
        if size is None or size > settings.AVATAR_MAX_SIZE:
            max_mb = settings.AVATAR_MAX_SIZE // (1024 * 1024)
            raise AvatarTooLargeError(
                detail=f"Avatar file exceeds the maximum allowed size ({max_mb} MB)."
            )

        # No verify() pass: a broken image fails while it is decoded below, and
        # what gets stored is the re-encoded pixels, never the uploaded bytes.
        try:
            uploaded_file.seek(0)
            with _DECODE_SLOTS, Image.open(uploaded_file) as source:
                format_name = (source.format or "").upper()
                # A phone JPEG carrying a depth or gain map: its first frame is a plain JPEG.
                if format_name == "MPO":
                    format_name = "JPEG"
                # Bounded by _FORMAT_TO_EXT too: only formats this service can
                # re-encode are stored, whatever the setting says.
                if (
                    format_name not in settings.AVATAR_ALLOWED_FORMATS
                    or format_name not in self._FORMAT_TO_EXT
                ):
                    raise InvalidAvatarError()
                if (
                    source.info.get("progressive")
                    and source.width * source.height > AVATAR_MAX_PROGRESSIVE_PIXELS
                ):
                    raise InvalidAvatarError()
                if source.mode.startswith(_HIGH_DEPTH_MODES):
                    raise InvalidAvatarError()
                # No-op for PNG.
                source.draft(None, (AVATAR_MAX_DIMENSION, AVATAR_MAX_DIMENSION))
                if source.width * source.height > AVATAR_MAX_DECODED_PIXELS:
                    raise InvalidAvatarError()
                # Shrink before rotating, so the rotation copies a small image; the
                # mode changes first because a palette shrinks badly.
                image = self._to_encodable_mode(source, format_name)
                image.thumbnail((AVATAR_MAX_DIMENSION, AVATAR_MAX_DIMENSION))
                image = ImageOps.exif_transpose(image)
                # The colour profile is kept, or a Display P3 photo renders desaturated,
                # unless the conversion left its colour space (CMYK or grey to RGB).
                icc_profile = (
                    source.info.get("icc_profile") if image.mode[:3] == source.mode[:3] else None
                )
                # Encoders read EXIF and comments from `info`.
                image.info = {}
                output = io.BytesIO()
                if format_name == "JPEG":
                    image.save(
                        output, format="JPEG", quality=85, optimize=True, icc_profile=icc_profile
                    )
                else:
                    image.save(output, format="PNG", optimize=True, icc_profile=icc_profile)
        except _IMAGE_ERRORS as exc:
            raise InvalidAvatarError() from exc
        return ContentFile(output.getvalue()), format_name

    @staticmethod
    def _to_encodable_mode(image: Image.Image, format_name: str) -> Image.Image:
        # A palette resizes with nearest-neighbour only and keeps its transparency
        # in `info`, which is about to be cleared; RGB/RGBA carry colour and alpha
        # in the pixels. JPEG has no alpha, and browsers render CMYK JPEGs badly.
        if format_name == "JPEG":
            return image if image.mode in ("RGB", "L") else image.convert("RGB")
        has_alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
        target_mode = "RGBA" if has_alpha else "RGB"
        return image if image.mode == target_mode else image.convert(target_mode)
