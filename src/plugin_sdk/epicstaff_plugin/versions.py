"""Comparing plugin versions in SemVer 2.0 order, from a plugin's own code.

An upgrade hook gets the version its organization was last brought to in
`HookRequest.previous_version`, which may be several versions back. Compare it with the version
that changed what the hook sets up:

    from epicstaff_plugin.versions import is_newer

    if request.previous_version is None or is_newer("0.7.0", request.previous_version):
        await set_up_what_0_7_0_changed(epicstaff)

These are the functions of `epicstaff_plugin.contracts.versions`, the order EpicStaff uses to
decide whether an uploaded package is newer than the installed one.
"""

from epicstaff_plugin.contracts.versions import VersionKey, compare_versions, is_newer, version_key

__all__ = ["VersionKey", "compare_versions", "is_newer", "version_key"]
