import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionRequirement } from '../../../services/auth/permissions.service';

/**
 * What the flow editor's toolbar buttons need before they are shown. The keymap hides the keys of a hidden button
 * from the shortcuts list, so the buttons and their keys read the same requirement.
 */
export const FLOW_ACTION_PERMISSIONS = {
    /** Export needs Flows:Export, Import needs Flows:Update; with neither there is no Export / Import menu. */
    exportImport: { resource: ResourceCode.Flows, anyOf: [ActionCode.Export, ActionCode.Update] },
    files: { resource: ResourceCode.Files, anyOf: [ActionCode.Read] },
    /** Run and Get cURL start the flow; Stop session stops one of its runs. */
    useFlow: { resource: ResourceCode.Flows, anyOf: [ActionCode.Use] },
} as const satisfies Record<string, PermissionRequirement>;
