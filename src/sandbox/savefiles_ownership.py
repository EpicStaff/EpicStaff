"""TEMPORARY stopgap: lets sandboxuser write to the savefiles bind mount.

Docker creates a missing bind-mount directory as root:root 755, and the Landlock
jail only restricts access, so user code could not create anything in its own
working directory. Delete this module together with the savefiles feature once
users have moved to epicstaff_storage.
"""

import os
import stat
from pathlib import Path

from utils.logger import logger


def ensure_savefiles_writable(path: str | Path, uid: int, gid: int) -> None:
    """Chown the savefiles root to uid:gid unless uid already owns it. Never raises.

    Not recursive: existing files and subdirectories keep their owner. A symlink
    or a missing path is left alone with a warning, and so is a chown failure:
    user code that does not write to savefiles still works.
    """
    # Path() drops a trailing slash, which would make lstat follow a symlinked
    # root; absolute() matches jail.build_jail.
    savefiles_root = Path(path).absolute()
    try:
        root_stat = os.lstat(savefiles_root)
        if not stat.S_ISDIR(root_stat.st_mode):
            logger.warning(
                "Savefiles root {} is not a real directory (symlink or other file type); "
                "leaving its owner unchanged. User code may be unable to write to savefiles.",
                savefiles_root,
            )
            return
        if root_stat.st_uid == uid:
            return
        # follow_symlinks=False: if the root were swapped for a symlink after the
        # lstat above, only the link itself changes owner, never its target.
        os.chown(savefiles_root, uid, gid, follow_symlinks=False)
        logger.info(
            "Changed owner of savefiles root {} from uid {} to uid={} gid={}.",
            savefiles_root,
            root_stat.st_uid,
            uid,
            gid,
        )
    except OSError as error:
        logger.warning(
            "Could not give uid={} gid={} ownership of savefiles root {}: {}. "
            "User code may be unable to write to savefiles.",
            uid,
            gid,
            savefiles_root,
            error,
        )
