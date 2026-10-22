import base64
import hashlib
import time
from pathlib import PurePosixPath

from django.conf import settings
from storages.backends.s3 import S3Storage

SECONDS_PER_DAY = 86400
CONTENT_TYPE_BY_EXTENSION = {".jpg": "image/jpeg", ".png": "image/png"}


class AvatarStorage(S3Storage):
    """S3 storage for user avatars, served by nginx only through a signed, expiring URL.

    nginx maps `/media/avatars/` to `<bucket>/system/avatars/` and serves it only when
    `secure_link` accepts the `e` (expiry) and `s` (signature) query arguments, so only
    a caller who got the URL from an authenticated API response can open the image.
    The URL is a bearer link, not bound to a user: anyone holding it can open the image
    until it expires.
    """

    def get_object_parameters(self, name):
        # The stored type comes from the key's extension, which the server picked from the
        # validated image format, never from the client's multipart Content-Type: a PNG
        # with HTML appended, uploaded as text/html, would otherwise be served as HTML.
        # django-storages only falls back to the client's type when ContentType is unset.
        extension = PurePosixPath(name).suffix
        return {
            **super().get_object_parameters(name),
            "ContentType": CONTENT_TYPE_BY_EXTENSION.get(extension, "application/octet-stream"),
        }

    def url(self, name, *args, **kwargs):
        path = f"/media/{name}"
        # Expires at the end of the next UTC day: the URL stays the same for a whole day,
        # so the browser cache keeps working, and it is always valid for at least 24 h.
        expires = (int(time.time()) // SECONDS_PER_DAY + 2) * SECONDS_PER_DAY
        # The same string nginx's secure_link_md5 hashes: "$secure_link_expires$uri <secret>".
        digest = hashlib.md5(
            f"{expires}{path} {settings.AVATAR_URL_SIGNING_SECRET}".encode()
        ).digest()
        signature = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        return f"{path}?e={expires}&s={signature}"
