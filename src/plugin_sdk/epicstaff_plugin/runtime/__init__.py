"""What EpicStaff hands a running plugin process: settings, addresses and signing keys."""

from epicstaff_plugin.runtime.runtime_config import (
    RuntimeConfig,
    RuntimeConfigError,
    runtime_config,
)

__all__ = ["RuntimeConfig", "RuntimeConfigError", "runtime_config"]
