from django.db import models


class PluginState(models.TextChoices):
    UPLOADED = "uploaded"
    PROVISIONING = "provisioning"
    RUNNING = "running"
    FAILED = "failed"
    MAINTENANCE = "maintenance"
    UNINSTALLING = "uninstalling"
    PURGING = "purging"
    REMOVED = "removed"


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
