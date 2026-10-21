import { inject, Injectable } from '@angular/core';
import { ActionCode } from '@shared/models';
import {
    RolePermissionExtension,
    RolePermissionExtensionError,
    RolePermissionExtensionGrant,
    RolePermissionExtensionRoleState,
    RolePermissionExtensionRow,
} from '@shared/services';
import { catchError, map, MonoTypeOperatorFunction, Observable, tap, throwError } from 'rxjs';

import { ActiveOrgService } from '../../../services/auth/active-org.service';
import { ConfigService } from '../../../services/config';
import { PluginAction } from '../models/plugin-admin.model';
import {
    PluginRolePermissionsResponse,
    PluginRolePermissionsUpdate,
    PluginRoleRow,
} from '../models/plugin-role-permissions.model';
import { AvailablePluginsStorageService } from '../services/available-plugins-storage.service';
import { PluginRolePermissionsApiService } from '../services/plugin-role-permissions-api.service';
import { pluginRolePermissionErrorMessage } from './plugin-role-permission-error.util';

/** The matrix group of the plugin rows. */
export const PLUGIN_ROLE_PERMISSION_GROUP_KEY = 'plugins';

/** A plugin row's code is this prefix and the plugin identifier: `plugin:weather`. */
export const PLUGIN_ROW_CODE_PREFIX = 'plugin:';

/** The matrix action for each plugin action. */
const ACTION_CODES: Readonly<Record<PluginAction, ActionCode>> = {
    read: ActionCode.Read,
    create: ActionCode.Create,
    update: ActionCode.Update,
    delete: ActionCode.Delete,
    export: ActionCode.Export,
    use: ActionCode.Use,
};

/** The plugin action for each matrix action a plugin can declare. */
const PLUGIN_ACTIONS: Readonly<Partial<Record<ActionCode, PluginAction>>> = {
    [ActionCode.Read]: 'read',
    [ActionCode.Create]: 'create',
    [ActionCode.Update]: 'update',
    [ActionCode.Delete]: 'delete',
    [ActionCode.Export]: 'export',
    [ActionCode.Use]: 'use',
};

/**
 * The plugin rows of the Roles matrix: one row per plugin running and granted in the organization, a cell per action
 * its manifest declares. Every action but View needs View: the matrix ticks View along with any other action, and
 * clearing View clears them.
 *
 * Saving a role's plugin rows refreshes the left bar's plugins when the role belongs to the active organization. The
 * extension is inactive while the plugin platform is off.
 */
@Injectable({ providedIn: 'root' })
export class PluginRolePermissionExtension implements RolePermissionExtension {
    readonly groupKey = PLUGIN_ROLE_PERMISSION_GROUP_KEY;
    readonly groupLabel = 'Plugins';
    readonly groupIconClass = 'ti ti-puzzle';

    /** Plugin names by identifier, from every row mapped so far: error messages name a plugin by them. */
    private readonly pluginNames = new Map<string, string>();

    private readonly api = inject(PluginRolePermissionsApiService);
    private readonly configService = inject(ConfigService);
    private readonly activeOrgService = inject(ActiveOrgService);
    private readonly availablePlugins = inject(AvailablePluginsStorageService);

    isActive(): boolean {
        return this.configService.isPluginsEnabled;
    }

    rowsForOrg(orgId: number): Observable<RolePermissionExtensionRow[]> {
        return this.api.getRows(orgId).pipe(
            tap((response) => this.rememberNames(response.rows)),
            map((response) => response.rows.map((row) => toExtensionRow(row))),
            failWithMessage("Couldn't load the plugin permissions.")
        );
    }

    roleState(roleId: number, orgId?: number): Observable<RolePermissionExtensionRoleState> {
        return this.api.getRolePermissions(roleId, orgId).pipe(
            tap((response) => this.rememberNames(response.rows)),
            map((response) => toRoleState(response)),
            failWithMessage("Couldn't load the role's plugin permissions.")
        );
    }

    saveRole(roleId: number, granted: RolePermissionExtensionGrant[]): Observable<RolePermissionExtensionRoleState> {
        const update = toUpdate(granted);
        return this.api.updateRolePermissions(roleId, update).pipe(
            tap((response) => {
                this.rememberNames(response.rows);
                this.refreshAvailablePlugins(response.role.org_id);
            }),
            map((response) => toRoleState(response)),
            failWithMessage("Couldn't save the plugin permissions.", update, this.pluginNames)
        );
    }

    private rememberNames(rows: readonly PluginRoleRow[]): void {
        for (const row of rows) this.pluginNames.set(row.plugin_identifier, row.name);
    }

    /** The left bar lists what the signed-in user's role allows, so a change to a role of the active org may move it. */
    private refreshAvailablePlugins(roleOrgId: number | null): void {
        if (roleOrgId === null || roleOrgId !== this.activeOrgService.activeOrgId()) return;
        this.availablePlugins.refresh().subscribe();
    }
}

/** The row's code for a plugin. */
export function pluginRowCode(identifier: string): string {
    return `${PLUGIN_ROW_CODE_PREFIX}${identifier}`;
}

function toExtensionRow(row: PluginRoleRow): RolePermissionExtensionRow {
    const hasRead = row.actions.some((cell) => cell.action === 'read');
    return {
        code: pluginRowCode(row.plugin_identifier),
        label: row.name,
        description: '',
        iconUrl: row.icon_url,
        actions: row.actions.map((cell) => ({
            action: ACTION_CODES[cell.action],
            description: cell.description,
            requires: hasRead && cell.action !== 'read' ? [ActionCode.Read] : [],
        })),
        grantable: row.ceiling.map((action) => ACTION_CODES[action]),
    };
}

function toRoleState(response: PluginRolePermissionsResponse): RolePermissionExtensionRoleState {
    return {
        rows: response.rows.map((row) => toExtensionRow(row)),
        granted: response.rows.map((row) => ({
            code: pluginRowCode(row.plugin_identifier),
            actions: row.granted.map((action) => ACTION_CODES[action]),
        })),
        editable: response.editable,
    };
}

/** The `PUT` body: every plugin row given, in the order given; codes and actions that are not a plugin's are left out. */
function toUpdate(granted: RolePermissionExtensionGrant[]): PluginRolePermissionsUpdate {
    return {
        plugins: granted
            .filter((grant) => grant.code.startsWith(PLUGIN_ROW_CODE_PREFIX))
            .map((grant) => ({
                plugin_identifier: grant.code.slice(PLUGIN_ROW_CODE_PREFIX.length),
                actions: grant.actions.flatMap((action) => {
                    const pluginAction = PLUGIN_ACTIONS[action];
                    return pluginAction ? [pluginAction] : [];
                }),
            })),
    };
}

/** Turns any failure into a {@link RolePermissionExtensionError} carrying the message to show. */
function failWithMessage<Value>(
    fallback: string,
    update?: PluginRolePermissionsUpdate,
    pluginNames?: ReadonlyMap<string, string>
): MonoTypeOperatorFunction<Value> {
    return catchError((error: unknown) =>
        throwError(
            () =>
                new RolePermissionExtensionError(pluginRolePermissionErrorMessage(error, fallback, update, pluginNames))
        )
    );
}
