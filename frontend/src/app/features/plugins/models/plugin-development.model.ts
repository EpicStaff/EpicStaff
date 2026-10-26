import { PluginDevelopmentPorts, PluginUserRef } from './plugin-admin.model';

/** The only host development mode ever routes to; the SuperAdmin enters ports only. */
export const PLUGIN_DEVELOPMENT_HOST = 'host.docker.internal';

/** The ports a SuperAdmin stored for the plugin. */
export interface PluginDevelopmentTarget extends PluginDevelopmentPorts {
    updated_at: string;
    updated_by: PluginUserRef | null;
}

/** `GET /api/admin/plugins/{identifier}/development/`: the plugin's development state on this deployment. */
export interface PluginDevelopment {
    /** `PLUGINS_DEV_MODE` as EpicStaff reads it now. */
    development_mode: boolean;
    host: typeof PLUGIN_DEVELOPMENT_HOST;
    /** The IPv4 address the host resolves to in EpicStaff now; `null` when it does not resolve or the mode is off. */
    host_address: string | null;
    /** Where a development backend reaches EpicStaff's API, on the author's machine; `null` when the mode is off. */
    api_url: string | null;
    /** The current package has a backend. */
    can_use_backend: boolean;
    /** The current package has a page. */
    can_use_spa: boolean;
    /** The stored target, also while the mode is off (then it routes nothing). */
    target: PluginDevelopmentTarget | null;
    /** When the development keys still in use were issued; `null` when none is. */
    runtime_file_issued_at: string | null;
}

/** `PUT …/development/`: both ports, at least one of them set (Stop development removes the target). */
export type PluginDevelopmentUpdate = PluginDevelopmentPorts;
