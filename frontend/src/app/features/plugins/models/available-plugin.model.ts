import { PluginAction } from './plugin-admin.model';

/** `maintenance`: the plugin, or the organization's install of it, is being updated; it can't be opened until then. */
export type AvailablePluginAvailability = 'ready' | 'maintenance';

/** One entry of a plugin's app menu (`spa.navigation` in its manifest); EpicStaff draws it in its own sidebar. */
export interface AvailablePluginNavigationItem {
    label: string;
    /** `/` or `/`-separated segments below the plugin's address: `/projects` opens `/plugins/<identifier>/projects`. */
    path: string;
    /** Same-origin public URL of the item's icon file (`/api/plugin-public/<identifier>/icons/<file>/?v=<version>`). */
    icon_url: string;
}

/** A plugin the caller may open in the active organization (`GET /api/plugins/available/`). */
export interface AvailablePlugin {
    identifier: string;
    name: string;
    /** The running version's description, shown under the name in the Apps list. */
    description: string;
    /** Same-origin public icon URL, for a plain `<img>`. */
    icon_url: string;
    /** `<scheme>://<identifier>.<plugins base domain>[:<port>]`: the only origin the plugin page is framed from. */
    frame_origin: string;
    /** Always contains `read`. */
    permissions: PluginAction[];
    availability: AvailablePluginAvailability;
    /** The plugin is served from a developer's machine (development mode); members never see where. */
    development: boolean;
    /** The running version's app menu, in the manifest's order; empty when the plugin declares none. */
    navigation: AvailablePluginNavigationItem[];
}
