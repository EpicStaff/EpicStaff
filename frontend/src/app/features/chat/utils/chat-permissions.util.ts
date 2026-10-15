import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../services/auth/permissions.service';

/** Test conversations belong to whoever builds desks (chats create or update); the chat service enforces the same. */
export function canTestChats(permissions: Pick<PermissionsService, 'can'>): boolean {
    return (
        permissions.can(ResourceCode.Chats, ActionCode.Create) || permissions.can(ResourceCode.Chats, ActionCode.Update)
    );
}
