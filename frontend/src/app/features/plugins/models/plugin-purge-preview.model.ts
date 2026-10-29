import { PluginGrantState, PluginOrganizationRef, PluginState } from './plugin-admin.model';
import {
    PluginDefaultModelReference,
    PluginOwnedResourceCount,
    PluginPreviewFlow,
    PluginPreviewList,
    PluginPreviewSession,
} from './plugin-suspend-preview.model';

/**
 * What happens to the plugin's own data for an organization: `deleted_by_plugin` (its backend has an organization
 * removed hook), `kept_until_plugin_deleted` (a backend without one), `none` (no backend).
 */
export type PluginDataFate = 'deleted_by_plugin' | 'kept_until_plugin_deleted' | 'none';

/**
 * What deleting a grant's data removes in its organization (`GET …/grants/{id}/purge-preview/`): what the plugin owns
 * there, the organization's flows and the plugin's own flows that use it, the running sessions that are stopped, the
 * default-model settings that are cleared, and what becomes of the plugin's own data.
 */
export interface PluginGrantPurgePreview {
    grant: { id: number; state: PluginGrantState };
    plugin: { identifier: string; name: string };
    organization: PluginOrganizationRef;
    /** Typed exactly to confirm: `purge-<identifier>-<organization name>`. */
    verification_phrase: string;
    /** Sorted by label. */
    owned_resources: PluginOwnedResourceCount[];
    flows: { organization: PluginPreviewList<PluginPreviewFlow>; plugin: PluginPreviewList<PluginPreviewFlow> };
    /** Empty once the grant is suspended. */
    running_sessions: PluginPreviewList<PluginPreviewSession>;
    default_models: PluginDefaultModelReference[];
    plugin_data: PluginDataFate;
}

/** One organization a plugin is granted to, as uninstalling or deleting the plugin affects it. */
export interface PluginPurgePreviewOrganization {
    grant_id: number;
    organization: PluginOrganizationRef;
    state: PluginGrantState;
    owned_resource_count: number;
}

/**
 * What uninstalling or deleting a plugin affects (`GET …/purge-preview/`): the organizations it is granted to, what it
 * owns across them, the data removals still open, its database, and what EpicStaff deletes of it.
 */
export interface PluginPurgePreview {
    plugin: { identifier: string; name: string; state: PluginState };
    /** Typed exactly to confirm a deletion: `purge-<identifier>`. */
    verification_phrase: string;
    /** `purge_after` while uninstalled, else now plus the grace period. */
    data_kept_until: string;
    organizations: PluginPreviewList<PluginPurgePreviewOrganization>;
    /** Every organization together, sorted by label. */
    owned_resources: PluginOwnedResourceCount[];
    /** Data removals pending, running or failed, those of deleted organizations included. */
    data_removals_open: number;
    has_org_removed_hook: boolean;
    database: { name: string; size_bytes: number | null } | null;
    has_backend: boolean;
    has_spa: boolean;
    package_count: number;
}
