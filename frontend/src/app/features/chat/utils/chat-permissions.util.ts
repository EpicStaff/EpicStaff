import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../services/auth/permissions.service';

/**
 * Whoever builds desks (chats create or update), as opposed to an operator (read + use) who only answers visitors:
 * tests and the embed snippet are theirs. The chat service enforces the same.
 */
export function isDeskBuilder(permissions: Pick<PermissionsService, 'can'>): boolean {
    return (
        permissions.can(ResourceCode.Chats, ActionCode.Create) || permissions.can(ResourceCode.Chats, ActionCode.Update)
    );
}
