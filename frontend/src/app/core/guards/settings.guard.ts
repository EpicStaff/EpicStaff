import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../services/auth/permissions.service';

/**
 * Parent guard for /settings. Permissions are already loaded by bootstrapGuard
 * (parent canActivate on MainLayoutComponent), so this just checks access.
 */
export const settingsGuard: CanActivateFn = () => {
    const permissionsService = inject(PermissionsService);
    const router = inject(Router);
    return permissionsService.canOpenConfigureModelsDialog()
        ? true
        : router.parseUrl(permissionsService.resolveDefaultRoute());
};

/** /settings index redirect — sends the caller to their first accessible settings tab. */
export const settingsIndexGuard: CanActivateFn = () => {
    const permissionsService = inject(PermissionsService);
    const router = inject(Router);

    if (permissionsService.can(ResourceCode.LlmConfigs, ActionCode.Create)) {
        return router.parseUrl('/settings/quickstart');
    }
    if (permissionsService.can(ResourceCode.LlmConfigs, ActionCode.Read)) {
        return router.parseUrl('/settings/default-llms');
    }
    if (permissionsService.can(ResourceCode.Webhooks, ActionCode.Read)) {
        return router.parseUrl('/settings/webhook-triggers');
    }
    if (permissionsService.can(ResourceCode.Voice, ActionCode.Read)) {
        return router.parseUrl('/settings/voice');
    }
    if (permissionsService.canAny(ResourceCode.Secrets, [ActionCode.Read, ActionCode.Create])) {
        return router.parseUrl('/settings/secrets');
    }

    return router.parseUrl(permissionsService.resolveDefaultRoute());
};

/** Per-tab guard for /settings/secrets — requires Read OR Create on Secrets. */
export const secretsPermissionGuard: CanActivateFn = () => {
    const permissionsService = inject(PermissionsService);
    return (
        permissionsService.canAny(ResourceCode.Secrets, [ActionCode.Read, ActionCode.Create]) ||
        inject(Router).parseUrl(permissionsService.resolveDefaultRoute())
    );
};
