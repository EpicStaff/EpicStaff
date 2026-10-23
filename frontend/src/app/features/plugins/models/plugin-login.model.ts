import { PluginOrganizationRef } from './plugin-admin.model';

/** `GET /api/plugins/{identifier}/login-organizations/`: where the caller may sign in to a plugin. */
export interface PluginLoginOrganizations {
    plugin: {
        identifier: string;
        name: string;
        /** Same-origin public icon URL, for a plain `<img>`. */
        icon_url: string;
    };
    /** The caller's own organizations where they may open the plugin, sorted by name; `[]` when there are none. */
    organizations: PluginOrganizationRef[];
}
