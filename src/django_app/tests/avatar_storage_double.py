"""In-memory stand-in for `rbac.profile.avatar_storage.AvatarStorage`.

tests/settings.py installs it as the `avatars` storage, so no test writes to the
bucket the dev stack uses. It mirrors the contract the avatar code relies on:
reading a missing object raises FileNotFoundError, deleting a missing object is not
an error, and `url()` refuses because every avatar URL comes from `build_avatar_url`.
`tests/storage_tests/test_avatar_storage_contract.py` runs one suite against both.
"""

from django.core.files.storage import InMemoryStorage


class InMemoryAvatarStorage(InMemoryStorage):
    def url(self, name, *args, **kwargs):
        raise NotImplementedError("Avatar URLs come from build_avatar_url")
