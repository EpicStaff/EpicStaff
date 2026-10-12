"""Drop a single Linux capability from this process once it is no longer needed.

The sandbox container is granted CAP_NET_ADMIN for one reason: so the egress
firewall can be installed at startup (see `egress_firewall.apply`). After that,
nothing should be able to alter the firewall -- yet root-owned install-time code
(pip building a source distribution's setup.py / PEP 517 hooks) runs in this same
process tree and would otherwise still hold CAP_NET_ADMIN, enough to flush
iptables. `drop_net_admin` removes just that one capability from the thread's
effective, permitted and inheritable sets, leaving the capabilities the sandbox
still needs for the per-execution privilege drop
(CAP_SETUID/SETGID/CHOWN/DAC_OVERRIDE/FOWNER/KILL) untouched.

The bounding set is deliberately NOT touched here: PR_CAPBSET_DROP requires
CAP_SETPCAP, which this container intentionally does not grant, and the bounding
set only matters for an execve of a file-capability/setuid binary -- a vector
the container's `no-new-privileges:true` already closes. Clearing CAP_NET_ADMIN
from the permitted set is irreversible for this thread (a capability absent from
permitted cannot be raised back without CAP_SETPCAP), so once dropped, root pip
cannot regain it.

ctypes binding, matching the style of landlock.py / seccomp.py: libcap is not
assumed to be installed.
"""

import ctypes
import os

# <linux/capability.h>
_CAP_NET_ADMIN = 12
_LINUX_CAPABILITY_VERSION_3 = 0x20080522
_LINUX_CAPABILITY_U32S_3 = 2


class _CapUserHeader(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]


class _CapUserData(ctypes.Structure):
    _fields_ = [
        ("effective", ctypes.c_uint32),
        ("permitted", ctypes.c_uint32),
        ("inheritable", ctypes.c_uint32),
    ]


_libc = ctypes.CDLL(None, use_errno=True)
_libc.capget.argtypes = [ctypes.POINTER(_CapUserHeader), ctypes.POINTER(_CapUserData)]
_libc.capget.restype = ctypes.c_int
_libc.capset.argtypes = [ctypes.POINTER(_CapUserHeader), ctypes.POINTER(_CapUserData)]
_libc.capset.restype = ctypes.c_int


def _cap_index(cap: int) -> tuple[int, int]:
    """Return the (32-bit word, bit) position of a capability number."""
    return cap // 32, cap % 32


def drop_net_admin() -> None:
    """Remove CAP_NET_ADMIN from this thread's effective/permitted/inheritable sets.

    Call once, after `egress_firewall.apply` has succeeded. Clearing a bit from
    one's own capability sets needs no privilege, so this works whether or not
    the process is root; on a host where the capability is already absent it is a
    no-op that still returns cleanly.

    Raises:
        OSError: the capget or capset syscall failed.
    """
    word, bit = _cap_index(_CAP_NET_ADMIN)
    mask = 1 << bit

    header = _CapUserHeader(version=_LINUX_CAPABILITY_VERSION_3, pid=0)
    data = (_CapUserData * _LINUX_CAPABILITY_U32S_3)()

    if _libc.capget(ctypes.byref(header), data) != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, f"capget failed: {os.strerror(errno)}")

    data[word].effective &= ~mask
    data[word].permitted &= ~mask
    data[word].inheritable &= ~mask

    if _libc.capset(ctypes.byref(header), data) != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, f"capset failed: {os.strerror(errno)}")
