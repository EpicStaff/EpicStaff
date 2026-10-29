import { HttpErrorResponse } from '@angular/common/http';

import { PluginRolePermissionsUpdate } from '../models/plugin-role-permissions.model';
import { toPluginErrorView } from '../utils/plugin-error-message.util';

/** The codes the plugin Roles-matrix endpoints answer with, besides the generic ones. */
export type PluginRolePermissionErrorCode =
    | 'permission_escalation_denied'
    | 'built_in_role_immutable'
    | 'invalid_plugin_role_permissions'
    | 'role_not_found'
    | 'organization_not_found'
    | 'permission_denied';

/** What the Roles matrix says for each code of the plugin role-permission endpoints. */
export const PLUGIN_ROLE_PERMISSION_ERROR_MESSAGES: Readonly<Record<PluginRolePermissionErrorCode, string>> = {
    permission_escalation_denied: "You can't give plugin permissions you don't have yourself in this organization.",
    built_in_role_immutable:
        "Built-in roles get their plugin permissions from each plugin's defaults; they can't be changed.",
    invalid_plugin_role_permissions: "Some plugin permissions can't be saved.",
    role_not_found: 'This role no longer exists, or you can no longer see it.',
    organization_not_found: "That organization no longer exists, or you can't manage its roles.",
    permission_denied: "You don't have permission to change roles in this organization.",
};

/** `plugins[<index>]…` in an `errors[]` item's `loc`. */
const PLUGIN_INDEX_LOC = /^plugins\[(\d+)\]/;

function errorCode(error: unknown): unknown {
    if (!(error instanceof HttpErrorResponse)) return null;
    const body: unknown = error.error;
    return typeof body === 'object' && body !== null && 'code' in body ? body.code : null;
}

function isRoleErrorCode(code: unknown): code is PluginRolePermissionErrorCode {
    return typeof code === 'string' && Object.hasOwn(PLUGIN_ROLE_PERMISSION_ERROR_MESSAGES, code);
}

/**
 * The message for a failed plugin role-permission request: the matrix's own for its codes, with each refused plugin
 * named for `invalid_plugin_role_permissions` (the plugin sent at that index of `update`, by its name in `pluginNames`,
 * else its identifier); otherwise what the plugin endpoints say in general, else `fallback`.
 */
export function pluginRolePermissionErrorMessage(
    error: unknown,
    fallback: string,
    update?: PluginRolePermissionsUpdate,
    pluginNames?: ReadonlyMap<string, string>
): string {
    const view = toPluginErrorView(error, fallback);
    const code = errorCode(error);
    if (!isRoleErrorCode(code)) return view.message;
    const message = PLUGIN_ROLE_PERMISSION_ERROR_MESSAGES[code];
    if (code !== 'invalid_plugin_role_permissions' || view.items.length === 0) return message;
    const problems = view.items.map((item) => {
        const index = PLUGIN_INDEX_LOC.exec(item.loc)?.[1];
        const identifier = index === undefined ? undefined : update?.plugins[Number(index)]?.plugin_identifier;
        if (!identifier) return item.message;
        return `${pluginNames?.get(identifier) ?? identifier}: ${item.message}`;
    });
    return `${message} ${problems.join(' ')}`;
}
