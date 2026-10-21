import { Provider } from '@angular/core';
import { APP_STORAGE, ORG_SWITCH_URL_RULES, ROLE_PERMISSION_EXTENSIONS } from '@shared/services';

import { PluginRolePermissionExtension } from './role-permissions/plugin-role-permission-extension';
import { AvailablePluginsStorageService } from './services/available-plugins-storage.service';
import { PluginsAdminStorageService } from './services/plugins-admin-storage.service';
import { pluginRootUrl } from './utils/plugin-root-url.util';

/** The plugin feature's storages, cleared on logout and org switch. */
export function providePluginsStorages(): Provider[] {
    return [
        { provide: APP_STORAGE, useExisting: AvailablePluginsStorageService, multi: true },
        { provide: APP_STORAGE, useExisting: PluginsAdminStorageService, multi: true },
    ];
}

/**
 * What the plugin feature adds to other features through their tokens: its rows in the Roles matrix, and its
 * organization-switch rule (a plugin page keeps the plugin, not its path). The matrix extension checks the plugin flag
 * itself, because providers exist before the config loads.
 */
export function providePluginsExtensions(): Provider[] {
    return [
        { provide: ROLE_PERMISSION_EXTENSIONS, useExisting: PluginRolePermissionExtension, multi: true },
        { provide: ORG_SWITCH_URL_RULES, useValue: pluginRootUrl, multi: true },
    ];
}
