"""Wraps user code into the source actually run inside the sandbox subprocess.

Builds the preamble that injects globals and secrets, calls the entrypoint, writes
its return value to the result file, and translates a network denial into a clear
message. This is mechanism, not policy: the real network/filesystem boundary is the
kernel-enforced seccomp/Landlock filter the launcher installs before this source
runs. Pure -- it only formats a string.
"""

from pathlib import Path
from typing import Any

__all__ = ["wrap_code"]


def wrap_code(
    *,
    code: str,
    result_file_path: Path,
    entrypoint: str,
    func_kwargs: dict[str, Any],
    global_kwargs: dict[str, Any] | None = None,
    storage_mutations_path: Path | None = None,
) -> str:
    global_kwargs = global_kwargs or {}
    code_lines = code.split("\n")
    code_lines = ["    " + line for line in code_lines]
    code = "\n".join(code_lines)
    wrapped_code = f"""
import errno
import os
import socket
import sys
import json

# Message-quality aid only, NOT a security control -- the real boundary is
# the kernel-enforced seccomp/Landlock filter launcher.py installs before
# this interpreter starts. SANDBOX_NETWORK_BLOCKED mirrors that real state
# ("all" / "storage_only"), set by the launch step.
__sys_network_block_mode = os.environ.get("SANDBOX_NETWORK_BLOCKED")


def __sys_network_block_message():
    if __sys_network_block_mode == "storage_only":
        return (
            "Network access denied: the sandbox network policy allows outbound "
            "network access only to the storage endpoint."
        )
    return "Network access denied: the sandbox network policy blocks all outbound network access."


# Some in-sandbox tools catch socket.gaierror themselves and format it into
# their own returned string, e.g. f"could not resolve host {{host}}: {{e}}",
# so it never reaches __sys_is_network_denial() below. Monkeypatching
# getaddrinfo makes the exception itself carry the policy message, so every
# consumer that does str(e) gets it for free. Message-quality aid only, not a
# security control. Gated on "all" only: under storage_only, DNS genuinely
# still works over UDP, so a gaierror there is a real failure, not this.
if __sys_network_block_mode == "all":
    __sys_real_getaddrinfo = socket.getaddrinfo

    def __sys_getaddrinfo(*args, **kwargs):
        try:
            return __sys_real_getaddrinfo(*args, **kwargs)
        except socket.gaierror as exc:
            raise socket.gaierror(exc.errno, __sys_network_block_message()) from None

    socket.getaddrinfo = __sys_getaddrinfo


def __sys_is_network_denial(exc):
    # Partial coverage, deliberately: the raw OSError/PermissionError from
    # seccomp/Landlock, socket.gaierror (DNS), and one level of unwrap for
    # urllib's URLError (.reason). Other wrapper exceptions (requests, httpx,
    # botocore, ...) fall through to the generic str(e) message below.
    if isinstance(exc, socket.gaierror):
        # Only a full block guarantees DNS itself fails; under storage_only,
        # Landlock leaves DNS reachable, so a gaierror there is real and must
        # not be misreported as a policy denial.
        return __sys_network_block_mode == "all"
    return isinstance(exc, OSError) and exc.errno == errno.EACCES and exc.filename is None


try:
    from dotdict import DotDict, DotObject, DotList
    from epicstaff_secrets import get_secret
    for k, v in {global_kwargs}.items():
        globals()[k] = v

{code}

    __sys_dot_kwargs = DotDict({func_kwargs})

    sys_result_variable = {entrypoint}(**__sys_dot_kwargs)
    with open(r'{result_file_path.as_posix()}', 'w', encoding='utf-8') as file:
        file.write(json.dumps(sys_result_variable))
except OSError as e:
    __sys_candidate = getattr(e, "reason", e)
    if __sys_network_block_mode and __sys_is_network_denial(__sys_candidate):
        print(__sys_network_block_message(), file=sys.stderr)
    else:
        print(str(e), file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(str(e), file=sys.stderr)
    sys.exit(1)
"""

    if storage_mutations_path:
        wrapped_code += f"""
try:
    from epicstaff_storage.storage import get_mutations as __es_get_muts
    import json as __es_json
    __es_muts = __es_get_muts()
    if __es_muts:
        with open(r'{storage_mutations_path.as_posix()}', 'w') as __es_mf:
            __es_json.dump(__es_muts, __es_mf)
except Exception:
    pass
"""

    wrapped_code += "sys.exit(0)\n"

    return wrapped_code
