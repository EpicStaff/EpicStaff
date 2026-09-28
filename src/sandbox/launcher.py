"""Trusted handoff between privilege drop and untrusted user code.

Runs as `sandboxuser` -- the parent process has already dropped privileges via
the `user=`/`group=` subprocess kwargs before spawning this. Everything in
this file executes *before* the ruleset is applied, while the filesystem is
still fully open to `sandboxuser`, so `launcher.py` and the `landlock`
package it imports are read from disk with no Landlock restriction in effect
and need no allowlist entry of their own. Applying the restrictions then
irreversibly confines this process (and everything `execv` replaces it with)
to the given plan; only code that runs after that point -- the untrusted job
code -- is confined.

argv: [launcher.py, <plan-json>, <venv-python>, <code-path>]

<plan-json> is:
    {
    "jail": {
        "read_write": [...],
        "read_only": [...],
        "read_exec": [...]
    } | null,
    "network": {"mode": "unrestricted"}
             | {"mode": "block_all"}
             | {"mode": "allow_ports", "ports": [int, ...]}
    }

`jail` is null when the kernel lacks Landlock but network blocking is still
requested -- the launcher then runs for seccomp alone. The "mode" field makes
the policy unrepresentable as two conflicting fields (there is no state where
both a full block and a port allowlist could be set at once).
"""

import json
import os
import sys

import landlock
import seccomp


def main() -> None:
    plan_json, venv_python, code_path = sys.argv[1], sys.argv[2], sys.argv[3]
    plan = json.loads(plan_json)

    # Any failure here must produce exactly one clear stderr line naming what
    # could not be applied, not a raw ctypes traceback: this process's stderr
    # becomes CodeResultData.stderr and is shown to the user or handed to an
    # LLM as a tool observation. It must also fail closed -- never execv into
    # the untrusted job code when a requested restriction could not be
    # applied.
    network = plan["network"]
    mode = network["mode"]
    allowed_tcp_ports = tuple(network["ports"]) if mode == "allow_ports" else None

    try:
        jail = plan["jail"]
        if jail is not None:
            landlock.apply(
                rw_paths=jail["read_write"],
                ro_paths=jail["read_only"],
                roexec_paths=jail["read_exec"],
                allowed_tcp_ports=allowed_tcp_ports,
            )
    except landlock.LandlockUnavailableError:
        print(
            "Sandbox isolation unavailable: Landlock filesystem jail could not be applied.",
            file=sys.stderr,
        )
        sys.exit(1)
    except landlock.LandlockNetworkUnavailableError:
        print(
            "Sandbox isolation unavailable: Landlock network restriction could not be applied.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        if mode == "block_all":
            seccomp.block_network()
    except seccomp.SeccompUnavailableError:
        print(
            "Sandbox isolation unavailable: network block (seccomp) could not be applied.",
            file=sys.stderr,
        )
        sys.exit(1)

    os.execv(venv_python, [venv_python, code_path])


if __name__ == "__main__":
    main()
