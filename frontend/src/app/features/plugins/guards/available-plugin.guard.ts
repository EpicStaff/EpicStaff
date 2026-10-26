import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { map } from 'rxjs';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { PLUGIN_PAGE_IDENTIFIER_PARAM } from '../pages/plugin-host-page/plugin-page.matcher';
import { AvailablePluginsStorageService } from '../services/available-plugins-storage.service';

/**
 * `/plugins/<identifier>/**` opens only a plugin the caller may open in the active organization (its available list);
 * anything else goes to the caller's default route. Also covers an org switch, which keeps the plugin address.
 */
export const availablePluginGuard: CanActivateFn = (route) => {
    const router = inject(Router);
    const permissionsService = inject(PermissionsService);
    const identifier = route.paramMap.get(PLUGIN_PAGE_IDENTIFIER_PARAM);
    return inject(AvailablePluginsStorageService)
        .loadForActiveOrg()
        .pipe(
            map((plugins) =>
                plugins.some((plugin) => plugin.identifier === identifier)
                    ? true
                    : router.parseUrl(permissionsService.resolveDefaultRoute())
            )
        );
};
