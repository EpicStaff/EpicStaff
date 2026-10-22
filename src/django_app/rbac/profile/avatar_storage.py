from storages.backends.s3 import S3Storage


class AvatarStorage(S3Storage):
    """S3 storage for user avatars, which are public and served by nginx.

    nginx maps `/media/avatars/` to `<bucket>/system/avatars/`, and the bucket policy
    lets anyone read that prefix only, so an avatar URL is an origin-relative path,
    never the internal storage endpoint or a presigned link.
    """

    def url(self, name, *args, **kwargs):
        return f"/media/{name}"
