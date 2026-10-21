from storages.backends.s3 import S3Storage


class AvatarStorage(S3Storage):
    """S3 storage for user avatars, served only through the avatar endpoint.

    The bucket is private and its endpoint is internal, so a storage URL would
    either be unreachable from the browser or leak a presigned link. Every avatar
    URL comes from `build_avatar_url` instead.
    """

    def url(self, name, *args, **kwargs):
        raise NotImplementedError("Avatar URLs come from build_avatar_url")
