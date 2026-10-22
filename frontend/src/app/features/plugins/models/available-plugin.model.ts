import { PluginAction } from './plugin-admin.model';

/** `maintenance`: the plugin, or the organization's install of it, is being updated; it can't be opened until then. */
export type AvailablePluginAvailability = 'ready' | 'maintenance';

/** A plugin the caller may open in the active organization (`GET /api/plugins/available/`). */
export interface AvailablePlugin {
    identifier: string;
    name: string;
    /** Same-origin public icon URL, for a plain `<img>`. */
    icon_url: string;
    /** `<scheme>://<identifier>.<plugins base domain>[:<port>]`: the only origin the plugin page is framed from. */
    frame_origin: string;
    /** Always contains `read`. */
    permissions: PluginAction[];
    availability: AvailablePluginAvailability;
    /** The plugin is served from a developer's machine (development mode); members never see where. */
    development: boolean;
}
