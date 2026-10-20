import traceback
from pathlib import Path


def describe_failure(error: BaseException) -> str:
    """Describe where `error` was raised, without any value it carried.

    Password-reset failures happen while the email address and the raw token
    are in scope, so the exception message and a traceback with locals can
    both hold them. The type and the location of the innermost frame cannot.
    The file is reduced to its basename so the logged line stays well under
    the 200-character cut of `utils.logger` even when the frame is deep in
    site-packages.

    Returns:
        `error_type=<name> at=<file>:<line> in <function>`, or `at=unknown`
        when the exception carries no traceback.
    """
    frames = traceback.extract_tb(error.__traceback__)
    if not frames:
        return f"error_type={type(error).__name__} at=unknown"
    frame = frames[-1]
    return (
        f"error_type={type(error).__name__} "
        f"at={Path(frame.filename).name}:{frame.lineno} in {frame.name}"
    )
