"""Trusted handoff between privilege drop and untrusted user code.

Runs as `sandboxuser` -- the parent process has already dropped privileges via
the `user=`/`group=` subprocess kwargs before spawning this. Everything in
this file executes *before* the ruleset is applied, while the filesystem is
still fully open to `sandboxuser`, so `launcher.py` and the `landlock`
package it imports are read from disk with no Landlock restriction in effect
and need no allowlist entry of their own. Applying the ruleset then
irreversibly confines this process (and everything `execv` replaces it with)
to the given jail; only code that runs after that point -- the untrusted job
code -- is confined.

argv: [launcher.py, <jail-json>, <venv-python>, <code-path>]
"""

import json
import os
import sys

import landlock


def main() -> None:
    jail_json, venv_python, code_path = sys.argv[1], sys.argv[2], sys.argv[3]
    jail = json.loads(jail_json)

    landlock.apply(
        rw_paths=jail["read_write"],
        ro_paths=jail["read_only"],
        roexec_paths=jail["read_exec"],
    )

    os.execv(venv_python, [venv_python, code_path])


if __name__ == "__main__":
    main()
