from django.db import models


class PluginState(models.TextChoices):
    UPLOADED = "uploaded"
    PROVISIONING = "provisioning"
    RUNNING = "running"
    FAILED = "failed"
    MAINTENANCE = "maintenance"
    UNINSTALLING = "uninstalling"
    PURGING = "purging"


class Trust(models.TextChoices):
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


class SignatureStatus(models.TextChoices):
    VALID = "valid"
    ABSENT = "absent"
    UNKNOWN_KEY = "unknown_key"


class ReviewState(models.TextChoices):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class GrantState(models.TextChoices):
    GRANTING = "granting"
    ACTIVE = "active"
    INSTALL_FAILED = "install_failed"
    UPGRADING = "upgrading"
    UPGRADE_FAILED = "upgrade_failed"
    SUSPENDED = "suspended"
    PURGING = "purging"


class SuspensionCause(models.TextChoices):
    """Why a grant is suspended: on its own, or because its plugin was uninstalled.

    A reinstall resumes only the grants the uninstall suspended.
    """

    GRANT = "grant"
    UNINSTALL = "uninstall"


class PlacementObservedState(models.TextChoices):
    UNKNOWN = "unknown"
    DOWNLOADING = "downloading"
    BUILDING = "building"
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"


class PlacementHealth(models.TextChoices):
    OK = "ok"
    FAILING = "failing"
    UNKNOWN = "unknown"


class PlacementRemovalState(models.TextChoices):
    """How the node's removal of a placement goes, as it last reported it."""

    REMOVING = "removing"
    FAILED = "failed"


class PluginDatabaseState(models.TextChoices):
    PENDING = "pending"
    PROVISIONING = "provisioning"
    READY = "ready"
    FAILED = "failed"


class UpgradeStage(models.TextChoices):
    """How far an upgrade has gone; the first three are open, the last three closed."""

    PREPARING = "preparing"
    MAINTENANCE = "maintenance"
    MIGRATING = "migrating"
    DONE = "done"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


class BackupReason(models.TextChoices):
    PRE_UPGRADE = "pre_upgrade"
    PRE_RESTORE = "pre_restore"


class RestoreState(models.TextChoices):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
