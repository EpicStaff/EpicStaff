import io
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlencode

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from PIL import Image, ImageOps, UnidentifiedImageError
from tables.models.user import User

from rbac.exceptions import (
    AvatarNotFoundError,
    AvatarTooLargeError,
    InvalidAvatarError,
)
from rbac.models import OrganizationUser

# Largest side of a stored avatar: covers the biggest rendering on a high-DPI screen.
AVATAR_MAX_DIMENSION = 512
# Largest image decoded to build an avatar: 64 MB as RGBA, far below Pillow's
# process-wide MAX_IMAGE_PIXELS (~89 MP, ~350 MB per copy).
AVATAR_MAX_DECODED_PIXELS = 4096 * 4096

_CONTENT_TYPE_BY_EXTENSION = {".jpg": "image/jpeg", ".png": "image/png"}
_FALLBACK_CONTENT_TYPE = "application/octet-stream"
# Every Pillow failure on a hostile or broken upload: a bad header, truncated data,
# an unsupported mode, or more pixels than Image.MAX_IMAGE_PIXELS.
_IMAGE_ERRORS = (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError)


def avatar_version(name: str) -> str:
    """Return the version token of a stored avatar: its random file stem, new on every upload."""
    return PurePosixPath(name).stem


def build_avatar_url(user) -> str | None:
    """Return the relative URL of the user's avatar endpoint, or None when unset.

    The `v` query parameter changes with every upload, so the browser may cache
    each URL forever and a new avatar is fetched as soon as a payload carries it.
    Reads no storage: rendering a list of users costs nothing per avatar.
    """
    if not user.avatar:
        return None
    path = reverse("user_avatar", kwargs={"user_id": user.pk})
    return f"{path}?{urlencode({'v': avatar_version(user.avatar.name)})}"


@dataclass(frozen=True)
class AvatarDescriptor:
    """The stored avatar a request resolved to, and how the response may be cached."""

    name: str
    etag: str
    immutable: bool

    @property
    def content_type(self) -> str:
        """The type to serve: the upload service only ever writes `.jpg` and `.png` keys."""
        extension = PurePosixPath(self.name).suffix.lower()
        return _CONTENT_TYPE_BY_EXTENSION.get(extension, _FALLBACK_CONTENT_TYPE)


class UserAvatarReadService:
    """Decide whether a caller may see a user's avatar, and read it.

    A caller sees their own avatar, any avatar when superadmin, a superadmin's
    avatar, and the avatar of anyone sharing an active organization with them. Every refusal is the same
    AvatarNotFoundError, raised before any avatar state is read, so the endpoint
    cannot be used to probe which users exist or have an avatar.
    """

    def resolve(self, requester, user_id: int, version: str | None) -> AvatarDescriptor:
        """Find the avatar `requester` asked for.

        Args:
            version: The `v` the URL was built with. A stale one is refused, so a
                cached-forever URL never serves a newer image; None asks for the
                current avatar, which the caller must then revalidate.

        Raises:
            AvatarNotFoundError: Not visible, no avatar, or a stale version.
        """
        if not self._can_view(requester, user_id):
            raise AvatarNotFoundError()
        user = User.objects.filter(pk=user_id).only("id", "avatar").first()
        if user is None or not user.avatar:
            raise AvatarNotFoundError()
        current_version = avatar_version(user.avatar.name)
        if version is not None and version != current_version:
            raise AvatarNotFoundError()
        return AvatarDescriptor(
            name=user.avatar.name,
            etag=f'"{current_version}"',
            immutable=version is not None,
        )

    def read(self, descriptor: AvatarDescriptor) -> bytes:
        """Return the resolved avatar's bytes; a stored avatar is at most a few hundred KB.

        Raises:
            AvatarNotFoundError: The row names an object the bucket does not hold.
        """
        storage = User._meta.get_field("avatar").storage
        try:
            with storage.open(descriptor.name, "rb") as stored:
                return stored.read()
        except FileNotFoundError as error:
            raise AvatarNotFoundError() from error

    @staticmethod
    def _can_view(requester, target_user_id: int) -> bool:
        if getattr(requester, "is_superadmin", False):
            return True
        requester_id = getattr(requester, "pk", None)
        if requester_id is None:
            return False
        if requester_id == target_user_id:
            return True
        # Filtering the requester's side on an active org covers the target too:
        # both memberships point at the same organization row.
        requester_org_ids = OrganizationUser.objects.filter(
            user_id=requester_id, org__is_active=True
        ).values("org_id")
        # A superadmin holds no memberships yet authors content inside every
        # organization, so their avatar is visible to any signed-in user.
        return User.objects.filter(
            Q(is_superadmin=True) | Q(organization_memberships__org_id__in=requester_org_ids),
            pk=target_user_id,
        ).exists()


