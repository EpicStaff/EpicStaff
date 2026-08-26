/**
 * Recommended (co-required) permissions for a given permission.
 *
 * Key   — `<resource>:<action>` that triggers the recommendation.
 * Value — list of `<resource>:<action>` keys recommended alongside it
 *         (typically read-level permissions on related resources).
 *
 * Kept as a plain frontend constant for now; can be migrated to a backend
 * endpoint later by mirroring the same shape.
 */
export const PERMISSION_RELATIONS: Record<string, string[]> = {
    'organizations:read': ['users:read', 'roles:read'],
    'organizations:create': ['organizations:read'], //superadmin only
    'organizations:update': ['organizations:read', 'users:read', 'roles:read'],
    'organizations:delete': ['organizations:read'], //superadmin only
    'organizations:export': [],

    'users:read': [],
    'users:create': ['users:read'],
    'users:update': ['users:read'],
    'users:delete': ['users:read'],
    'users:export': [],

    'roles:read': [],
    'roles:create': ['roles:read'],
    'roles:update': ['roles:read'],
    'roles:delete': ['roles:read'],
    'roles:export': [],

    'flows:read': ['projects:read', 'llm_configs:read'],
    'flows:create': ['flows:read'],
    'flows:update': ['flows:read', 'projects:read', 'llm_configs:read'],
    'flows:delete': ['flows:read'],
    'flows:export': ['flows:read'],

    'agents:read': ['knowledge_sources:read', 'tools:read', 'llm_configs:read'],
    'agents:create': ['agents:read', 'knowledge_sources:read', 'tools:read', 'llm_configs:read'],
    'agents:update': ['agents:read', 'knowledge_sources:read', 'tools:read', 'llm_configs:read'],
    'agents:delete': ['agents:read'],
    'agents:export': [],

    'tools:read': [],
    'tools:create': ['tools:read'],
    'tools:update': ['tools:read'],
    'tools:delete': ['tools:read'],
    'tools:export': ['tools:read'],

    'knowledge_sources:read': [],
    'knowledge_sources:create': ['knowledge_sources:read', 'llm_configs:read'],
    'knowledge_sources:update': ['knowledge_sources:read', 'llm_configs:read'],
    'knowledge_sources:delete': ['knowledge_sources:read'],
    'knowledge_sources:export': [],

    'files:read': [],
    'files:create': ['files:read'],
    'files:update': ['files:read'],
    'files:delete': ['files:read'],
    'files:export': ['files:read'],

    'projects:read': [],
    'projects:create': ['projects:read', 'flows:create', 'flows:update'],
    'projects:update': ['projects:read', 'flows:create', 'flows:update'],
    'projects:delete': ['projects:read'],
    'projects:export': ['projects:read'],

    'llm_configs:read': [],
    'llm_configs:create': ['llm_configs:read'],
    'llm_configs:update': ['llm_configs:read'],
    'llm_configs:delete': ['llm_configs:read'],
    'llm_configs:export': ['llm_configs:read'],

    'secrets:read': [],
    'secrets:create': ['secrets:read'],
    'secrets:use': ['secrets:read'],
    'secrets:delete': ['secrets:read'],
    'secrets:export': [],
};
