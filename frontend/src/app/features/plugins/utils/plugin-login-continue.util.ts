import {
    PLUGIN_AUTHORIZE_PARAMETERS,
    PLUGIN_LOGIN_CONTINUE_PATTERN,
    PLUGIN_LOGIN_PATHS,
} from '../constants/plugin-login-protocol.constants';
import { PLUGIN_IDENTIFIER_PATTERN } from './plugin-frame-url.util';

/** A checked `continue`: EpicStaff's own authorize request for one plugin, never anywhere else. */
export interface PluginLoginContinue {
    /** The authorize path and query, exactly as EpicStaff sent it. */
    readonly path: string;
    /** The plugin the person is signing in to. */
    readonly plugin: string;
    /** The sign-in's `state`, new for every sign-in a plugin page starts. */
    readonly state: string;
}

/**
 * Checks the `continue` parameter of `/plugin-login` and `/plugin-choose-org`. It must be the authorize path with a
 * plain query (`patterns.continue` of the login protocol, so never another path, origin, `//`, `..` or fragment), name
 * exactly one plugin and one `state`, and carry no `prompt` in any spelling: EpicStaff sends a person to these pages
 * only for an interactive sign-in. `null` for anything else; the caller then never follows it.
 */
export function parsePluginLoginContinue(value: string | null): PluginLoginContinue | null {
    if (value === null || !PLUGIN_LOGIN_CONTINUE_PATTERN.test(value)) return null;
    const query = authorizeQuery(value);
    const plugins = query.getAll(PLUGIN_AUTHORIZE_PARAMETERS.plugin);
    const plugin = plugins[0];
    if (plugins.length !== 1 || plugin === undefined || !PLUGIN_IDENTIFIER_PATTERN.test(plugin)) return null;
    const states = query.getAll(PLUGIN_AUTHORIZE_PARAMETERS.state);
    const state = states[0];
    if (states.length !== 1 || state === undefined || state === '') return null;
    if (query.has(PLUGIN_AUTHORIZE_PARAMETERS.prompt)) return null;
    return { path: value, plugin, state };
}

/** The authorize request with `org` set to the chosen organization, replacing any `org` it had. */
export function continueWithOrganization(target: PluginLoginContinue, orgId: number): string {
    const query = authorizeQuery(target.path);
    query.set(PLUGIN_AUTHORIZE_PARAMETERS.org, String(orgId));
    return `${PLUGIN_LOGIN_PATHS.authorize}?${query.toString()}`;
}

/** The decoded query of a `continue` that matched the pattern (which guarantees the authorize path and `?`). */
function authorizeQuery(path: string): URLSearchParams {
    return new URLSearchParams(path.slice(PLUGIN_LOGIN_PATHS.authorize.length + 1));
}
