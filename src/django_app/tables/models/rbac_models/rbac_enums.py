from enum import IntFlag

from django.db import models


class ResourceType(models.TextChoices):
    ORGANIZATIONS = "organizations", "Organizations"
    ROLES = "roles", "Roles"
    MEMBERSHIPS = "memberships", "Members"
    API_KEYS = "api_keys", "API Keys"
    FLOWS = "flows", "Flows"
    AGENTS = "agents", "Agents"
    TOOLS = "tools", "Tools"
    KNOWLEDGE_SOURCES = "knowledge_sources", "Knowledge Sources"
    FILES = "files", "Files"
    PROJECTS = "projects", "Projects"
    LLM_CONFIGS = "llm_configs", "LLM Configs"
    SECRETS = "secrets", "Secrets"
    VOICE = "voice", "Voice"
    SURFACES = "surfaces", "Surfaces"


class Permission(IntFlag):
    CREATE = 1
    READ = 2
    UPDATE = 4
    DELETE = 8
    EXPORT = 16
    # 32 retired (was DOWNLOAD; folded into EXPORT — same logic).
    USE = 64
    LIST = 128


class BuiltInRole:
    SUPERADMIN = "Superadmin"
    ORG_ADMIN = "Org Admin"
    MEMBER = "Member"
    VIEWER = "Viewer"
