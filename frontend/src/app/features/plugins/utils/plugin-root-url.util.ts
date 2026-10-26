/** `/plugins/<identifier>` and the rest of a plugin page address. */
const PLUGIN_PAGE_ADDRESS = /^\/plugins\/([^/?#;]+)/;

/**
 * The plugin's own root for an address of a plugin page (`/plugins/weather/forecast?city=Rome` → `/plugins/weather`),
 * else `null`. Used across an organization switch: the plugin is kept, its page path (data of the old organization) is
 * not.
 */
export function pluginRootUrl(url: string): string | null {
    const match = PLUGIN_PAGE_ADDRESS.exec(url);
    return match ? `/plugins/${match[1]}` : null;
}
