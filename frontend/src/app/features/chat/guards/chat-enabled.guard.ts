import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { ConfigService } from '../../../services/config';

/** `CHAT_ENABLED` off means no chat service behind nginx, so the page must not exist either. */
export const chatEnabledGuard: CanActivateFn = () =>
    inject(ConfigService).isChatEnabled || inject(Router).parseUrl(inject(PermissionsService).resolveDefaultRoute());
