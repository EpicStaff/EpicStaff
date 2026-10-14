import { TestBed } from '@angular/core/testing';
import { ActionCode, ActivePermissions, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../services/auth/permissions.service';

/** Flows actions of a role that may change a flow but not run it: trigger nodes are read-only for it. */
export const FLOW_ACTIONS_WITHOUT_RUN: ActionCode[] = [ActionCode.Read, ActionCode.Update];
/** Flows actions of a role that may change and run a flow. */
export const FLOW_ACTIONS_WITH_RUN: ActionCode[] = [ActionCode.Read, ActionCode.Update, ActionCode.Run];
/** Flows actions of a custom role that may run but not change a flow. */
export const FLOW_ACTIONS_RUN_WITHOUT_UPDATE: ActionCode[] = [ActionCode.Read, ActionCode.Run];

/**
 * Gives the signed-in user exactly these permissions in the active org, through the real PermissionsService
 * (the test bed must provide HttpClient). A resource left out allows nothing. Callable before or after the
 * component under test is created: permission checks read a signal.
 */
export function grantPermissions(permissions: Partial<Record<ResourceCode, ActionCode[]>>): void {
    TestBed.inject(PermissionsService).setActivePermissions({
        org_id: 1,
        is_superadmin: false,
        role: { id: 1, name: 'Custom' },
        permissions: permissions as ActivePermissions['permissions'],
    });
}
