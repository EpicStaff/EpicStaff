"""Notices shown to plugin authors.

`OPEN_CODE_NOTICE` is the single source of the open-code notice: `epicstaff-plugin pack`
prints it, and the author documentation quotes it verbatim (a test keeps them equal).
"""

OPEN_CODE_NOTICE = (
    "Plugins are meant to be open code, and EpicStaff does not check that they are. "
    "Anyone who can reach a deployment can download a plugin's frontend files. "
    "Every administrator of every deployment that installs a plugin can read the whole "
    "package, including its backend code. EpicStaff is not responsible for that exposure."
)
