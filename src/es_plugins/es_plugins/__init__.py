"""The EpicStaff plugin node: a root launcher (PID 1) and an unprivileged agent (UID 10000).

The launcher only spawns and kills processes under plugin UIDs, prepares per-plugin
directories and writes runtime files. The agent does everything else: it talks to
django_app, downloads and verifies packages, builds venvs and supervises the processes.
"""

# Reported to django_app as `agent_version`; a test keeps it equal to pyproject.toml's version.
AGENT_VERSION = "0.1.0"
