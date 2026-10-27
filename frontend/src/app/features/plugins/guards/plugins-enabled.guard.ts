import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { ConfigService } from '../../../services/config';

/** `PLUGINS_ENABLED` off means no plugin endpoints behind nginx, so no plugin page may exist either. */
export const pluginsEnabledGuard: CanActivateFn = () =>
    inject(ConfigService).isPluginsEnabled || inject(Router).parseUrl(inject(PermissionsService).resolveDefaultRoute());