class UserAvatarStorageService:
    """Validate, normalize, store, and atomically replace a user's avatar.

    Four responsibilities, isolated for testability:
      1. Validate the upload (size gate, real-image Pillow verify,
         format whitelist).
      2. Re-encode it: apply the EXIF orientation, shrink it to fit
         AVATAR_MAX_DIMENSION and drop every metadata block (EXIF with GPS,
         ICC, comments), so what is stored is a small, clean image.
      3. Write the result to storage via Django's ImageField machinery
         with the model's callable upload_to.
      4. Schedule deletion of the previous file via transaction.on_commit
         so storage state can never get ahead of DB state.
    """

    _FORMAT_TO_EXT = {
        "JPEG": ".jpg",
        "PNG": ".png",
    }

    def store(self, user, uploaded_file: UploadedFile):
        upload_bytes, format_name = self._validate(uploaded_file)
        ext = self._FORMAT_TO_EXT[format_name]
        normalized = ContentFile(self._reencode(upload_bytes, format_name))

        with transaction.atomic():
            old_storage = user.avatar.storage if user.avatar else None
            old_name = user.avatar.name if user.avatar else None

            # The model's callable upload_to renames the file to
            # avatars/<user_id>/<uuid_hex>.<ext>. We pass an arbitrary
            # placeholder name here just to carry the extension through.
            new_filename = f"avatar{ext}"
            user.avatar.save(new_filename, normalized, save=False)
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

    def _validate(self, uploaded_file: UploadedFile) -> tuple[bytes, str]:
        # 1. size gate — cheapest check first.
        size = getattr(uploaded_file, "size", None)
        if size is None or size > settings.AVATAR_MAX_SIZE:
            max_mb = settings.AVATAR_MAX_SIZE // (1024 * 1024)
            raise AvatarTooLargeError(
                detail=(f"Avatar file exceeds the maximum allowed size ({max_mb} MB).")
            )

        # 2. Pillow real-image verify. verify() consumes the file pointer
        #    and only validates the header; we then re-open to read the
        #    format. Both passes operate on an in-memory copy, which the
        #    re-encode step decodes once more.
        try:
            uploaded_file.seek(0)
            upload_bytes = uploaded_file.read()
        except Exception as exc:
            raise InvalidAvatarError() from exc

        try:
            with Image.open(io.BytesIO(upload_bytes)) as img:
                img.verify()
            with Image.open(io.BytesIO(upload_bytes)) as img:
                format_name = (img.format or "").upper()
        except _IMAGE_ERRORS as exc:
            raise InvalidAvatarError() from exc

        # 3. format whitelist. Also bounded by _FORMAT_TO_EXT: only formats
        #    this service can re-encode are stored, whatever the setting says.
        if (
            format_name not in settings.AVATAR_ALLOWED_FORMATS
            or format_name not in self._FORMAT_TO_EXT
        ):
            raise InvalidAvatarError()

        return upload_bytes, format_name

    def _reencode(self, upload_bytes: bytes, format_name: str) -> bytes:
        try:
            with Image.open(io.BytesIO(upload_bytes)) as source:
                # Lets the JPEG decoder scale down by up to 8x while decoding, so a
                # phone photo never sits in memory at full size; no-op for PNG.
                source.draft(None, (AVATAR_MAX_DIMENSION, AVATAR_MAX_DIMENSION))
                # Checked on the size the decoder will produce: a PNG is always
                # decoded in full, and a few hundred KB can declare ~89 MP.
                if source.width * source.height > AVATAR_MAX_DECODED_PIXELS:
                    raise InvalidAvatarError()
                # Shrink before rotating, so the rotation copies a small image, not a
                # full-size one; the mode changes first because a palette shrinks badly.
                image = self._to_encodable_mode(source, format_name)
                image.thumbnail((AVATAR_MAX_DIMENSION, AVATAR_MAX_DIMENSION))
                image = ImageOps.exif_transpose(image)
                # Encoders read ICC profiles, comments and EXIF from `info`;
                # the converted image keeps none of them.
                image.info = {}
                output = io.BytesIO()
                if format_name == "JPEG":
                    image.save(output, format="JPEG", quality=85, optimize=True)
                else:
                    image.save(output, format="PNG", optimize=True)
        except _IMAGE_ERRORS as exc:
            raise InvalidAvatarError() from exc
        return output.getvalue()

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
