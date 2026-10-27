from epicstaff_plugin.contracts.manifest import MAX_HOOK_TIMEOUT_SECONDS, PluginManifest


def hook_timeout_seconds(manifest: PluginManifest, kind: str) -> int:
    """The manifest's timeout for a hook kind, else the platform maximum for it."""
    timeouts = manifest.hooks.timeouts_seconds
    declared = getattr(timeouts, kind, None) if timeouts is not None else None
    return declared or MAX_HOOK_TIMEOUT_SECONDS[kind]
