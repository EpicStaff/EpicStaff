import io

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from PIL import Image, UnidentifiedImageError

from tables.services.rbac.rbac_exceptions import (
    AvatarTooLargeError,
    InvalidAvatarError,
)


class UserAvatarStorageService:
    """Validate, store, and atomically replace a user's avatar.

    Three responsibilities, isolated for testability:
      1. Validate the upload (size gate, real-image Pillow verify,
         format whitelist).
      2. Write the new file to storage via Django's ImageField machinery
         with the model's callable upload_to.
      3. Schedule deletion of the previous file via transaction.on_commit
         so storage state can never get ahead of DB state.
    """

    _FORMAT_TO_EXT = {
        "JPEG": ".jpg",
        "PNG": ".png",
    }

    def store(self, user, uploaded_file: UploadedFile):
        format_name = self._validate(uploaded_file)
        ext = self._FORMAT_TO_EXT.get(format_name, ".bin")
        # Rewind in case Pillow advanced the read pointer during verify.
        uploaded_file.seek(0)

        with transaction.atomic():
            old_storage = user.avatar.storage if user.avatar else None
            old_name = user.avatar.name if user.avatar else None

            # The model's callable upload_to renames the file to
            # avatars/<user_id>/<uuid_hex>.<ext>. We pass an arbitrary
            # placeholder name here just to carry the extension through.
            new_filename = f"avatar{ext}"
            user.avatar.save(new_filename, uploaded_file, save=False)
            user.save(update_fields=["avatar", "updated_at"])

            if old_name:
                transaction.on_commit(lambda: old_storage.delete(old_name))

        return user

    def clear(self, user):
        if not user.avatar:
            return user
        with transaction.atomic():
            old_storage = user.avatar.storage
            old_name = user.avatar.name
            user.avatar = None
            user.save(update_fields=["avatar", "updated_at"])
            transaction.on_commit(lambda: old_storage.delete(old_name))
        return user

    # ---- private ----

    def _validate(self, uploaded_file: UploadedFile) -> str:
        # 1. size gate — cheapest check first.
        size = getattr(uploaded_file, "size", None)
        if size is None or size > settings.AVATAR_MAX_SIZE:
            max_mb = settings.AVATAR_MAX_SIZE // (1024 * 1024)
            raise AvatarTooLargeError(
                detail=(
                    f"Avatar file exceeds the maximum allowed size " f"({max_mb} MB)."
                )
            )

        # 2. Pillow real-image verify. verify() consumes the file pointer
        #    and only validates the header; we then re-open to read the
        #    format. Both passes operate on an in-memory copy so the
        #    original upload buffer stays seekable for the writer.
        try:
            uploaded_file.seek(0)
            buf = io.BytesIO(uploaded_file.read())
        except Exception as exc:
            raise InvalidAvatarError() from exc

        try:
            with Image.open(buf) as img:
                img.verify()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise InvalidAvatarError() from exc

        try:
            buf.seek(0)
            with Image.open(buf) as img:
                format_name = (img.format or "").upper()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise InvalidAvatarError() from exc

        # 3. format whitelist.
        if format_name not in settings.AVATAR_ALLOWED_FORMATS:
            raise InvalidAvatarError()

        return format_name
