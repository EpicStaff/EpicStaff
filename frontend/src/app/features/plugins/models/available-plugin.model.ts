import { PluginAction } from './plugin-admin.model';

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
}
