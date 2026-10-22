import { readStackFile, type StackFile } from './stack-file.ts';

/** The running stack the browser checks use: the environment first, then the stack file `npm run e2e:seed` wrote. */
export interface Organization {
    id: number;
    name: string;
}

/** Read once, on first use; `null` when there is none. */
let stackFile: StackFile | null | undefined;

function seeded(): StackFile | null {
    if (stackFile === undefined) stackFile = readStackFile();
    return stackFile;
}

function optional(name: string, fromStack: (stack: StackFile) => string, fallback: string): string {
    const stack = seeded();
    return process.env[name] || (stack ? fromStack(stack) : fallback);
}

/** Read lazily, so `playwright test --list` works without the secrets. */
function required(name: string, fromStack: (stack: StackFile) => string | number): string {
    const value = process.env[name];
    if (value) return value;
    const stack = seeded();
    if (stack) return String(fromStack(stack));
    throw new Error(`Set ${name}, or run npm run e2e:seed, to run the browser checks against a running stack.`);
}

export const STACK = {
    /** EpicStaff's origin, without a trailing slash. */
    epicstaffUrl: optional('E2E_EPICSTAFF_URL', (stack) => stack.epicstaff_url, 'http://epicstaff.localhost'),
    plugin: optional('E2E_PLUGIN', (stack) => stack.plugin, 'weather'),
    /** The plugin's own origin. */
    pluginUrl: optional('E2E_PLUGIN_URL', (stack) => stack.plugin_url, 'http://weather.plugins.epicstaff.localhost'),
    /** A Member of organizations A and C (the seed's Ada), with Weather's Member permissions in both. */
    get email(): string {
        return required('E2E_EMAIL', (stack) => stack.people.ada.email);
    },
    get password(): string {
        return required('E2E_PASSWORD', (stack) => stack.people.ada.password);
    },
    get orgA(): Organization {
        return {
            id: Number(required('E2E_ORG_A_ID', (stack) => stack.organizations.a.id)),
            name: required('E2E_ORG_A_NAME', (stack) => stack.organizations.a.name),
        };
    },
    get orgC(): Organization {
        return {
            id: Number(required('E2E_ORG_C_ID', (stack) => stack.organizations.c.id)),
            name: required('E2E_ORG_C_NAME', (stack) => stack.organizations.c.name),
        };
    },
};
