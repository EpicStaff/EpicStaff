/** The running stack the browser checks use, from the environment. */
export interface Organization {
    id: number;
    name: string;
}

function optional(name: string, fallback: string): string {
    return process.env[name] || fallback;
}

/** Read lazily, so `playwright test --list` works without the secrets. */
function required(name: string): string {
    const value = process.env[name];
    if (!value) throw new Error(`Set ${name} to run the browser checks against a running stack.`);
    return value;
}

export const STACK = {
    /** EpicStaff's origin, without a trailing slash. */
    epicstaffUrl: optional('E2E_EPICSTAFF_URL', 'http://epicstaff.localhost'),
    plugin: optional('E2E_PLUGIN', 'weather'),
    /** The plugin's own origin. */
    pluginUrl: optional('E2E_PLUGIN_URL', 'http://weather.plugins.epicstaff.localhost'),
    /** A member of organizations A and C, with View on the plugin in both. */
    get email(): string {
        return required('E2E_EMAIL');
    },
    get password(): string {
        return required('E2E_PASSWORD');
    },
    get orgA(): Organization {
        return { id: Number(required('E2E_ORG_A_ID')), name: required('E2E_ORG_A_NAME') };
    },
    get orgC(): Organization {
        return { id: Number(required('E2E_ORG_C_ID')), name: required('E2E_ORG_C_NAME') };
    },
};
